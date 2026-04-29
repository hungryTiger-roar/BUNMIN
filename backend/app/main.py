import asyncio
import concurrent.futures
import contextlib
import json
import os
import sys
import threading
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import ModelConfig
from app.routers import ws, slides, transcripts, network, mode
from app.utils.firewall import ensure_firewall_rule
from app.utils.network import SERVER_PORT, get_lan_ip

# VLM Base 모델 (translate_slide_v3.py와 동일한 env 사용)
# .env 값이 상대 경로면 프로젝트 루트 기준 절대 경로로 변환, repo_id면 그대로
from pathlib import Path as _Path
_PROJECT_ROOT = _Path(__file__).parent.parent.parent
def _resolve_vlm(value: str) -> str:
    p = _Path(value)
    if p.is_absolute():
        return value
    candidate = _PROJECT_ROOT / value
    return str(candidate) if candidate.is_dir() else value

VLM_BASE_MODEL = _resolve_vlm(os.environ.get("VLM_BASE_MODEL", "Qwen/Qwen3-VL-8B-Instruct"))

# PyInstaller 번들 여부에 따라 frontend dist 경로 결정
if getattr(sys, 'frozen', False):
    _FRONTEND_DIST = os.path.join(sys._MEIPASS, 'frontend_dist')
else:
    _FRONTEND_DIST = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'dist')

# 모델 로딩 상태 추적
_model_status = {
    "status": "starting",
    "message": "백엔드 시작 중...",
    "progress": 0,
    "models": {
        "asr": {"status": "pending", "progress": 0, "label": "ASR (음성인식)", "desc": ModelConfig.ASR_MODEL},
        "nmt_asr": {"status": "pending", "progress": 0, "label": "NMT-ASR (실시간 번역)", "desc": ModelConfig.NMT_ASR_MODEL},
        "ocr": {"status": "pending", "progress": 0, "label": "OCR (문자인식)", "desc": ModelConfig.OCR_MODEL},
        "vlm": {"status": "pending", "progress": 0, "label": "VLM (슬라이드 번역)", "desc": VLM_BASE_MODEL},
    },
}

# 병렬 다운로드 시 스레드별 모델 키 추적
_thread_model_key = threading.local()


def _start_health_thread(port: int = 18765):
    """GIL에 무관하게 항상 응답하는 별도 스레드 health 서버."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(_model_status, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[Health] 전용 서버 시작: port {port}", flush=True)


def _is_cached(model_name: str) -> bool:
    """HuggingFace 캐시에 모델이 완전히 있는지 확인.
    incomplete 파일이 있거나 모델 가중치(10MB 이상 파일)가 없으면 False.
    슬래시 없는 값(로컬 식별자)은 True로 처리 (서비스 자체에서 관리).
    로컬 디렉토리 경로면 가중치 파일 존재로 판단."""
    from pathlib import Path
    # 로컬 절대경로 (Windows: C:\..., Linux: /...) → 디렉토리에 가중치 파일 존재 시 캐시됨
    p = Path(model_name)
    if p.is_absolute():
        if not p.is_dir():
            return False
        weights = list(p.glob("*.safetensors")) + list(p.glob("*.bin"))
        return len(weights) > 0
    if "/" not in model_name:
        return True
    try:
        from huggingface_hub import scan_cache_dir
        from pathlib import Path
        cache_info = scan_cache_dir()
        for repo in cache_info.repos:
            if repo.repo_id == model_name:
                blobs_dir = Path(repo.repo_path) / "blobs"
                if list(blobs_dir.glob("*.incomplete")):
                    return False
                large_files = [f for f in blobs_dir.iterdir() if f.stat().st_size > 10 * 1024 * 1024]
                if not large_files:
                    return False
                return True
        return False
    except Exception:
        return False


def _emit_status():
    """모델 상태를 stdout으로 내보냄.
    ensure_ascii=True: 한글을 \\uXXXX 이스케이프로 출력 → 인코딩 무관하게 안전"""
    print(f"__AUNION_STATUS__:{json.dumps(_model_status, ensure_ascii=True)}", flush=True)


def _set_status(message: str, progress: int | None = None):
    """전체 로딩 상태 메시지 업데이트"""
    _model_status["message"] = message
    if progress is not None:
        _model_status["progress"] = progress
    print(f"[상태] {message}", flush=True)
    _emit_status()


# ── 병렬 다운로드용 tqdm 전역 패치 ──────────────────────────────────────────
@contextlib.contextmanager
def _track_all_downloads():
    """병렬 다운로드 중 thread-local로 모델별 tqdm 진행률 추적.
    tqdm.tqdm(std)와 tqdm.auto.tqdm 양쪽 패치 → 환경 차이 방어."""
    import tqdm as _tqdm_std
    import tqdm.auto as _tqdm_auto

    original_std = _tqdm_std.tqdm.update
    original_auto = _tqdm_auto.tqdm.update

    def _patched(self, n=1):
        if self.__class__ is _tqdm_std.tqdm:
            original_std(self, n)
        else:
            original_auto(self, n)
        model_key = getattr(_thread_model_key, 'key', None)
        if model_key and self.total and self.total > 0:
            pct = min(99, int(self.n * 100 / self.total))
            entry = _model_status["models"][model_key]
            # 5% 단위로만 emit — stdout 폭주 방지
            if pct >= entry["progress"] + 5 or pct >= 99:
                entry["progress"] = pct
                _emit_status()

    _tqdm_std.tqdm.update = _patched
    if _tqdm_auto.tqdm is not _tqdm_std.tqdm:
        _tqdm_auto.tqdm.update = _patched
    try:
        yield
    finally:
        _tqdm_std.tqdm.update = original_std
        if _tqdm_auto.tqdm is not _tqdm_std.tqdm:
            _tqdm_auto.tqdm.update = original_auto


def _download_one(model_key: str, repo_id: str):
    """단일 모델 HuggingFace 다운로드 — ThreadPoolExecutor에서 병렬 실행"""
    from huggingface_hub import snapshot_download
    _thread_model_key.key = model_key  # 이 스레드의 모델 키 등록
    _model_status["models"][model_key]["status"] = "loading"
    _emit_status()
    print(f"[다운로드 시작] {model_key.upper()}: {repo_id}", flush=True)
    snapshot_download(repo_id=repo_id)
    _model_status["models"][model_key]["progress"] = 100
    _emit_status()
    print(f"[다운로드 완료] {model_key.upper()}", flush=True)


# ── 모델 로딩 메인 함수 ────────────────────────────────────────────────────
def _load_models_sync():
    """동기 모델 로딩 — 스레드풀에서 실행.
    1단계: 미캐시 모델 병렬 다운로드
    2단계: 순차 메모리 로딩 (GIL 안전)"""
    print("=" * 50, flush=True)
    print("Aunion AI Backend 시작", flush=True)
    print("=" * 50, flush=True)

    # 슬라이드 번역 전용 모드 - 실시간 모델 스킵 (VLM은 다운로드만 진행)
    skip_models = os.environ.get("SKIP_STARTUP_MODELS", "").lower() == "true"
    if skip_models:
        print("[모드] 슬라이드 번역 전용 - ASR/NMT/OCR 스킵 (VLM은 다운로드 진행)", flush=True)
        for key in ["asr", "nmt_asr", "ocr"]:
            _model_status["models"][key]["status"] = "skipped"
        _emit_status()

    # ── 1단계: 병렬 다운로드 ─────────────────────────────────────────
    # VLM은 사용 시점에 메모리 로드되지만, 다운로드는 미리 받아둠 (~17GB 첫 사용 대기 회피)
    model_repos = [] if skip_models else [
        ("asr",     ModelConfig.ASR_MODEL),
        ("nmt_asr", ModelConfig.NMT_ASR_MODEL),
    ]
    model_repos.append(("vlm", VLM_BASE_MODEL))

    to_download = [(key, repo) for key, repo in model_repos if not _is_cached(repo)]

    if to_download:
        names = ", ".join(k.upper() for k, _ in to_download)
        _set_status(f"모델 다운로드 중... ({names}) 병렬 진행", progress=0)
        print(f"[다운로드] {len(to_download)}개 모델 병렬 다운로드 시작", flush=True)

        with _track_all_downloads():
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(to_download)) as executor:
                futures = {
                    executor.submit(_download_one, key, repo): key
                    for key, repo in to_download
                }
                for future in concurrent.futures.as_completed(futures):
                    key = futures[future]
                    try:
                        future.result()
                        print(f"[완료] {key.upper()} 다운로드 성공", flush=True)
                    except Exception as e:
                        raise RuntimeError(f"{key.upper()} 다운로드 실패: {e}")

        _set_status("모든 다운로드 완료, 모델 초기화 시작...", progress=10)
        print("[다운로드] 전체 완료", flush=True)

        # 다운로드 완료 표시를 잠깐 보여준 뒤 로딩 단계로 재설정
        # VLM은 메모리 로드를 startup에서 안 함 (실시간 스택과 VRAM 충돌, 사용 시점에 lazy 로드)
        for key, repo in model_repos:
            if "/" not in repo:
                continue
            if key == "vlm":
                continue
            _model_status["models"][key]["status"] = "loading"
            _model_status["models"][key]["progress"] = 0
        _emit_status()
    else:
        _set_status("모든 모델 캐시 확인됨, 초기화 시작...", progress=10)

    # VLM은 다운로드 완료(또는 캐시됨) 시점에 done 처리 — 메모리 로드는 사용 시점에 lazy
    _model_status["models"]["vlm"]["status"] = "done"
    _model_status["models"]["vlm"]["progress"] = 100
    _emit_status()

    # 슬라이드 전용 모드는 여기서 종료 (실시간 스택 메모리 로드 안 함)
    if skip_models:
        _model_status["status"] = "ready"
        _model_status["message"] = "슬라이드 번역 전용 모드 — 준비 완료"
        _model_status["progress"] = 100
        _emit_status()
        print("=" * 50, flush=True)
        print("[모드] 슬라이드 번역 전용 모드 — VLM 다운로드 완료, 메모리 로드는 사용 시점에", flush=True)
        print("=" * 50, flush=True)
        return

    # ── 2단계: 순차 메모리 로딩 ──────────────────────────────────────
    import traceback
    failed_models = []

    # ASR
    _model_status["models"]["asr"]["status"] = "loading"
    _emit_status()
    _set_status(f"ASR 초기화 중... (1/3) - {ModelConfig.ASR_MODEL}", progress=15)
    try:
        from app.services.asr_service import ASRService
        asr_service = ASRService(
            model_name=ModelConfig.ASR_MODEL,
            device=ModelConfig.ASR_DEVICE,
            dtype=ModelConfig.ASR_DTYPE,
        )
        ws.set_asr_service(asr_service)
        _model_status["models"]["asr"]["status"] = "done"
        _model_status["models"]["asr"]["progress"] = 100
        _set_status("ASR 완료 ✓ (1/3)", progress=40)
        print(f"[ASR] {ModelConfig.ASR_MODEL} 초기화 완료", flush=True)
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ASR ERROR] {e}\n{tb}", flush=True)
        _model_status["models"]["asr"]["status"] = "error"
        _set_status(f"ASR 실패: {e}", progress=40)
        failed_models.append(f"ASR: {e}")

    # NMT-ASR (실시간 번역)
    _model_status["models"]["nmt_asr"]["status"] = "loading"
    _emit_status()
    _set_status(f"NMT-ASR 초기화 중... (2/3) - {ModelConfig.NMT_ASR_MODEL}", progress=45)
    try:
        from app.services.nmt_service import NMTService
        nmt_asr_service = NMTService(
            model_name=ModelConfig.NMT_ASR_MODEL,
            device=ModelConfig.NMT_ASR_DEVICE,
            dtype=ModelConfig.NMT_ASR_DTYPE,
        )
        ws.set_nmt_service(nmt_asr_service)
        _model_status["models"]["nmt_asr"]["status"] = "done"
        _model_status["models"]["nmt_asr"]["progress"] = 100
        _set_status("NMT-ASR 완료 ✓ (2/3)", progress=70)
        print(f"[NMT-ASR] {ModelConfig.NMT_ASR_MODEL} 초기화 완료", flush=True)
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[NMT-ASR ERROR] {e}\n{tb}", flush=True)
        _model_status["models"]["nmt_asr"]["status"] = "error"
        _set_status(f"NMT-ASR 실패: {e}", progress=70)
        failed_models.append(f"NMT-ASR: {e}")

    # OCR
    _model_status["models"]["ocr"]["status"] = "loading"
    _emit_status()
    _ocr_model_name = ModelConfig.OCR_MODEL
    _set_status(f"OCR 초기화 중... (3/3) - {_ocr_model_name}", progress=75)
    try:
        from app.services.ocr_service import OCRService
        ocr_service = OCRService()
        ws.set_ocr_service(ocr_service)
        slides.set_ocr_service(ocr_service)
        _model_status["models"]["ocr"]["status"] = "done"
        _model_status["models"]["ocr"]["progress"] = 100
        _set_status("OCR 완료 ✓ (3/3)", progress=100)
        print(f"[OCR] {_ocr_model_name} 초기화 완료", flush=True)
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[OCR ERROR] {e}\n{tb}", flush=True)
        _model_status["models"]["ocr"]["status"] = "error"
        _set_status(f"OCR 실패: {e}", progress=100)
        failed_models.append(f"OCR: {e}")

    print("=" * 50, flush=True)
    if failed_models:
        print(f"[경고] 일부 모델 초기화 실패: {', '.join(failed_models)}", flush=True)
    else:
        print("모든 모델 초기화 완료!", flush=True)
    print("=" * 50, flush=True)

    if failed_models:
        _model_status["status"] = "error"
        _model_status["message"] = f"모델 로드 실패: {'; '.join(failed_models)}"
        _model_status["progress"] = 100
    else:
        _model_status["status"] = "ok"
        _model_status["message"] = "모든 모델 로드 완료 ✓"
        _model_status["progress"] = 100
    _emit_status()  # Electron에 완료/실패 신호 전달


async def _load_models():
    """모델 로딩을 스레드풀에서 실행 — 이벤트 루프를 막지 않음"""
    try:
        await asyncio.to_thread(_load_models_sync)
    except Exception as e:
        _model_status["status"] = "error"
        _model_status["message"] = f"모델 로딩 실패: {e}"
        print(f"[ERROR] 모델 로딩 실패: {e}", flush=True)
        _emit_status()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _start_health_thread()
    ensure_firewall_rule(SERVER_PORT)
    print(f"[Network] LAN 접속 주소: http://{get_lan_ip()}:{SERVER_PORT}", flush=True)
    task = asyncio.create_task(_load_models())
    yield
    task.cancel()
    print("서버 종료 중...")


app = FastAPI(
    title="Aunion AI Backend",
    description="실시간 강의 번역 AI 파이프라인",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws.router)
app.include_router(slides.router)
app.include_router(transcripts.router)
app.include_router(network.router)
app.include_router(mode.router)


@app.api_route("/health", methods=["GET", "HEAD"], tags=["Health"])
async def health():
    return _model_status


_assets_dir = os.path.join(_FRONTEND_DIST, 'assets')
if os.path.isdir(_assets_dir):
    app.mount('/assets', StaticFiles(directory=_assets_dir), name='frontend_assets')


@app.get('/{path:path}', include_in_schema=False)
async def spa_fallback(path: str):
    index = os.path.join(_FRONTEND_DIST, 'index.html')
    if os.path.isfile(index):
        return FileResponse(index)
    return {'service': 'Aunion AI Backend', 'version': '1.0.0'}
