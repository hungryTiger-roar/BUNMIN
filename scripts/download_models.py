"""
AI 모델 다운로드 스크립트
HuggingFace Hub에서 필요한 모델들을 미리 다운로드합니다.

사용법:
    python scripts/download_models.py

필요 조건:
    pip install huggingface_hub
"""

import os
import sys
from pathlib import Path
from huggingface_hub import snapshot_download

# ─── HF 캐시 경로를 백엔드와 동일하게 설정 ────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent
_HF_HOME = _PROJECT_ROOT / "backend" / "cache" / "huggingface"
_HF_HOME.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(_HF_HOME))

# 모델 저장 경로
MODELS_DIR = _PROJECT_ROOT / "models"

# ============================================
# 다운로드할 모델 목록
# ============================================

# VLM Base 모델 (HuggingFace 캐시에 저장)
VLM_BASE = {
    "repo_id": "Qwen/Qwen3-VL-4B-Instruct",
    # 로컬 평탄 디렉토리 사용 — Windows 심볼릭 미지원 환경에서 HF 캐시
    # snapshots/blobs 분리 구조가 부분 실패하는 문제 회피
    "local_dir": MODELS_DIR / "qwen3-vl-4b-instruct",
    "description": "VLM Base 모델 (4B)",
    "size": "~8GB",  # bf16 가중치 (4B params × 2 bytes)
}

# ASR 모델 (음성 인식) — openai 원본 turbo를 CTranslate2 int8로 변환
# ghost613 한국어 fine-tune은 한국 뉴스 정형구 환각이 심해 교체 (S14P31S205-64)
# 변환 시 --copy_files 로 tokenizer.json + preprocessor_config.json 복사 필수
# (large-v3는 128 mel — 안 넣으면 mel 미스매치 ValueError)
ASR_MODEL = {
    "repo_id": "openai/whisper-large-v3-turbo",
    "local_dir": MODELS_DIR / "whisper-large-v3-turbo-ct2-int8",
    "description": "ASR 음성인식 모델 (CTranslate2 int8)",
    "size": "~800MB (변환 후)",
}

# NMT 모델 (실시간 번역) — CTranslate2 변환 대상
# Meta 의 200개 언어 다국어 모델, 짧은 인사말·다문장에서도 환각 거의 없음
NMT_MODEL = {
    "repo_id": "facebook/nllb-200-distilled-600M",
    "local_dir": MODELS_DIR / "nllb-200-distilled-600M-ct2",
    "description": "NMT 실시간 번역 모델 (CTranslate2 int8, 다국어)",
    "size": "~600MB",
}

# Surya OCR 모델 (Transformer 기반, 고정확도)
SURYA_OCR = {
    "description": "Surya OCR (Transformer 기반)",
    "size": "~500MB",
}


def download_to_cache(model: dict, step: str, retries: int = 3) -> bool:
    """HuggingFace 캐시에 모델 다운로드 (네트워크 끊김에 대비해 재시도)"""
    print(f"\n[{step}] {model['description']} ({model['size']})")
    print(f"      저장소: {model['repo_id']}")
    print("      (HuggingFace 캐시에 저장됨)")
    print("-" * 60)

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            print(f"다운로드 중... (시도 {attempt}/{retries})")
            # snapshot_download는 기본적으로 부분 다운로드를 이어받음
            snapshot_download(repo_id=model["repo_id"])
            print(f"✓ {model['description']} 다운로드 완료!")
            return True
        except Exception as e:
            last_err = e
            print(f"  시도 {attempt} 실패: {e}")
    print(f"✗ {model['description']} 다운로드 실패 (재시도 {retries}회 모두 실패): {last_err}")
    return False


def download_to_local(model: dict, step: str, retries: int = 3) -> bool:
    """로컬 디렉토리에 모델 다운로드 (재시도 포함)"""
    print(f"\n[{step}] {model['description']} ({model['size']})")
    print(f"      저장소: {model['repo_id']}")
    print(f"      경로: {model['local_dir']}")
    print("-" * 60)

    model["local_dir"].parent.mkdir(parents=True, exist_ok=True)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            print(f"다운로드 중... (시도 {attempt}/{retries})")
            snapshot_download(
                repo_id=model["repo_id"],
                local_dir=str(model["local_dir"]),
            )
            print(f"✓ {model['description']} 다운로드 완료!")
            return True
        except Exception as e:
            last_err = e
            print(f"  시도 {attempt} 실패: {e}")
    print(f"✗ {model['description']} 다운로드 실패 (재시도 {retries}회 모두 실패): {last_err}")
    return False




def download_vlm_processor(model: dict, step: str) -> bool:
    """VLM 프로세서 파일 다운로드 (AutoProcessor가 필요로 하는 추가 파일)"""
    print(f"\n[{step}] VLM 프로세서 파일 확인")
    print(f"      경로: {model['local_dir']}")
    print("-" * 60)

    try:
        print("VLM 프로세서 로드 중 (추가 파일 다운로드)...")
        from transformers import AutoProcessor

        # AutoProcessor.from_pretrained 호출 시 누락된 파일 자동 다운로드
        processor = AutoProcessor.from_pretrained(
            str(model["local_dir"]),
            trust_remote_code=True,
        )
        del processor

        import gc
        gc.collect()

        print("✓ VLM 프로세서 파일 준비 완료!")
        return True
    except Exception as e:
        print(f"✗ VLM 프로세서 다운로드 실패: {e}")
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
    """NLLB-200 모델을 CTranslate2 int8 포맷으로 변환.
    --copy_files 로 NllbTokenizer 가 필요로 하는 파일들을 동봉 →
    nmt_service 가 AutoTokenizer.from_pretrained(local_dir) 로 직접 로드 가능."""
    import subprocess

    print(f"\n[{step}] {model['description']} ({model['size']})")
    print(f"      저장소: {model['repo_id']}")
    print(f"      경로: {model['local_dir']}")
    print("-" * 60)

    # CT2 변환 산출물 + NLLB 토크나이저 파일 — 일부만 있는 부분 변환 상태 차단
    required = [
        "model.bin", "config.json",
        "tokenizer.json", "sentencepiece.bpe.model",
        "tokenizer_config.json", "special_tokens_map.json",
    ]
    if model["local_dir"].exists():
        missing = [f for f in required if not (model["local_dir"] / f).exists()]
        if not missing:
            print(f"✓ 이미 변환됨 → 스킵")
            return True
        print(f"⚠ 부분 변환 상태 (누락: {missing}) → 재변환")
        import shutil
        shutil.rmtree(model["local_dir"])

    try:
        print("CTranslate2 변환 중 (int8 양자화 + 토크나이저 동봉)...")
        model["local_dir"].parent.mkdir(parents=True, exist_ok=True)
        converter = _find_ct2_converter()
        subprocess.run(
            [
                converter,
                "--model", model["repo_id"],
                "--output_dir", str(model["local_dir"]),
                "--copy_files",
                "tokenizer.json", "sentencepiece.bpe.model",
                "special_tokens_map.json", "tokenizer_config.json",
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


def convert_asr_ct2(model: dict, step: str) -> bool:
    """openai/whisper-large-v3-turbo를 CTranslate2 int8 포맷으로 변환.
    --copy_files로 tokenizer.json + preprocessor_config.json 복사 (large-v3는 128 mel — 안 넣으면 mel 미스매치 ValueError)."""
    import subprocess

    print(f"\n[{step}] {model['description']} ({model['size']})")
    print(f"      저장소: {model['repo_id']}")
    print(f"      경로: {model['local_dir']}")
    print("-" * 60)

    # CTranslate2 + faster-whisper가 요구하는 필수 파일 — 부분 변환 상태 차단
    required = ["model.bin", "config.json", "vocabulary.json", "tokenizer.json", "preprocessor_config.json"]
    if model["local_dir"].exists():
        missing = [f for f in required if not (model["local_dir"] / f).exists()]
        if not missing:
            print(f"✓ 이미 변환됨 → 스킵")
            return True
        print(f"⚠ 부분 변환 상태 (누락: {missing}) → 재변환")
        import shutil
        shutil.rmtree(model["local_dir"])

    try:
        print("CTranslate2 변환 중 (int8 양자화)...")
        model["local_dir"].parent.mkdir(parents=True, exist_ok=True)
        converter = _find_ct2_converter()
        subprocess.run(
            [
                converter,
                "--model", model["repo_id"],
                "--output_dir", str(model["local_dir"]),
                "--copy_files", "tokenizer.json", "preprocessor_config.json",
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


def main():
    # SKIP_VLM_DOWNLOAD=true 면 VLM 건너뜀.
    # 근거: electron-builder.json extraResources 에 VLM 미포함 (setup.exe 안 들어감).
    #       빌드 PC 에 VLM 받아둘 필요 없음 — 사용자 PC 첫 슬라이드 처리 시 자동 다운.
    skip_vlm = os.environ.get("SKIP_VLM_DOWNLOAD", "").lower() == "true"

    print("=" * 60)
    print("Aunion AI 모델 다운로드")
    print("=" * 60)
    print("\n다운로드할 모델:")
    if not skip_vlm:
        print(f"  1. {VLM_BASE['description']} ({VLM_BASE['size']})")
    print(f"  2. {ASR_MODEL['description']} ({ASR_MODEL['size']})")
    print(f"  3. {NMT_MODEL['description']} ({NMT_MODEL['size']})")
    print(f"  4. {SURYA_OCR['description']} ({SURYA_OCR['size']})")
    print(f"\n총 예상 용량: {'~2GB (VLM 제외)' if skip_vlm else '~10GB'} (최초 1회만 다운로드)")

    results = []

    if skip_vlm:
        print("\n[SKIP] VLM 다운로드 건너뜀 — 사용자 PC 첫 슬라이드 처리 시 HF 에서 자동 다운로드.")
    else:
        # 1. VLM Base 모델 (로컬 디렉토리 — HF 캐시 심볼릭 이슈 회피)
        results.append(("VLM Base", download_to_local(VLM_BASE, "1/5")))
        # 1-b. VLM 프로세서 파일 (AutoProcessor가 필요로 하는 추가 파일)
        results.append(("VLM Processor", download_vlm_processor(VLM_BASE, "1-b/5")))

    # 2. ASR 모델 (CTranslate2 int8 변환)
    results.append(("ASR", convert_asr_ct2(ASR_MODEL, "2/5")))

    # 3. NMT 모델 (CTranslate2 변환)
    results.append(("NMT", convert_nmt_ct2(NMT_MODEL, "3/5")))

    # 4. Surya OCR 모델 (Transformer 기반)
    results.append(("Surya OCR", download_surya_ocr(SURYA_OCR, "4/5")))

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

    # 핵심 모델 실패 시 setup이 멈추도록 종료 코드 1
    # → silent fail로 첫 추론에서 16GB를 다시 받는 사고 방지
    # SKIP_VLM_DOWNLOAD=true 면 VLM 은 critical 에서 빠짐 (사용자 PC 에서 받음).
    critical = {"ASR", "NMT"} if skip_vlm else {"VLM Base", "VLM Processor", "ASR", "NMT"}
    failed_critical = [name for name, ok in results if not ok and name in critical]
    if failed_critical:
        print(f"\n[중단] 핵심 모델 실패: {', '.join(failed_critical)}")
        print("       네트워크 확인 후 다시 실행해주세요:")
        print("       conda run -n aunion python scripts/download_models.py")
        sys.exit(1)


if __name__ == "__main__":
    main()
