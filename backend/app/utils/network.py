"""
네트워크 유틸 — LAN IP 감지, 서버 바인딩 정보
"""
import socket


SERVER_PORT = 8000


def get_lan_ip() -> str:
    """같은 LAN에서 접근 가능한 IPv4 주소를 반환.
    실제로 외부에 패킷을 보내진 않고 OS의 라우팅 테이블을 이용해
    외부용 인터페이스 IP를 얻는 표준 기법."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def get_join_url(port: int = SERVER_PORT, path: str = "/join") -> str:
    return f"http://{get_lan_ip()}:{port}{path}"
