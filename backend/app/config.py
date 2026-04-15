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
    # 개발 환경: 프로젝트 루트 기준
    APP_DATA_DIR = Path(__file__).parent.parent
    load_dotenv(APP_DATA_DIR / ".env")

# 기본 경로
CACHE_DIR = APP_DATA_DIR / "cache"
SLIDES_DIR = APP_DATA_DIR / "slides"

# 디렉토리 생성
CACHE_DIR.mkdir(parents=True, exist_ok=True)
SLIDES_DIR.mkdir(parents=True, exist_ok=True)

# HuggingFace 설정
os.environ.setdefault("HF_HOME", str(CACHE_DIR / "huggingface"))

# 모델 설정
class ModelConfig:
    # ASR - GPU 실행 (faster-whisper)
    ASR_MODEL = "large-v3-turbo"
    ASR_DEVICE = "cpu"
    ASR_DTYPE = "float32"  # GPU: float16, CPU: float32

    # NMT - CPU 실행
    NMT_MODEL = "Helsinki-NLP/opus-mt-ko-en"
    NMT_DEVICE = "cpu"
    NMT_DTYPE = "float32"

    # TTS - CPU 실행 (Supertonic-2 ONNX)
    TTS_MODEL = "onnx-community/Supertonic-TTS-2-ONNX"
    TTS_DEVICE = "cpu"

    # OCR - CPU 실행
    OCR_DEVICE = "cpu"


# 서버 설정
class ServerConfig:
    HOST = "0.0.0.0"
    PORT = 8000
    RELOAD = True


# GPU 사용 시 설정 변경
USE_GPU = os.environ.get("USE_GPU", "false").lower() == "true"

if USE_GPU:
    ModelConfig.ASR_DEVICE = "cuda"
    ModelConfig.ASR_DTYPE = "float16"
