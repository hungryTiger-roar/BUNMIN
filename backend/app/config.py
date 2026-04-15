import os
from pathlib import Path

# 기본 경로
BASE_DIR = Path(__file__).parent.parent
CACHE_DIR = BASE_DIR / "cache"
SLIDES_DIR = BASE_DIR / "slides"

# 디렉토리 생성
CACHE_DIR.mkdir(exist_ok=True)
SLIDES_DIR.mkdir(exist_ok=True)

# HuggingFace 설정
os.environ.setdefault("HF_HOME", str(CACHE_DIR / "huggingface"))

# 모델 설정
class ModelConfig:
    # ASR
    ASR_MODEL = "seastar105/whisper-small-komixv2"  # CPU용
    ASR_DEVICE = "cpu"

    # NMT
    NMT_MODEL = "Helsinki-NLP/opus-mt-ko-en"  # 가벼운 모델
    NMT_DEVICE = "cpu"

    # TTS
    TTS_MODEL_DIR = BASE_DIR / "app" / "models"

    # OCR - RapidOCR 사용


# 서버 설정
class ServerConfig:
    HOST = "0.0.0.0"
    PORT = 8000
    RELOAD = True


# GPU 사용 시 설정 변경
USE_GPU = os.environ.get("USE_GPU", "false").lower() == "true"

if USE_GPU:
    ModelConfig.ASR_MODEL = "CohereLabs/cohere-transcribe-03-2026"
    ModelConfig.ASR_DEVICE = "cuda:0"
    # NLLB: 다국어 번역 모델 (Seq2Seq 호환)
    ModelConfig.NMT_MODEL = "facebook/nllb-200-distilled-600M"
    ModelConfig.NMT_DEVICE = "cuda:0"
