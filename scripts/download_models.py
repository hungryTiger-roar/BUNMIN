"""
AI 모델 다운로드 스크립트
HuggingFace Hub에서 필요한 모델들을 미리 다운로드합니다.

사용법:
    python scripts/download_models.py

필요 조건:
    pip install huggingface_hub requests
"""

import os
from pathlib import Path
from huggingface_hub import snapshot_download
import requests

# ─── HF 캐시 경로를 백엔드와 동일하게 설정 ────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent
_HF_HOME = _PROJECT_ROOT / "backend" / "cache" / "huggingface"
_HF_HOME.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(_HF_HOME))

# 모델 저장 경로
MODELS_DIR = _PROJECT_ROOT / "models"
TTS_MODEL_DIR = _PROJECT_ROOT / "backend" / "app" / "services" / "models"

# ============================================
# 다운로드할 모델 목록
# ============================================

# VLM Base 모델 (HuggingFace 캐시에 저장)
VLM_BASE = {
    "repo_id": "Qwen/Qwen3-VL-8B-Instruct",
    "description": "VLM Base 모델",
    "size": "~17GB",
}

# VLM LoRA 어댑터 (로컬 디렉토리에 저장)
VLM_LORA = {
    "repo_id": "sanghoon1234/qwen3-vl-8b-lora-ko2en",
    "local_dir": MODELS_DIR / "qwen3" / "qwen3-vl-8b-lora-r64-e3-final",
    "description": "VLM 번역 LoRA",
    "size": "~665MB",
}

# ASR 모델 (음성 인식)
ASR_MODEL = {
    "repo_id": "ghost613/faster-whisper-large-v3-turbo-korean",
    "description": "ASR 음성인식 모델",
    "size": "~3GB",
}

# NMT 모델 (실시간 번역) — CTranslate2 변환 대상
NMT_MODEL = {
    "repo_id": "Helsinki-NLP/opus-mt-ko-en",
    "local_dir": MODELS_DIR / "opus-mt-ct2",
    "description": "NMT 실시간 번역 모델 (CTranslate2 int8)",
    "size": "~150MB",
}

# TTS 모델 (음성 합성) - Piper
TTS_MODEL = {
    "base_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium",
    "files": ["en_US-lessac-medium.onnx", "en_US-lessac-medium.onnx.json"],
    "local_dir": TTS_MODEL_DIR,
    "description": "TTS 음성합성 모델 (Piper)",
    "size": "~60MB",
}

# RapidOCR 한국어 모델 — ocr_service.py가 hf_hub_download로 사용하는 실제 모델
RAPIDOCR_KOREAN = {
    "repo_id": "cycloneboy/korean_PP-OCRv4_rec_infer",
    "description": "RapidOCR 한국어 모델 (PP-OCRv4)",
    "size": "~20MB",
}

# Surya OCR 모델 (Transformer 기반, 고정확도)
SURYA_OCR = {
    "description": "Surya OCR (Transformer 기반)",
    "size": "~500MB",
}


def download_to_cache(model: dict, step: str) -> bool:
    """HuggingFace 캐시에 모델 다운로드"""
    print(f"\n[{step}] {model['description']} ({model['size']})")
    print(f"      저장소: {model['repo_id']}")
    print("      (HuggingFace 캐시에 저장됨)")
    print("-" * 60)

    try:
        print("다운로드 중...")
        snapshot_download(repo_id=model["repo_id"])
        print(f"✓ {model['description']} 다운로드 완료!")
        return True
    except Exception as e:
        print(f"✗ {model['description']} 다운로드 실패: {e}")
        return False


def download_to_local(model: dict, step: str) -> bool:
    """로컬 디렉토리에 모델 다운로드"""
    print(f"\n[{step}] {model['description']} ({model['size']})")
    print(f"      저장소: {model['repo_id']}")
    print(f"      경로: {model['local_dir']}")
    print("-" * 60)

    try:
        model["local_dir"].parent.mkdir(parents=True, exist_ok=True)
        print("다운로드 중...")
        snapshot_download(
            repo_id=model["repo_id"],
            local_dir=str(model["local_dir"]),
        )
        print(f"✓ {model['description']} 다운로드 완료!")
        return True
    except Exception as e:
        print(f"✗ {model['description']} 다운로드 실패: {e}")
        return False



def download_surya_ocr(model: dict, step: str) -> bool:
    """Surya OCR 모델 다운로드 (Transformer 기반)"""
    print(f"\n[{step}] {model['description']} ({model['size']})")
    print("      (HuggingFace 캐시에 저장됨)")
    print("-" * 60)

    try:
        print("Surya OCR 모델 다운로드 중...")
        from surya.foundation import FoundationPredictor
        from surya.detection import DetectionPredictor
        from surya.recognition import RecognitionPredictor

        # 모델 초기화 시 자동 다운로드
        print("  Foundation 모델 로드 중...")
        foundation = FoundationPredictor()
        print("  Detection 모델 로드 중...")
        det = DetectionPredictor()
        print("  Recognition 모델 로드 중...")
        rec = RecognitionPredictor(foundation)

        # 메모리 해제
        del foundation, det, rec
        import gc
        gc.collect()

        print(f"✓ {model['description']} 다운로드 완료!")
        return True
    except ImportError:
        print("  [스킵] surya-ocr 패키지 미설치 (pip install surya-ocr)")
        return True  # 선택적이므로 실패로 처리하지 않음
    except Exception as e:
        print(f"✗ {model['description']} 다운로드 실패: {e}")
        return False


def _find_ct2_converter() -> str:
    """conda 환경 내 ct2-transformers-converter 실행 파일 경로 반환.
    sys.executable 기준 Scripts(Win) / bin(Linux) 디렉토리를 먼저 탐색하고,
    없으면 PATH에서 찾도록 이름만 반환."""
    import sys
    scripts_dir = Path(sys.executable).parent
    for name in ["ct2-transformers-converter.exe", "ct2-transformers-converter"]:
        candidate = scripts_dir / name
        if candidate.exists():
            return str(candidate)
    return "ct2-transformers-converter"


def convert_nmt_ct2(model: dict, step: str) -> bool:
    """Helsinki opus-mt 모델을 CTranslate2 int8 포맷으로 변환"""
    import subprocess

    print(f"\n[{step}] {model['description']} ({model['size']})")
    print(f"      저장소: {model['repo_id']}")
    print(f"      경로: {model['local_dir']}")
    print("-" * 60)

    if model["local_dir"].exists():
        print(f"✓ 이미 변환됨 → 스킵")
        return True

    try:
        print("CTranslate2 변환 중 (int8 양자화)...")
        model["local_dir"].parent.mkdir(parents=True, exist_ok=True)
        converter = _find_ct2_converter()
        subprocess.run(
            [
                converter,
                "--model", model["repo_id"],
                "--output_dir", str(model["local_dir"]),
                "--quantization", "int8",
                "--force",
            ],
            check=True,
        )
        print(f"✓ {model['description']} 변환 완료!")
        return True
    except FileNotFoundError:
        print(f"✗ ct2-transformers-converter 를 찾을 수 없습니다.")
        print(f"  ctranslate2 패키지가 설치됐는지 확인: pip install ctranslate2")
        return False
    except Exception as e:
        print(f"✗ {model['description']} 변환 실패: {e}")
        return False


def download_tts(model: dict, step: str) -> bool:
    """TTS Piper 모델 다운로드"""
    print(f"\n[{step}] {model['description']} ({model['size']})")
    print(f"      경로: {model['local_dir']}")
    print("-" * 60)

    try:
        model["local_dir"].mkdir(parents=True, exist_ok=True)

        for fname in model["files"]:
            file_path = model["local_dir"] / fname
            if file_path.exists():
                print(f"  {fname} 이미 존재, 스킵")
                continue

            print(f"  다운로드 중: {fname}")
            url = f"{model['base_url']}/{fname}"
            resp = requests.get(url, stream=True)
            resp.raise_for_status()

            with open(file_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"  ✓ {fname} 완료")

        print(f"✓ {model['description']} 다운로드 완료!")
        return True
    except Exception as e:
        print(f"✗ {model['description']} 다운로드 실패: {e}")
        return False


def main():
    print("=" * 60)
    print("Aunion AI 모델 다운로드")
    print("=" * 60)
    print("\n다운로드할 모델:")
    print(f"  1. {VLM_BASE['description']} ({VLM_BASE['size']})")
    print(f"  2. {VLM_LORA['description']} ({VLM_LORA['size']})")
    print(f"  3. {ASR_MODEL['description']} ({ASR_MODEL['size']})")
    print(f"  4. {NMT_MODEL['description']} ({NMT_MODEL['size']})")
    print(f"  5. {TTS_MODEL['description']} ({TTS_MODEL['size']})")
    print(f"  6. {RAPIDOCR_KOREAN['description']} ({RAPIDOCR_KOREAN['size']})")
    print(f"  7. {SURYA_OCR['description']} ({SURYA_OCR['size']})")
    print(f"\n총 예상 용량: ~22GB (최초 1회만 다운로드)")

    results = []

    # 1. VLM Base 모델
    results.append(("VLM Base", download_to_cache(VLM_BASE, "1/7")))

    # 2. VLM LoRA 어댑터
    results.append(("VLM LoRA", download_to_local(VLM_LORA, "2/7")))

    # 3. ASR 모델
    results.append(("ASR", download_to_cache(ASR_MODEL, "3/7")))

    # 4. NMT 모델 (CTranslate2 변환)
    results.append(("NMT", convert_nmt_ct2(NMT_MODEL, "4/7")))

    # 5. TTS 모델
    results.append(("TTS", download_tts(TTS_MODEL, "5/7")))

    # 6. RapidOCR 한국어 모델 (HF 캐시에 저장 — ocr_service.py의 hf_hub_download와 동일 경로)
    results.append(("RapidOCR Korean", download_to_cache(RAPIDOCR_KOREAN, "6/7")))

    # 7. Surya OCR 모델 (Transformer 기반)
    results.append(("Surya OCR", download_surya_ocr(SURYA_OCR, "7/7")))

    # 결과 출력
    print("\n" + "=" * 60)
    print("다운로드 결과")
    print("=" * 60)

    all_success = True
    for name, success in results:
        status = "✓" if success else "✗"
        print(f"  {status} {name}")
        if not success:
            all_success = False

    print()
    if all_success:
        print("모든 모델 다운로드 완료! 이제 서비스를 실행할 수 있습니다.")
        print("  npm run dev")
    else:
        print("일부 모델 다운로드 실패. 위 오류를 확인하세요.")
    print("=" * 60)


if __name__ == "__main__":
    main()
