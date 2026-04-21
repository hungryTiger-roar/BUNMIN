import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# PyInstaller 번들 여부 감지
_FROZEN = getattr(sys, 'frozen', False)

if _FROZEN:
    # 배포판: AppData\Local\Aunion AI\ 에 영구 저장
    APP_DATA_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Aunion AI'
    # .env는 exe 옆에 있을 수도 있음
    load_dotenv(Path(sys.executable).parent / ".env")
else:
    # 개발 환경: 프로젝트 루트(backend/app → backend → root)의 .env 로드
    APP_DATA_DIR = Path(__file__).parent.parent
    _PROJECT_ROOT = Path(__file__).parent.parent.parent
    load_dotenv(_PROJECT_ROOT / ".env")

# 기본 경로
CACHE_DIR = APP_DATA_DIR / "cache"
SLIDES_DIR = APP_DATA_DIR / "slides"

# 디렉토리 생성
CACHE_DIR.mkdir(parents=True, exist_ok=True)
SLIDES_DIR.mkdir(parents=True, exist_ok=True)

# HuggingFace 설정
os.environ.setdefault("HF_HOME", str(CACHE_DIR / "huggingface"))

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


class ModelConfig:
    ASR_MODEL  = os.environ.get("ASR_MODEL",  "ghost613/faster-whisper-large-v3-turbo-korean")
    ASR_DEVICE = _resolve_device("ASR_DEVICE", "asr")
    ASR_DTYPE  = _dtype(ASR_DEVICE)

    NMT_MODEL  = os.environ.get("NMT_MODEL",  "Helsinki-NLP/opus-mt-ko-en")
    NMT_DEVICE = _resolve_device("NMT_DEVICE", "nmt")
    NMT_DTYPE  = _dtype(NMT_DEVICE)

    TTS_MODEL  = os.environ.get("TTS_MODEL",  "facebook/mms-tts-eng")
    TTS_DEVICE = _resolve_device("TTS_DEVICE", "tts")

    OCR_MODEL  = os.environ.get("OCR_MODEL",  "rapidocr")
    OCR_DEVICE = _resolve_device("OCR_DEVICE", "ocr")

