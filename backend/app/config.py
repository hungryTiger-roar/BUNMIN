import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# PyInstaller 번들 여부 감지
_FROZEN = getattr(sys, 'frozen', False)

# ─── 경로 정의 ───────────────────────────────────────────────────────────────
# USER_DATA_DIR: 사용자별 영구 데이터 (frozen에선 다운로드 모델/캐시 저장 위치).
# INSTALL_DIR: 설치된 백엔드 파일 위치.
#   - frozen: <install>/resources/backend/ (extraResources로 동봉된 모델은 INSTALL_DIR/models/<name>/)
#   - dev: <root>/backend/
# PROJECT_ROOT: dev 모드 저장소 루트. frozen 모드에선 INSTALL_DIR과 동일.
# ─────────────────────────────────────────────────────────────────────────────
USER_DATA_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Aunion AI'

if _FROZEN:
    INSTALL_DIR = Path(sys.executable).parent
    PROJECT_ROOT = INSTALL_DIR
    # .env: 동봉본 → 사용자 오버라이드 순으로 로드
    load_dotenv(INSTALL_DIR / ".env")
    load_dotenv(USER_DATA_DIR / ".env", override=True)
else:
    # 개발: backend/app/config.py → backend → root
    INSTALL_DIR = Path(__file__).parent.parent  # backend/
    PROJECT_ROOT = INSTALL_DIR.parent           # <root>/
    load_dotenv(PROJECT_ROOT / ".env")

# 기존 코드 호환용 별칭
APP_DATA_DIR = USER_DATA_DIR if _FROZEN else INSTALL_DIR

# 캐시 위치:
#   - frozen: 사용자 데이터 디렉토리 (사용자별 격리)
#   - dev: 프로젝트 내 backend/cache (download_models.py와 동일 위치 — 기존 캐시 재사용)
CACHE_DIR = (USER_DATA_DIR / "cache") if _FROZEN else (INSTALL_DIR / "cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# HuggingFace 캐시
os.environ.setdefault("HF_HOME", str(CACHE_DIR / "huggingface"))


# ─── 모델 디렉토리 해석 ──────────────────────────────────────────────────────
# 흔한 가중치 파일 확장자 — 빈 폴더(설치 시 Inno Setup의 Excludes로 파일은 빠지고
# 디렉토리만 남는 경우)를 valid 모델로 오인하지 않기 위한 검사 키.
_WEIGHT_EXTS = (".safetensors", ".bin", ".onnx", ".pt", ".pth")


def _has_model_weights(directory: Path) -> bool:
    """디렉토리에 모델 가중치 파일이 하나라도 있으면 True."""
    if not directory.is_dir():
        return False
    for ext in _WEIGHT_EXTS:
        try:
            if next(directory.rglob(f"*{ext}"), None) is not None:
                return True
        except (OSError, PermissionError):
            continue
    return False


def resolve_model_dir(name: str) -> Path | None:
    """주어진 이름의 모델 디렉토리를 다음 순서로 찾는다 (가중치 파일이 있어야 valid).
      1) USER_DATA_DIR/models/<name>/  — 사용자가 다운로드한 모델 (예: VLM)
      2) INSTALL_DIR/models/<name>/    — 설치 시 동봉된 모델 (frozen) / 저장소 (dev)
      3) PROJECT_ROOT/models/<name>/   — dev 전용 추가 폴백
    가중치가 있는 첫 디렉토리를 반환, 없으면 None.
    빈 디렉토리(설치 시 Inno Setup Excludes 부산물 등)는 무시.
    """
    candidates = [
        USER_DATA_DIR / "models" / name,
        INSTALL_DIR / "models" / name,
    ]
    if not _FROZEN:
        candidates.append(PROJECT_ROOT / "models" / name)
    for c in candidates:
        if _has_model_weights(c):
            return c
    return None

# GPU 지원 여부 (런타임 체크)
def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False

_CUDA_AVAILABLE = _cuda_available()

_CPU_ONLY_MODELS: set[str] = set()  # GPU 미지원 모델 (현재 없음)
_GPU_ONLY_MODELS: set[str] = set()  # CPU 미지원 모델 (현재 없음, 확장 대비)


def _resolve_device(env_key: str, model_key: str, default: str = "cpu") -> str:
    requested = os.environ.get(env_key, default).lower()
    label = model_key.upper()

    if requested == "cuda":
        if model_key in _CPU_ONLY_MODELS:
            print(f"[Config] {label}: GPU 미지원 모델 → CPU로 실행합니다.")
            return "cpu"
        if not _CUDA_AVAILABLE:
            if model_key in _GPU_ONLY_MODELS:
                raise RuntimeError(
                    f"[Config] {label}: GPU 전용 모델인데 CUDA를 사용할 수 없습니다. "
                    "NVIDIA 드라이버 및 CUDA 설치를 확인하세요."
                )
            print(f"[Config] {label}: CUDA를 사용할 수 없습니다 → CPU로 실행합니다.")
            return "cpu"
        return "cuda"

    if requested == "cpu":
        if model_key in _GPU_ONLY_MODELS:
            if _CUDA_AVAILABLE:
                print(f"[Config] {label}: CPU 미지원 모델 → GPU로 실행합니다.")
                return "cuda"
            raise RuntimeError(
                f"[Config] {label}: CPU 미지원 모델인데 CUDA도 사용할 수 없습니다. "
                "NVIDIA 드라이버 및 CUDA 설치를 확인하세요."
            )
        return "cpu"

    return "cpu"


def _dtype(device: str) -> str:
    return "float16" if device == "cuda" else "float32"


# 모델 값 해석: 절대 경로/repo_id는 그대로, 상대 경로(`models/<name>` 또는
# 단순 이름)는 resolve_model_dir로 다단계 폴백. dev/frozen 양쪽에서 일관 동작.
def _resolve_model(value: str) -> str:
    p = Path(value)
    if p.is_absolute():
        return value
    # PROJECT_ROOT 기준으로 풀어보고 디렉토리면 절대 경로 반환 (기존 동작 유지)
    candidate = PROJECT_ROOT / value
    if candidate.is_dir():
        return str(candidate)
    # 단순 이름이거나 다른 위치 폴백 검사
    name = p.name if "/" in value or "\\" in value else value
    found = resolve_model_dir(name)
    if found is not None:
        return str(found)
    # 못 찾으면 원본(주로 HF repo_id) 반환
    return value


class ModelConfig:
    ASR_MODEL  = _resolve_model(os.environ.get("ASR_MODEL", "models/whisper-large-v3-turbo-ct2-int8"))
    ASR_DEVICE = _resolve_device("ASR_DEVICE", "asr")
    ASR_DTYPE  = _dtype(ASR_DEVICE)  # faster-whisper는 compute_type을 ASRService 내부에서 결정

    NMT_ASR_MODEL  = os.environ.get("NMT_ASR_MODEL", "Helsinki-NLP/opus-mt-ko-en")
    NMT_ASR_DEVICE = _resolve_device("NMT_ASR_DEVICE", "nmt_asr")
    NMT_ASR_DTYPE  = os.environ.get("NMT_ASR_DTYPE", _dtype(NMT_ASR_DEVICE))

    OCR_MODEL  = os.environ.get("OCR_MODEL",  "surya")
    OCR_DEVICE = _resolve_device("OCR_DEVICE", "ocr")

