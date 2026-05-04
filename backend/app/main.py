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

from app.config import ModelConfig, PROJECT_ROOT, resolve_model_dir
from app.routers import ws, slides, transcripts, network, mode, install, settings
from app.utils.firewall import ensure_firewall_rule
from app.utils.network import SERVER_PORT, get_lan_ip

# VLM Base 모델: env 미설정이면 로컬 동봉본(qwen2.5-vl-7b-instruct) 우선,
# 없으면 HF repo_id로 fallback. 사용자가 env로 명시하면 그 값 그대로.
from pathlib import Path as _Path

def _resolve_vlm(value: str) -> str:
    p = _Path(value)
    if p.is_absolute():
        return value
    # 상대 경로면 다단계 폴백 (USER_DATA → INSTALL → PROJECT_ROOT)
    found = resolve_model_dir(_Path(value).name)
    if found is not None:
        return str(found)
    # PROJECT_ROOT 직접 검사 (호환성)
    candidate = PROJECT_ROOT / value
    if candidate.is_dir():
        return str(candidate)
    return value

def _vlm_default() -> str:
    """env 미지정 시 사용할 기본값. 로컬 디렉토리(USER_DATA → INSTALL → PROJECT_ROOT)가
    있으면 그 경로, 없으면 HF repo_id 로 fallback 해 다운로드 트리거.
    Electron 배포 환경에서 사용자별 모델 디렉토리를 우선 사용하기 위함."""
    found = resolve_model_dir("qwen2.5-vl-7b-instruct")
    return str(found) if found is not None else "Qwen/Qwen2.5-VL-7B-Instruct"


VLM_BASE_MODEL = _resolve_vlm(os.environ.get("VLM_BASE_MODEL") or _vlm_default())

# PyInstaller 번들 여부에 따라 frontend dist 경로 결정
if getattr(sys, 'frozen', False):
    _FRONTEND_DIST = os.path.join(sys._MEIPASS, 'frontend_dist')
else:
    _FRONTEND_DIST = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'dist')

# 모델 로딩 상태 추적
# status:
#   - "starting"          백엔드 부팅 중
#   - "wait_user_action"  사용자 다운로드 시작 클릭 대기 (VLM 미캐시 + 첫 실행)
#   - "loading"           모델 다운로드/메모리 로드 중
#   - "ready" / "ok"      준비 완료
#   - "error"             실패
# download (있을 때만):
#   - phase: "downloading" | "verifying"
#   - current_bytes, total_bytes, speed_bps, current_file
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
    "download": None,
}

# 사용자가 "다운로드 시작" 버튼 클릭 시 set — VLM 미캐시 첫 실행 흐름에서 대기 해제
_start_download_event = threading.Event()

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


def _is_local_path_format(value: str) -> bool:
    """value가 HF repo_id가 아니라 로컬 경로 형식인지 판별."""
    from pathlib import Path
    if Path(value).is_absolute():
        return True
    return value.startswith(("models/", "models\\", "./", "../", ".\\", "..\\"))


def _has_weights(directory) -> bool:
    """디렉토리에 모델 가중치 파일이 있는지 (HF safetensors/bin 또는 CT2 model.bin)."""
    from pathlib import Path
    p = Path(directory)
    if not p.is_dir():
        return False
    return (
        any(p.rglob("*.safetensors"))
        or any(p.rglob("*.bin"))
        or (p / "model.bin").is_file()
    )


def _is_cached(model_name: str) -> bool:
    """모델이 로컬 디렉토리 또는 HF 캐시에 있는지 판단.
      - 로컬 경로 형식(절대/`models/...`): 디렉토리 + 가중치 존재 검사
      - 단순 이름(piper, rapidocr): True (서비스 자체에서 처리)
      - HF repo_id: 캐시 검사
    """
    from pathlib import Path
    # 로컬 경로 형식
    if _is_local_path_format(model_name):
        p = Path(model_name)
        target = p if p.is_absolute() else (PROJECT_ROOT / model_name)
        return _has_weights(target)
    # 서비스 내부 처리 (piper, rapidocr 등)
    if "/" not in model_name:
        return True
    # HF repo_id → 캐시 검사
    try:
        from huggingface_hub import scan_cache_dir
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


def _hf_repo_total_bytes(repo_id: str) -> int:
    """HF 모델 repo의 전체 다운로드 사이즈를 합산 (시간↑, 대신 정확한 진행률)."""
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        info = api.model_info(repo_id, files_metadata=True)
        total = sum(s.size or 0 for s in info.siblings)
        return total
    except Exception as e:
        print(f"[Download] 전체 사이즈 조회 실패 ({repo_id}): {e}", flush=True)
        return 0


def _hf_cache_dir_for(repo_id: str):
    """HF 캐시 안 특정 repo의 디렉토리. 캐시 사이즈 polling 대상."""
    from pathlib import Path
    hf_home = Path(os.environ.get("HF_HOME", ""))
    safe = repo_id.replace("/", "--")
    return hf_home / "hub" / f"models--{safe}"


def _measure_dir_size(directory) -> int:
    """HF 캐시 디렉토리에서 실제 다운로드된 사이즈 측정.
    blobs/만 합산 — snapshots/는 blobs로 향하는 하드링크/복사본이라 중복 카운트되면
    실제보다 ~2배 부풀려진 값이 나옴 (Windows는 심볼릭 미지원 시 실제 복사 발생)."""
    from pathlib import Path
    p = Path(directory)
    if not p.is_dir():
        return 0
    # HF 캐시 표준 구조: <repo>/blobs/* (실제 파일들), <repo>/snapshots/<rev>/* (링크)
    blobs = p / "blobs"
    target = blobs if blobs.is_dir() else p
    total = 0
    try:
        for f in target.iterdir():
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _start_byte_progress_watcher(model_key: str, repo_id: str, total_bytes: int) -> threading.Event:
    """1초 간격으로 캐시 디렉토리 사이즈를 측정해 다운로드 진행률 emit.
    반환된 stop_event를 set하면 watcher 종료."""
    import time as _time
    stop_event = threading.Event()
    cache_dir = _hf_cache_dir_for(repo_id)

    def _run():
        last_bytes = 0
        last_time = _time.time()
        while not stop_event.is_set():
            current = _measure_dir_size(cache_dir)
            now = _time.time()
            elapsed = now - last_time
            speed = (current - last_bytes) / elapsed if elapsed > 0 else 0

            # Phase 판정:
            #   - blobs/가 전체 사이즈 도달 + snapshot_download 미반환 = "finalizing"
            #     (Windows에서 blobs → snapshots 하드링크/복사 단계, 수 분 소요)
            #   - 그 외 = "downloading"
            if total_bytes > 0 and current >= total_bytes:
                phase = "finalizing"
            else:
                phase = "downloading"

            _model_status["download"] = {
                "phase": phase,
                "current_bytes": current,
                "total_bytes": total_bytes,
                "speed_bps": int(max(0, speed)),
            }
            # 모델 카드 진행률도 동기화
            if total_bytes > 0:
                pct = min(99, int(current * 100 / total_bytes))
                if pct != _model_status["models"][model_key]["progress"]:
                    _model_status["models"][model_key]["progress"] = pct
                    _emit_status()
            else:
                _emit_status()
            last_bytes = current
            last_time = now
            stop_event.wait(1.0)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return stop_event


def _download_one(model_key: str, repo_id: str):
    """단일 모델 HuggingFace 다운로드 — ThreadPoolExecutor에서 병렬 실행.
    repo_id가 로컬 경로 형식이면 (예: 'models/...') 다운로드 대신 명확한 에러.
    바이트 단위 진행률을 watcher 스레드로 emit."""
    if _is_local_path_format(repo_id):
        raise RuntimeError(
            f"{model_key.upper()} 모델이 지정된 로컬 경로에 없습니다: {repo_id}\n"
            f"  해결: 'npm run setup' 재실행 또는 .env의 {model_key.upper()}_MODEL을\n"
            f"        HuggingFace repo_id로 변경 (예: Qwen/Qwen2.5-VL-7B-Instruct)."
        )
    from huggingface_hub import snapshot_download
    _thread_model_key.key = model_key
    _model_status["models"][model_key]["status"] = "loading"

    # 전체 사이즈 미리 조회 (실패해도 다운로드 자체는 진행)
    total_bytes = _hf_repo_total_bytes(repo_id)
    if total_bytes > 0:
        gb = total_bytes / (1024 ** 3)
        print(f"[다운로드 시작] {model_key.upper()}: {repo_id} ({gb:.2f} GB)", flush=True)
    else:
        print(f"[다운로드 시작] {model_key.upper()}: {repo_id}", flush=True)
    _emit_status()

    # 바이트 단위 진행률 watcher
    stop_watcher = _start_byte_progress_watcher(model_key, repo_id, total_bytes)
    try:
        snapshot_download(repo_id=repo_id)
    finally:
        stop_watcher.set()

    _model_status["models"][model_key]["progress"] = 100
    # 다운로드 완료 — phase 전환 (검증/초기화)
    _model_status["download"] = {
        "phase": "verifying",
        "current_bytes": total_bytes,
        "total_bytes": total_bytes,
        "speed_bps": 0,
    }
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

    # ── 첫 실행 사용자 액션 대기 ──────────────────────────────────────
    # VLM 미캐시 + 슬라이드 전용 모드 = 신규 사용자 첫 실행 → 다운로드 마법사 UI 표시 후
    # "다운로드 시작" 클릭까지 대기. 사용자 동의 없이 16GB 자동 다운로드 안 함.
    if skip_models and any(k == "vlm" for k, _ in to_download):
        _model_status["status"] = "wait_user_action"
        _model_status["message"] = "사용자 다운로드 시작 클릭 대기 중"
        _emit_status()
        print("[설치] 사용자 액션 대기 중 — 프론트의 '다운로드 시작' 버튼 필요", flush=True)
        _start_download_event.wait()
        print("[설치] 사용자 액션 수신 — 다운로드 진행", flush=True)
        _model_status["status"] = "loading"
        _emit_status()

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
        # VLM을 방금 다운로드했다면 검증 단계 표시 — 파일 존재 + 사이즈 sanity 검사
        vlm_just_downloaded = any(k == "vlm" for k, _ in to_download)
        if vlm_just_downloaded:
            import time as _time
            _model_status["download"] = {
                "phase": "verifying",
                "current_bytes": _model_status["download"].get("current_bytes", 0) if _model_status["download"] else 0,
                "total_bytes": _model_status["download"].get("total_bytes", 0) if _model_status["download"] else 0,
                "speed_bps": 0,
            }
            _model_status["message"] = "AI 엔진 준비 중..."
            _emit_status()
            print("[검증] 다운로드 결과 무결성 검사 중...", flush=True)

            # 실제 검증: 캐시 디렉토리 존재 + safetensors 1개 이상 + 파일 헤더 읽기로 손상 확인
            from pathlib import Path
            cache_dir = _hf_cache_dir_for(VLM_BASE_MODEL) if not _is_local_path_format(VLM_BASE_MODEL) else Path(VLM_BASE_MODEL)
            safetensors = list(cache_dir.rglob("*.safetensors"))
            if not safetensors:
                raise RuntimeError(f"VLM 검증 실패 — safetensors 파일이 없습니다: {cache_dir}")
            # 각 shard 파일 헤더 8바이트 읽기 (2~5초 — 사용자에게 검증 단계 보여주기)
            for sf in safetensors:
                try:
                    with open(sf, "rb") as f:
                        f.read(8)
                except OSError as e:
                    raise RuntimeError(f"VLM 검증 실패 — 파일 손상: {sf} ({e})")
            _time.sleep(0.5)  # 검증 단계 UI에 잠시 보이도록
            print(f"[검증] 완료 ({len(safetensors)}개 파일 OK)", flush=True)

        _model_status["download"] = None
        _model_status["status"] = "ready"
        _model_status["message"] = "슬라이드 번역 전용 모드 — 준비 완료"
        _model_status["progress"] = 100
        _emit_status()
        mode._current_mode = mode.Mode.SLIDE
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
        mode._current_mode = mode.Mode.REALTIME
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
app.include_router(install.router)
app.include_router(settings.router)


@app.api_route("/health", methods=["GET", "HEAD"], tags=["Health"])
async def health():
    return _model_status


_assets_dir = os.path.join(_FRONTEND_DIST, 'assets')
if os.path.isdir(_assets_dir):
    app.mount('/assets', StaticFiles(directory=_assets_dir), name='frontend_assets')


@app.get('/{path:path}', include_in_schema=False)
async def spa_fallback(path: str):
    # 1) frontend/dist 최상단의 정적 파일 (ort.all.min.js, vad-bundle.min.js,
    #    silero_vad_*.onnx, vite.svg 등)은 직접 서빙. 안 그러면 index.html이
    #    대신 반환되어 JS 파서가 '<' 토큰 에러로 죽음.
    if path:
        candidate = os.path.join(_FRONTEND_DIST, path)
        try:
            real_candidate = os.path.realpath(candidate)
            real_dist = os.path.realpath(_FRONTEND_DIST)
            if (
                os.path.commonpath([real_candidate, real_dist]) == real_dist
                and os.path.isfile(real_candidate)
            ):
                return FileResponse(real_candidate)
        except (OSError, ValueError):
            pass
    # 2) SPA 라우트 (/, /lecturer 등) → index.html
    index = os.path.join(_FRONTEND_DIST, 'index.html')
    if os.path.isfile(index):
        return FileResponse(index)
    return {'service': 'Aunion AI Backend', 'version': '1.0.0'}
