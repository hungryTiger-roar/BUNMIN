"""
동적 모델 모드 전환 API

슬라이드 번역 모드 ↔ 실시간 번역 모드 전환
- /api/mode/slide: VLM 온디맨드 로드, 실시간 모델 언로드 (ASR/NMT/OCR)
- /api/mode/realtime: VLM 언로드, ASR/NMT-ASR 로드 (OCR은 슬라이드 전용이라 재로드 안 함)
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

# 최초 실시간 모드 로드 여부
_first_realtime_load = True


def get_current_mode() -> Mode:
    return _current_mode


def _unload_vlm():
    """VLM 모델 언로드 (GPU 메모리 해제)"""
    try:
        from app.services.slide_translation.image_pipeline import unload_vlm_model
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
    """실시간 모델들 언로드 (ASR/NMT-ASR/OCR) — ws 참조까지 해제해야 GC 가능"""
    from app.routers import ws, slides

    unloaded = []
    for name, clear_fn in [
        ("asr",     lambda: ws.set_asr_service(None)),
        ("nmt_asr", lambda: ws.set_nmt_service(None)),
        ("ocr",     lambda: (ws.set_ocr_service(None), slides.set_ocr_service(None))),
    ]:
        try:
            clear_fn()
            unloaded.append(name)
        except Exception as e:
            print(f"[Mode] {name} 언로드 실패: {e}")

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print(f"[Mode] 실시간 모델 언로드 완료: {unloaded}")
    return unloaded


@router.get("/current", response_model=ModeResponse)
async def get_mode():
    """현재 모드 확인"""
    from app.routers import ws as _ws
    models_loaded = []

    if _ws._asr_service is not None:
        models_loaded.append("asr")
    if _ws._nmt_service is not None:
        models_loaded.append("nmt_asr")
    if _ws._ocr_service is not None:
        models_loaded.append("ocr")

    try:
        from app.services.slide_translation.image_pipeline import is_vlm_loaded
        if is_vlm_loaded():
            models_loaded.append("vlm")
    except Exception:
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
    """실시간 번역 모드로 전환 (VLM 언로드, ASR/NMT-ASR 로드)"""
    global _current_mode, _first_realtime_load

    async with _mode_lock:
        if _current_mode == Mode.REALTIME:
            return ModeResponse(
                mode=Mode.REALTIME.value,
                message="이미 실시간 번역 모드입니다",
                models_loaded=["asr", "nmt_asr"]
            )

        # VLM 언로드
        await asyncio.to_thread(_unload_vlm)

        # 실시간 모델 로드
        loaded = []

        if _first_realtime_load:
            print()
            print("============================================================")
            print("[실시간 모드] AI 모델 최초 로드 중... (서버 재시작 전까지 1회)")
            print("============================================================")

        try:
            from app.config import ModelConfig
            from app.services.asr_service import ASRService
            from app.services.nmt_service import NMTService
            from app.routers import ws

            # ASR
            print(f"\n[1/2] ASR 음성인식 모델 로드 중...")
            if _first_realtime_load:
                print(f"  모델: {ModelConfig.ASR_MODEL}")
                print(f"  디바이스: {ModelConfig.ASR_DEVICE} / {ModelConfig.ASR_DTYPE}")
            asr_service = await asyncio.to_thread(
                lambda: ASRService(
                    model_name=ModelConfig.ASR_MODEL,
                    device=ModelConfig.ASR_DEVICE,
                    dtype=ModelConfig.ASR_DTYPE,
                )
            )
            ws.set_asr_service(asr_service)
            loaded.append("asr")
            print(f"  [1/2] ASR 로드 완료 ✓")

            # NMT-ASR
            print(f"\n[2/2] NMT 번역 모델 로드 중...")
            if _first_realtime_load:
                print(f"  모델: {ModelConfig.NMT_ASR_MODEL}")
                print(f"  디바이스: {ModelConfig.NMT_ASR_DEVICE} / int8")
            nmt_asr_service = await asyncio.to_thread(
                lambda: NMTService(
                    model_name=ModelConfig.NMT_ASR_MODEL,
                    device=ModelConfig.NMT_ASR_DEVICE,
                    dtype=ModelConfig.NMT_ASR_DTYPE,
                )
            )
            ws.set_nmt_service(nmt_asr_service)
            loaded.append("nmt_asr")
            print(f"  [2/2] NMT 로드 완료 ✓")

            # OCR은 실시간 모드에서 사용하지 않음 (슬라이드 번역 전용)

        except Exception as e:
            print(f"[Mode] 실시간 모델 로드 실패: {e}")
            raise HTTPException(status_code=500, detail=f"모델 로드 실패: {e}")

        if _first_realtime_load:
            print()
            print("============================================================")
            print("[실시간 모드] 모든 AI 모델 로드 완료! 실시간 번역 준비됨")
            print("============================================================")
            _first_realtime_load = False
        else:
            print("[Mode] 실시간 모드 전환 완료")

        _current_mode = Mode.REALTIME
        return ModeResponse(
            mode=Mode.REALTIME.value,
            message=f"실시간 번역 모드로 전환 완료. 로드: {loaded}",
            models_loaded=loaded
        )
