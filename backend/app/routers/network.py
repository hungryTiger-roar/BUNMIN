"""
네트워크 정보 라우터 — 강의자 UI가 수강자 초대 링크를 만들기 위한 정보.
"""
from fastapi import APIRouter

from app.utils.network import SERVER_PORT, get_lan_ip, get_join_url

router = APIRouter(prefix="/network", tags=["Network"])


@router.get("/info")
async def network_info():
    """강의자 PC의 LAN IP와 수강자 초대 URL을 반환."""
    lan_ip = get_lan_ip()
    return {
        "lan_ip": lan_ip,
        "port": SERVER_PORT,
        "join_url": get_join_url(SERVER_PORT),
    }
