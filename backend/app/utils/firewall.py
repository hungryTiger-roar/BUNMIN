"""
Windows 방화벽 인바운드 룰 자동 등록.
수강자가 같은 LAN에서 강의자 PC의 FastAPI에 접근하려면 방화벽 허용이 필요하다.
"""
import subprocess
import sys


RULE_NAME = "Aunion AI Backend"


def _run_netsh(args: list[str]) -> tuple[int, str]:
    """netsh 호출 — CREATE_NO_WINDOW로 콘솔 창 깜빡임 방지."""
    try:
        proc = subprocess.run(
            ["netsh", *args],
            capture_output=True,
            text=True,
            encoding="cp949",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return -1, "netsh not found"


def _rule_exists(rule_name: str) -> bool:
    code, out = _run_netsh([
        "advfirewall", "firewall", "show", "rule", f"name={rule_name}",
    ])
    # 룰이 없으면 netsh가 비영 리턴코드 + "No rules match" 메시지를 준다
    return code == 0 and ("LocalPort" in out or "로컬 포트" in out)


def ensure_firewall_rule(port: int, rule_name: str = RULE_NAME) -> bool:
    """TCP 인바운드 허용 룰이 없으면 추가.
    관리자 권한 없으면 실패(코드!=0) — 경고만 출력하고 False 반환."""
    if not sys.platform.startswith("win"):
        return False

    if _rule_exists(rule_name):
        print(f"[방화벽] 기존 룰 존재: '{rule_name}' (port {port})", flush=True)
        return True

    code, out = _run_netsh([
        "advfirewall", "firewall", "add", "rule",
        f"name={rule_name}",
        "dir=in",
        "action=allow",
        "protocol=TCP",
        f"localport={port}",
        "profile=private,domain",
    ])

    if code == 0:
        print(f"[방화벽] 룰 추가됨: '{rule_name}' (TCP {port}, private+domain)", flush=True)
        return True

    print(
        f"[방화벽] 룰 추가 실패 (관리자 권한 필요할 수 있음). "
        f"수동 추가: 제어판 → Windows Defender 방화벽 → 고급 설정 → 인바운드 규칙 → "
        f"새 규칙 → TCP {port} 허용.\n  netsh 출력: {out.strip()[:200]}",
        flush=True,
    )
    return False
