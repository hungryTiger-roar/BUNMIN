"""
설치 마법사용 API — 사용자 데이터(업로드/캐시/자막) 누적용 디스크 여유 확인.

현재 흐름:
  VLM 포함 모든 AI 모델은 인스톨러에 동봉(electron-builder.json extraResources) →
  설치 직후 추가 다운로드 없이 사용 가능. `wait_user_action` 경로는 모델이 어떤 이유로
  누락된 경우(개발 빌드, 부분 설치 등)에만 트리거되는 안전망.

  Install.tsx 가 mount 시점에 /disk-check 를 호출해 부족하면 UI 에 경고 표시.
"""
import os
import shutil

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/install", tags=["install"])


# 동봉본(정상 설치) — 사용자 데이터(업로드/캐시/자막/로그) 누적용 여유만 필요.
REQUIRED_GB_BUNDLED = 5.0
# VLM 미동봉(개발 빌드 / 부분 설치) — HF 다운로드 ~16GB + symlink→copy 패치로 인한 사본 ~16GB.
REQUIRED_GB_DOWNLOAD = 30.0


def _required_gb() -> float:
    """현재 VLM 상태에 따라 적절한 디스크 요구치 결정.
    동봉 VLM 발견되면 사용자 데이터 분(5GB), 다운로드 필요하면 30GB.
    main 임포트 실패 시(테스트 등) 보수적으로 다운로드 기준."""
    try:
        from app.main import _is_cached, VLM_BASE_MODEL
        return REQUIRED_GB_BUNDLED if _is_cached(VLM_BASE_MODEL) else REQUIRED_GB_DOWNLOAD
    except Exception:
        return REQUIRED_GB_DOWNLOAD


def _cache_drive_path() -> str:
    """HF cache 가 들어갈 드라이브를 가리키는 경로. shutil.disk_usage 가 그 드라이브의
    free space 를 반환하도록 하기 위한 입력."""
    return os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")


@router.get("/disk-check")
async def disk_check():
    """디스크 여유 확인. VLM 동봉 여부에 따라 요구치 동적 결정.
    `%LOCALAPPDATA%` 가 있는 드라이브의 free space 를 GB 단위로 반환.
    """
    target = _cache_drive_path()
    try:
        usage = shutil.disk_usage(target)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"디스크 정보 조회 실패: {e}")

    required = _required_gb()
    free_gb = usage.free / (1024 ** 3)
    return {
        "ok": free_gb >= required,
        "free_gb": round(free_gb, 2),
        "required_gb": required,
        "drive": os.path.splitdrive(target)[0] or target,
        "shortfall_gb": round(max(0.0, required - free_gb), 2),
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

    # 안전장치 — 디스크 부족/측정 실패 모두 다운로드 시작 거부.
    # disk_check 와 동일한 fail-closed 정책. 측정 자체가 실패하는 상황은 디스크/파일시스템에
    # 진짜 문제가 있다는 신호이므로 사용자에게 명시적으로 알리고 차단.
    target = _cache_drive_path()
    try:
        usage = shutil.disk_usage(target)
        free_gb = usage.free / (1024 ** 3)
    except OSError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "disk_check_failed",
                "message": f"디스크 정보 조회 실패: {e}",
            },
        )
    required = _required_gb()
    if free_gb < required:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "insufficient_disk",
                "message": f"디스크 여유 부족: {free_gb:.1f}GB / 필요 {required:.0f}GB",
                "free_gb": round(free_gb, 2),
                "required_gb": required,
            },
        )

    _start_download_event.set()
    return {"ok": True, "already_started": False}
