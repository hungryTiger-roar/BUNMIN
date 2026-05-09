"""
설치 마법사용 API — VLM 첫 다운로드를 사용자 액션으로 트리거.

흐름:
  1. 백엔드 시작 시 VLM 미캐시 + 슬라이드 전용 모드면 status="wait_user_action"으로 대기
  2. 프론트가 마법사 표시 → /api/install/disk-check 로 디스크 여유 확인
  3. 사용자가 "다운로드 시작" 클릭 → POST /api/install/start-download
  4. _start_download_event 발화 → 백엔드 다운로드 진행
"""
import os
import shutil

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/install", tags=["install"])


# VLM HF 다운로드(~14GB) + symlink → copy 패치로 인한 snapshots/ 사본(~14GB)
# + 안전 마진(~2GB) = ~30GB 권장.
REQUIRED_GB = 30.0


def _cache_drive_path() -> str:
    """HF cache 가 들어갈 드라이브를 가리키는 경로. shutil.disk_usage 가 그 드라이브의
    free space 를 반환하도록 하기 위한 입력."""
    return os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")


@router.get("/disk-check")
async def disk_check():
    """VLM 다운로드용 디스크 여유 확인.
    `%LOCALAPPDATA%` 가 있는 드라이브의 free space 를 GB 단위로 반환.
    """
    target = _cache_drive_path()
    try:
        usage = shutil.disk_usage(target)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"디스크 정보 조회 실패: {e}")

    free_gb = usage.free / (1024 ** 3)
    return {
        "ok": free_gb >= REQUIRED_GB,
        "free_gb": round(free_gb, 2),
        "required_gb": REQUIRED_GB,
        "drive": os.path.splitdrive(target)[0] or target,
        "shortfall_gb": round(max(0.0, REQUIRED_GB - free_gb), 2),
    }


@router.post("/start-download")
async def start_download():
    """사용자가 마법사에서 '다운로드 시작' 클릭 시 호출.
    백엔드 메인 스레드에서 대기 중이던 다운로드 흐름을 깨움.

    프론트가 disk-check 를 우회해서 호출하더라도 여기서 한 번 더 검사해 안전 차단.
    """
    from app.main import _start_download_event, _model_status

    if _model_status["status"] != "wait_user_action":
        # 이미 다운로드 진행/완료 등 — 멱등 처리
        return {
            "ok": True,
            "already_started": True,
            "current_status": _model_status["status"],
        }

    # 안전장치 — 디스크 부족 시 다운로드 시작 거부
    target = _cache_drive_path()
    try:
        usage = shutil.disk_usage(target)
        free_gb = usage.free / (1024 ** 3)
    except OSError:
        free_gb = float("inf")  # 측정 실패 시 통과시킴 (보수적)
    if free_gb < REQUIRED_GB:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "insufficient_disk",
                "message": f"디스크 여유 부족: {free_gb:.1f}GB / 필요 {REQUIRED_GB:.0f}GB",
                "free_gb": round(free_gb, 2),
                "required_gb": REQUIRED_GB,
            },
        )

    _start_download_event.set()
    return {"ok": True, "already_started": False}
