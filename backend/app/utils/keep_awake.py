"""
절전모드 방지 유틸리티
Windows SetThreadExecutionState API를 사용하여 장시간 작업 중 절전모드 진입 방지
"""
import sys
from contextlib import contextmanager

if sys.platform == "win32":
    import ctypes

    # Windows API 상수
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002

    def _set_thread_execution_state(flags: int) -> int:
        """SetThreadExecutionState API 호출"""
        return ctypes.windll.kernel32.SetThreadExecutionState(flags)

    @contextmanager
    def keep_awake(prevent_display_sleep: bool = False):
        """
        컨텍스트 매니저: 블록 내에서 시스템 절전모드 방지

        Args:
            prevent_display_sleep: True면 디스플레이 절전도 방지 (기본 False)

        Usage:
            with keep_awake():
                # 장시간 작업 수행
                process_long_task()
        """
        flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        if prevent_display_sleep:
            flags |= ES_DISPLAY_REQUIRED

        try:
            _set_thread_execution_state(flags)
            print("[KeepAwake] 절전모드 방지 활성화")
            yield
        finally:
            _set_thread_execution_state(ES_CONTINUOUS)
            print("[KeepAwake] 절전모드 방지 해제")

else:
    # Linux/macOS: 절전모드 방지 미지원 (필요시 caffeinate/systemd-inhibit 사용)
    @contextmanager
    def keep_awake(prevent_display_sleep: bool = False):
        """Non-Windows: no-op"""
        yield
