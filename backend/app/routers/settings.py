"""
강의자 개인설정 API.

현재는 토큰(HF_TOKEN, OPENAI_API_KEY) 갱신 기능만 제공.
.env 파일에 직접 쓰고 os.environ도 갱신해 다음 모델 다운로드/슬라이드 업로드부터 적용된다.
이미 메모리에 로드된 모델은 앱 재시작이 필요할 수 있다.
"""

import os
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from dotenv import set_key

router = APIRouter(prefix="/api/settings", tags=["Settings"])


# ─── .env 경로 결정 (config.py와 동일한 규칙) ────────────────────────────────
_FROZEN = getattr(sys, "frozen", False)


def _writable_env_path() -> Path:
    """런타임에 갱신할 .env 파일 경로.
    - frozen: USER_DATA_DIR/.env (사용자 오버라이드 파일)
    - dev: <root>/.env
    """
    if _FROZEN:
        user_data_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Aunion AI"
        user_data_dir.mkdir(parents=True, exist_ok=True)
        return user_data_dir / ".env"
    # dev: backend/app/routers/settings.py → backend/app → backend → <root>
    project_root = Path(__file__).resolve().parents[3]
    return project_root / ".env"


def _mask(value: str | None) -> str:
    """토큰 표시용 마스킹. 양 끝 일부만 노출."""
    if not value:
        return ""
    v = value.strip()
    if len(v) <= 8:
        return "***"
    return f"{v[:4]}...{v[-4:]}"


# ─── 모델 ────────────────────────────────────────────────────────────────────
class TokenStatusResponse(BaseModel):
    hf_token_set: bool
    openai_api_key_set: bool
    hf_token_masked: str
    openai_api_key_masked: str


class UpdateTokensRequest(BaseModel):
    hf_token: str | None = None
    openai_api_key: str | None = None


class UpdateTokensResponse(BaseModel):
    updated: list[str]
    message: str


# ─── 엔드포인트 ──────────────────────────────────────────────────────────────
@router.get("/tokens", response_model=TokenStatusResponse)
async def get_tokens():
    """현재 환경변수에 설정된 토큰 상태(마스킹된 값)를 반환."""
    hf = os.environ.get("HF_TOKEN", "")
    oa = os.environ.get("OPENAI_API_KEY", "")
    return TokenStatusResponse(
        hf_token_set=bool(hf),
        openai_api_key_set=bool(oa),
        hf_token_masked=_mask(hf),
        openai_api_key_masked=_mask(oa),
    )


@router.post("/tokens", response_model=UpdateTokensResponse)
async def update_tokens(payload: UpdateTokensRequest):
    """토큰을 .env 파일에 저장하고 os.environ도 즉시 갱신."""
    hf = (payload.hf_token or "").strip() if payload.hf_token is not None else None
    oa = (payload.openai_api_key or "").strip() if payload.openai_api_key is not None else None

    if hf is None and oa is None:
        raise HTTPException(400, "변경할 토큰을 하나 이상 보내주세요.")

    env_path = _writable_env_path()
    # 파일이 없으면 빈 파일 생성 (set_key가 동작하려면 파일이 존재해야 함)
    if not env_path.exists():
        env_path.touch()

    updated: list[str] = []
    try:
        if hf is not None:
            set_key(str(env_path), "HF_TOKEN", hf, quote_mode="never")
            os.environ["HF_TOKEN"] = hf
            updated.append("HF_TOKEN")
        if oa is not None:
            set_key(str(env_path), "OPENAI_API_KEY", oa, quote_mode="never")
            os.environ["OPENAI_API_KEY"] = oa
            updated.append("OPENAI_API_KEY")
    except Exception as e:
        raise HTTPException(500, f".env 파일 저장 실패: {e}")

    return UpdateTokensResponse(
        updated=updated,
        message=(
            f"{', '.join(updated)} 저장 완료. "
            "이미 로드된 모델은 앱 재시작 후 적용됩니다."
        ),
    )
