from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ModelConfig
from app.routers import ws, slides


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 모델 로드/언로드"""
    print("=" * 50)
    print("Aunion AI Backend 시작")
    print("=" * 50)
    print("모델 로딩 중...")

    # ASR 서비스 초기화
    from app.services.asr_service import ASRService
    asr_service = ASRService(
        model_name=ModelConfig.ASR_MODEL,
        device=ModelConfig.ASR_DEVICE
    )
    ws.set_asr_service(asr_service)
    print(f"[ASR] {ModelConfig.ASR_MODEL} 로드 완료")

    # NMT 서비스 초기화 (ASR 전용 / OCR 전용 분리)
    from app.services.nmt_service import NMTService
    asr_nmt_service = NMTService(
        model_name=ModelConfig.NMT_MODEL,
        device=ModelConfig.NMT_DEVICE
    )
    ocr_nmt_service = NMTService(
        model_name=ModelConfig.NMT_MODEL,
        device=ModelConfig.NMT_DEVICE
    )
    ws.set_asr_nmt_service(asr_nmt_service)
    ws.set_ocr_nmt_service(ocr_nmt_service)
    slides.set_nmt_service(ocr_nmt_service)
    print(f"[NMT] {ModelConfig.NMT_MODEL} x2 로드 완료 (ASR 전용 / OCR 전용)")

    # TTS 서비스 초기화
    from app.services.tts_service import TTSService
    tts_service = TTSService(model_dir=str(ModelConfig.TTS_MODEL_DIR))
    ws.set_tts_service(tts_service)
    print("[TTS] Piper TTS 로드 완료")

    # OCR 서비스 초기화
    from app.services.ocr_service import OCRService
    ocr_service = OCRService()
    ws.set_ocr_service(ocr_service)
    slides.set_ocr_service(ocr_service)
    print("[OCR] RapidOCR 로드 완료")

    print("=" * 50)
    print("모든 모델 로드 완료!")
    print("=" * 50)

    yield

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
    return {"status": "ok"}
