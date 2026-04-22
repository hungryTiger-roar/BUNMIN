"""
동적 모델 모드 전환 API

슬라이드 번역 모드 ↔ 실시간 번역 모드 전환
- /api/mode/slide: VLM 온디맨드 로드, 실시간 모델 언로드
- /api/mode/realtime: VLM 언로드, ASR/NMT/TTS/OCR 로드
- /api/mode/current: 현재 모드 확인
"""

import asyncio
import gc
from enum import Enum

import torch
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/mode", tags=["Mode"])


class Mode(str, Enum):
    SLIDE = "slide"
    REALTIME = "realtime"
    IDLE = "idle"


class ModeResponse(BaseModel):
    mode: str
    message: str
    models_loaded: list[str]


# 현재 모드 상태
_current_mode: Mode = Mode.IDLE
_mode_lock = asyncio.Lock()

# 서비스 참조 (main.py에서 설정)
_asr_service = None
_nmt_asr_service = None
_nmt_ocr_service = None
_tts_service = None
_ocr_service = None


def set_services(asr=None, nmt_asr=None, nmt_ocr=None, tts=None, ocr=None):
    """main.py에서 서비스 참조 설정"""
    global _asr_service, _nmt_asr_service, _nmt_ocr_service, _tts_service, _ocr_service
    _asr_service = asr
    _nmt_asr_service = nmt_asr
    _nmt_ocr_service = nmt_ocr
    _tts_service = tts
    _ocr_service = ocr


def get_current_mode() -> Mode:
    return _current_mode


def _unload_vlm():
    """VLM 모델 언로드 (GPU 메모리 해제)"""
    try:
        from translate_slide_v3 import unload_vlm_model
        unload_vlm_model()
        print("[Mode] VLM 모델 언로드 완료")
        return True
    except ImportError:
        print("[Mode] translate_slide_v3 모듈 없음")
        return False
    except Exception as e:
        print(f"[Mode] VLM 언로드 실패: {e}")
        return False


def _unload_realtime_models():
    """실시간 모델들 언로드 (ASR/NMT/TTS/OCR)"""
    global _asr_service, _nmt_asr_service, _nmt_ocr_service, _tts_service, _ocr_service

    unloaded = []

    # ASR 언로드
    if _asr_service is not None:
        try:
            del _asr_service
            _asr_service = None
            unloaded.append("asr")
        except:
            pass

    # NMT-ASR 언로드
    if _nmt_asr_service is not None:
        try:
            del _nmt_asr_service
            _nmt_asr_service = None
            unloaded.append("nmt_asr")
        except:
            pass

    # NMT-OCR 언로드
    if _nmt_ocr_service is not None:
        try:
            del _nmt_ocr_service
            _nmt_ocr_service = None
            unloaded.append("nmt_ocr")
        except:
            pass

    # TTS 언로드
    if _tts_service is not None:
        try:
            del _tts_service
            _tts_service = None
            unloaded.append("tts")
        except:
            pass

    # OCR 언로드
    if _ocr_service is not None:
        try:
            del _ocr_service
            _ocr_service = None
            unloaded.append("ocr")
        except:
            pass

    # GPU 메모리 정리
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print(f"[Mode] 실시간 모델 언로드 완료: {unloaded}")
    return unloaded


@router.get("/current", response_model=ModeResponse)
async def get_mode():
    """현재 모드 확인"""
    models_loaded = []

    if _asr_service is not None:
        models_loaded.append("asr")
    if _nmt_asr_service is not None:
        models_loaded.append("nmt_asr")
    if _nmt_ocr_service is not None:
        models_loaded.append("nmt_ocr")
    if _tts_service is not None:
        models_loaded.append("tts")
    if _ocr_service is not None:
        models_loaded.append("ocr")

    # VLM 로드 여부 확인
    try:
        from translate_slide_v3 import is_vlm_loaded
        if is_vlm_loaded():
            models_loaded.append("vlm")
    except:
        pass

    return ModeResponse(
        mode=_current_mode.value,
        message=f"현재 모드: {_current_mode.value}",
        models_loaded=models_loaded
    )


@router.post("/slide", response_model=ModeResponse)
async def switch_to_slide_mode():
    """슬라이드 번역 모드로 전환 (실시간 모델 언로드, VLM 온디맨드)"""
    global _current_mode

    async with _mode_lock:
        if _current_mode == Mode.SLIDE:
            return ModeResponse(
                mode=Mode.SLIDE.value,
                message="이미 슬라이드 번역 모드입니다",
                models_loaded=["vlm (on-demand)"]
            )

        # 실시간 모델 언로드
        unloaded = await asyncio.to_thread(_unload_realtime_models)

        _current_mode = Mode.SLIDE

        return ModeResponse(
            mode=Mode.SLIDE.value,
            message=f"슬라이드 번역 모드로 전환 완료. 언로드: {unloaded}",
            models_loaded=["vlm (on-demand)"]
        )


@router.post("/realtime", response_model=ModeResponse)
async def switch_to_realtime_mode():
    """실시간 번역 모드로 전환 (VLM 언로드, ASR/NMT/TTS/OCR 로드)"""
    global _current_mode, _asr_service, _nmt_asr_service, _nmt_ocr_service, _tts_service, _ocr_service

    async with _mode_lock:
        if _current_mode == Mode.REALTIME:
            return ModeResponse(
                mode=Mode.REALTIME.value,
                message="이미 실시간 번역 모드입니다",
                models_loaded=["asr", "nmt_asr", "nmt_ocr", "tts", "ocr"]
            )

        # VLM 언로드
        await asyncio.to_thread(_unload_vlm)

        # 실시간 모델 로드
        loaded = []

        try:
            from app.config import ModelConfig
            from app.services.asr_service import ASRService
            from app.services.nmt_service import NMTService
            from app.services.tts_service import TTSService
            from app.services.ocr_service import OCRService
            from app.routers import ws, slides

            # ASR
            print("[Mode] ASR 로드 중...")
            _asr_service = ASRService(
                model_name=ModelConfig.ASR_MODEL,
                device=ModelConfig.ASR_DEVICE,
                dtype=ModelConfig.ASR_DTYPE,
            )
            ws.set_asr_service(_asr_service)
            loaded.append("asr")

            # NMT-ASR
            print("[Mode] NMT-ASR 로드 중...")
            _nmt_asr_service = NMTService(
                model_name=ModelConfig.NMT_ASR_MODEL,
                device=ModelConfig.NMT_ASR_DEVICE,
                dtype=ModelConfig.NMT_ASR_DTYPE,
            )
            ws.set_nmt_service(_nmt_asr_service)
            loaded.append("nmt_asr")

            # NMT-OCR
            print("[Mode] NMT-OCR 로드 중...")
            _nmt_ocr_service = NMTService(
                model_name=ModelConfig.NMT_OCR_MODEL,
                device=ModelConfig.NMT_OCR_DEVICE,
                dtype=ModelConfig.NMT_OCR_DTYPE,
            )
            slides.set_nmt_service(_nmt_ocr_service)
            loaded.append("nmt_ocr")

            # TTS
            print("[Mode] TTS 로드 중...")
            _tts_service = TTSService(
                model_name=ModelConfig.TTS_MODEL,
                device=ModelConfig.TTS_DEVICE,
            )
            ws.set_tts_service(_tts_service)
            loaded.append("tts")

            # OCR
            print("[Mode] OCR 로드 중...")
            _ocr_service = OCRService()
            ws.set_ocr_service(_ocr_service)
            slides.set_ocr_service(_ocr_service)
            loaded.append("ocr")

        except Exception as e:
            print(f"[Mode] 실시간 모델 로드 실패: {e}")
            raise HTTPException(status_code=500, detail=f"모델 로드 실패: {e}")

        _current_mode = Mode.REALTIME

        return ModeResponse(
            mode=Mode.REALTIME.value,
            message=f"실시간 번역 모드로 전환 완료. 로드: {loaded}",
            models_loaded=loaded
        )
