import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ModelConfig
from app.routers import ws, slides

# 모델 로딩 상태 추적
_model_status = {"status": "starting", "message": "백엔드 시작 중..."}


def _is_cached(model_name: str) -> bool:
    """HuggingFace 캐시에 모델이 있는지 확인"""
    try:
        from huggingface_hub import scan_cache_dir
        cache_info = scan_cache_dir()
        for repo in cache_info.repos:
            if repo.repo_id == model_name:
                return True
        return False
    except Exception:
        return False


def _set_status(message: str):
    """로딩 상태 메시지 업데이트"""
    _model_status["message"] = message
    print(f"[상태] {message}")


def _load_models_sync():
    """동기 모델 로딩 — 스레드풀에서 실행"""
    print("=" * 50)
    print("Aunion AI Backend 시작")
    print("=" * 50)

    # ASR
    cached = _is_cached(f"Systran/faster-whisper-{ModelConfig.ASR_MODEL}")
    _set_status(f"ASR 모델 {'로딩' if cached else '다운로드'} 중... (1/4) - faster-whisper {ModelConfig.ASR_MODEL}")
    from app.services.asr_service import ASRService
    asr_service = ASRService(
        model_name=ModelConfig.ASR_MODEL,
        device=ModelConfig.ASR_DEVICE,
        dtype=ModelConfig.ASR_DTYPE,
    )
    ws.set_asr_service(asr_service)
    _set_status(f"ASR 완료 ✓ (1/4)")
    print(f"[ASR] {ModelConfig.ASR_MODEL} 로드 완료")

    # NMT
    cached = _is_cached(ModelConfig.NMT_MODEL)
    _set_status(f"NMT 모델 {'로딩' if cached else '다운로드'} 중... (2/4) - {ModelConfig.NMT_MODEL}")
    from app.services.nmt_service import NMTService
    nmt_service = NMTService(
        model_name=ModelConfig.NMT_MODEL,
        device=ModelConfig.NMT_DEVICE
    )
    ws.set_nmt_service(nmt_service)
    slides.set_nmt_service(nmt_service)
    _set_status(f"NMT 완료 ✓ (2/4)")
    print(f"[NMT] {ModelConfig.NMT_MODEL} 로드 완료")

    # TTS
    cached = _is_cached(ModelConfig.TTS_MODEL)
    _set_status(f"TTS 모델 {'로딩' if cached else '다운로드'} 중... (3/4) - Supertonic-2 ONNX")
    from app.services.tts_service import TTSService
    tts_service = TTSService(
        model_name=ModelConfig.TTS_MODEL,
        device=ModelConfig.TTS_DEVICE,
    )
    ws.set_tts_service(tts_service)
    _set_status(f"TTS 완료 ✓ (3/4)")
    print("[TTS] Supertonic-2 ONNX 로드 완료")

    # OCR
    _set_status("OCR 모델 로딩 중... (4/4) - RapidOCR")
    from app.services.ocr_service import OCRService
    ocr_service = OCRService()
    ws.set_ocr_service(ocr_service)
    slides.set_ocr_service(ocr_service)
    _set_status("OCR 완료 ✓ (4/4)")
    print("[OCR] RapidOCR 로드 완료")

    print("=" * 50)
    print("모든 모델 로드 완료!")
    print("=" * 50)

    _model_status["status"] = "ok"
    _model_status["message"] = "모든 모델 로드 완료 ✓"


async def _load_models():
    """모델 로딩을 스레드풀에서 실행 — 이벤트 루프를 막지 않음"""
    try:
        await asyncio.to_thread(_load_models_sync)
    except Exception as e:
        _model_status["status"] = "error"
        _model_status["message"] = f"모델 로딩 실패: {e}"
        print(f"[ERROR] 모델 로딩 실패: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버를 즉시 시작하고, 모델 로딩은 백그라운드에서 진행"""
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

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(ws.router)
app.include_router(slides.router)


@app.get("/", tags=["Root"])
async def root():
    return {
        "service": "Aunion AI Backend",
        "version": "1.0.0",
        "endpoints": {
            "websocket": "/ws/pipeline",
            "slides": {
                "upload": "POST /slides/upload",
                "status": "GET /slides/status/{slide_id}",
                "pages": "GET /slides/pages/{slide_id}",
            },
        },
    }


@app.get("/health", tags=["Health"])
async def health():
    return _model_status
