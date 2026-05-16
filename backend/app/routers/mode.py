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


async def _do_enter_slide_mode() -> list[str]:
    """슬라이드 모드 진입 (실시간 모델 언로드). 락은 호출자가 잡음."""
    global _current_mode
    if _current_mode == Mode.SLIDE:
        return []
    unloaded = await asyncio.to_thread(_unload_realtime_models)
    _current_mode = Mode.SLIDE
    return unloaded


async def _do_enter_realtime_mode() -> list[str]:
    """실시간 모드 진입 (VLM 언로드 + ASR/NMT 적재). 락은 호출자가 잡음.
    실패 시 RuntimeError raise (HTTPException 아님 — 내부/엔드포인트 양쪽 호출 대응).
    VLM 언로드는 mode 무관하게 항상 시도 — 강의 중 슬라이드 처리(enter_slide_mode skip)
    의 finally 에서 호출돼도 VLM 만 회수되고 ASR/NMT 적재는 skip 되는 정상 흐름 보장."""
    global _current_mode, _first_realtime_load

    # VLM 항상 언로드 (race / skip 케이스에서 VLM 누적 방지)
    await asyncio.to_thread(_unload_vlm)

    # ASR/NMT 가 이미 적재돼 있으면 재적재 skip — 서버 부팅 직후 main.py 가 적재한 상태에서
    # 라이브러리 자료 로드 시 switchToRealtimeMode 가 불려도 ~10초 재적재 발생 방지.
    # 메모리 정책 "강의 딜레이 최소화 최우선" 부합.
    from app.routers import ws as _ws
    if _ws._asr_service is not None and _ws._nmt_service is not None:
        _current_mode = Mode.REALTIME
        return ["asr (cached)", "nmt_asr (cached)"]

    if _current_mode == Mode.REALTIME:
        return []

    loaded: list[str] = []
    if _first_realtime_load:
        print()
        print("============================================================")
        print("[실시간 모드] AI 모델 최초 로드 중... (서버 재시작 전까지 1회)")
        print("============================================================")

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

    if _first_realtime_load:
        print()
        print("============================================================")
        print("[실시간 모드] 모든 AI 모델 로드 완료! 실시간 번역 준비됨")
        print("============================================================")
        _first_realtime_load = False
    else:
        print("[Mode] 실시간 모드 전환 완료")

    _current_mode = Mode.REALTIME
    return loaded


async def _broadcast_mode_change():
    """현재 모드 + 적재 모델 상태를 강의자에게 push (옵션 D).
    frontend 가 modelsReady 기준으로 강의 시작/슬라이드 업로드 버튼을 선제 활성/비활성 가드.
    실패해도 swallow — broadcast 실패가 mode 전환 흐름을 깨지 않게."""
    try:
        from app.routers import ws
        models_loaded = []
        if ws._asr_service is not None:
            models_loaded.append("asr")
        if ws._nmt_service is not None:
            models_loaded.append("nmt_asr")
        try:
            from app.services.slide_translation.image_pipeline import is_vlm_loaded
            if is_vlm_loaded():
                models_loaded.append("vlm")
        except Exception:
            pass
        msg = {
            "type": "mode_change",
            "mode": _current_mode.value,
            "models_loaded": models_loaded,
            # frontend 가 강의 시작 가능 여부 빠른 판단용
            "realtime_ready": ("asr" in models_loaded and "nmt_asr" in models_loaded),
        }
        if ws.manager.lecturer is not None:
            await ws.manager.lecturer.send_json(msg)
    except Exception as e:
        print(f"[Mode] broadcast 실패: {e}")


async def enter_slide_mode_safe() -> list[str]:
    """슬라이드 처리 진입 — 내부 호출용 (락 + 에러 안전).
    slides.py 의 process_slide / process_slide_batch 에서 호출.
    옵션 C 안전망: 강의 진행 중이면 ASR/NMT 언로드 skip (강의 끊김 방지).
    slides.py upload endpoint 가 이미 강의 중 업로드를 거부하므로 여기 도달은 race 케이스만."""
    async with _mode_lock:
        from app.routers.ws import manager as _ws_manager
        if _ws_manager.is_lecture_started:
            print("[Mode] 강의 진행 중 — slide 모드 전환 skip (race 안전망)")
            return []
        unloaded = await _do_enter_slide_mode()
    # 옵션 D: lock 밖에서 broadcast (lock hold 최소화)
    await _broadcast_mode_change()
    return unloaded


async def enter_realtime_mode_safe() -> list[str]:
    """슬라이드 처리 종료 — 내부 호출용. 실패해도 raise 안 함 (background task 흐름 보호).
    실패 시 ASR/NMT 미적재 상태로 남고, 강의 시작 시 ws 의 None 체크 또는 재시도가 필요."""
    async with _mode_lock:
        try:
            loaded = await _do_enter_realtime_mode()
        except Exception as e:
            print(f"[Mode] 실시간 재적재 실패 (background): {e}")
            loaded = []
    # 옵션 D: 성공/실패 모두 broadcast (frontend 가 실제 상태 인지)
    await _broadcast_mode_change()
    return loaded


@router.post("/slide", response_model=ModeResponse)
async def switch_to_slide_mode():
    """슬라이드 번역 모드로 전환 (실시간 모델 언로드, VLM 온디맨드)"""
    async with _mode_lock:
        if _current_mode == Mode.SLIDE:
            return ModeResponse(
                mode=Mode.SLIDE.value,
                message="이미 슬라이드 번역 모드입니다",
                models_loaded=["vlm (on-demand)"]
            )
        unloaded = await _do_enter_slide_mode()
        return ModeResponse(
            mode=Mode.SLIDE.value,
            message=f"슬라이드 번역 모드로 전환 완료. 언로드: {unloaded}",
            models_loaded=["vlm (on-demand)"]
        )


@router.post("/realtime", response_model=ModeResponse)
async def switch_to_realtime_mode():
    """실시간 번역 모드로 전환 (VLM 언로드, ASR/NMT-ASR 로드)"""
    async with _mode_lock:
        if _current_mode == Mode.REALTIME:
            return ModeResponse(
                mode=Mode.REALTIME.value,
                message="이미 실시간 번역 모드입니다",
                models_loaded=["asr", "nmt_asr"]
            )
        try:
            loaded = await _do_enter_realtime_mode()
        except Exception as e:
            print(f"[Mode] 실시간 모델 로드 실패: {e}")
            raise HTTPException(status_code=500, detail=f"모델 로드 실패: {e}")
        return ModeResponse(
            mode=Mode.REALTIME.value,
            message=f"실시간 번역 모드로 전환 완료. 로드: {loaded}",
            models_loaded=loaded
        )
