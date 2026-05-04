"""
설치 마법사용 API — VLM 첫 다운로드를 사용자 액션으로 트리거.

흐름:
  1. 백엔드 시작 시 VLM 미캐시 + 슬라이드 전용 모드면 status="wait_user_action"으로 대기
  2. 프론트가 마법사 표시 → 사용자가 "다운로드 시작" 클릭
  3. POST /api/install/start-download → _start_download_event 발화 → 백엔드 다운로드 진행
"""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/install", tags=["install"])


@router.post("/start-download")
async def start_download():
    """사용자가 마법사에서 '다운로드 시작' 클릭 시 호출.
    백엔드 메인 스레드에서 대기 중이던 다운로드 흐름을 깨움.
    """
    from app.main import _start_download_event, _model_status

    if _model_status["status"] != "wait_user_action":
        # 이미 다운로드 진행/완료 등 — 멱등 처리
        return {
            "ok": True,
            "already_started": True,
            "current_status": _model_status["status"],
        }

    _start_download_event.set()
    return {"ok": True, "already_started": False}
