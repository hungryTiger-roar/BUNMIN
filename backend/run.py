"""
백엔드 진입점 (PyInstaller용)
"""
import sys
import os
import traceback
from pathlib import Path
from datetime import datetime

# ── HuggingFace Hub symlink → copy 대체 (Windows WinError 448 회피) ───
# HF Hub 가 cache/snapshots/ 에 symlink 을 만들면, 새 Windows 보안 정책이 그 reparse
# point 를 "untrusted mount point" 로 판정해 per-user (asInvoker) 프로세스에서
# traverse 거부 (WinError 448) → 모델 로딩 실패.
#
# `os.symlink` 자체를 `shutil.copyfile` 로 대체. HF Hub 은 symlink 성공으로 인식해
# 정상 흐름을 유지하고, 실제 디스크엔 reparse point 대신 일반 파일 복사본이 생김.
# (이전엔 OSError 를 던져 HF Hub 의 fallback 을 유도했으나, xet/`new_blob=False` 등
#  fallback 이 없는 경로에서 OSError 가 그대로 전파돼 다운로드 실패.)
if sys.platform == "win32":
    import shutil as _shutil

    def _symlink_as_copy(src, dst, target_is_directory=False, *, dir_fd=None):
        src_str = os.fspath(src)
        dst_str = os.fspath(dst)
        # symlink 의 src 는 보통 dst 디렉토리 기준 상대경로 — resolve
        if not os.path.isabs(src_str):
            resolved_src = os.path.normpath(os.path.join(os.path.dirname(dst_str), src_str))
        else:
            resolved_src = src_str
        # HF Hub 는 파일만 symlink — 디렉토리 케이스는 안 만남. 안전하게 스킵.
        if target_is_directory:
            return
        _shutil.copyfile(resolved_src, dst_str)

    os.symlink = _symlink_as_copy

# ── 상위 디렉토리를 Python 경로에 추가 (translate_slide_v3 import용) ─────
_backend_dir = Path(__file__).parent
_project_root = _backend_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ── 로그 파일 경로 결정 ──────────────────────────────────────────────
_frozen = getattr(sys, 'frozen', False)
if _frozen:
    _log_dir = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Aunion AI'
else:
    _log_dir = Path(__file__).parent

_log_dir.mkdir(parents=True, exist_ok=True)
LOG_FILE = _log_dir / 'error_log.txt'

# stdout/stderr를 UTF-8로 강제 (PyInstaller 빌드에서 CP949 깨짐 방지)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


_log_initialized = False

def write_log(msg: str):
    """로그 파일에 기록 (첫 호출 시 덮어쓰기, 이후 append)"""
    global _log_initialized
    mode = 'w' if not _log_initialized else 'a'
    _log_initialized = True
    try:
        with open(LOG_FILE, mode, encoding='utf-8') as f:
            f.write(msg + '\n')
            f.flush()
    except Exception:
        pass


# ── 시작 헤더 기록 ───────────────────────────────────────────────────
write_log(f"\n{'='*60}")
write_log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Aunion AI Backend 시작")
write_log(f"Python: {sys.version}")
write_log(f"Frozen: {_frozen}")
write_log(f"Log file: {LOG_FILE}")
write_log(f"{'='*60}")


# ── stderr를 로그 파일과 원본 출력 양쪽에 기록 ───────────────────────
class _TeeStream:
    """write()를 원본 스트림 + 로그 파일 양쪽으로 전달"""
    def __init__(self, original):
        self._orig = original

    def write(self, msg):
        try:
            self._orig.write(msg)
        except Exception:
            pass
        if msg.strip():
            write_log(f"[STDERR] {msg.rstrip()}")

    def flush(self):
        try:
            self._orig.flush()
        except Exception:
            pass

    def fileno(self):
        return self._orig.fileno()

    def isatty(self):
        return False


sys.stderr = _TeeStream(sys.stderr)


# ── 처리되지 않은 예외도 파일에 기록 ────────────────────────────────
def _exception_hook(exc_type, exc_value, exc_tb):
    tb_str = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    write_log(f"[UNCAUGHT EXCEPTION]\n{tb_str}")
    print(f"[FATAL] {exc_value}", flush=True)


sys.excepthook = _exception_hook


# ── 실제 앱 기동 ─────────────────────────────────────────────────────
try:
    write_log("[INFO] uvicorn / app 임포트 시작...")

    # CUDA 진단
    try:
        import torch
        cuda_available = torch.cuda.is_available()
        write_log(f"[CUDA] torch.cuda.is_available(): {cuda_available}")
        write_log(f"[CUDA] PyTorch version: {torch.__version__}")
        if cuda_available:
            write_log(f"[CUDA] CUDA version: {torch.version.cuda}")
            write_log(f"[CUDA] GPU count: {torch.cuda.device_count()}")
            write_log(f"[CUDA] GPU name: {torch.cuda.get_device_name(0)}")
        else:
            write_log(f"[CUDA] WARNING: CUDA not available! VLM translation will fail.")
            print("[WARNING] CUDA not available! VLM translation will fail.", flush=True)
    except Exception as e:
        write_log(f"[CUDA] Error checking CUDA: {e}")

    import uvicorn
    from app.main import app
    write_log("[INFO] 임포트 성공, uvicorn 기동 중...")

    if __name__ == '__main__':
        uvicorn.run(app, host='0.0.0.0', port=8000)

except Exception as e:
    tb_str = traceback.format_exc()
    write_log(f"[FATAL] 시작 실패: {e}\n{tb_str}")
    print(f"[FATAL] 시작 실패: {e}", flush=True)
    sys.exit(1)
