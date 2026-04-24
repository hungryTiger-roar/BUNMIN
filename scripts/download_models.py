"""
VLM 모델 다운로드 스크립트
HuggingFace Hub에서 모델을 다운로드합니다.

사용법:
    python scripts/download_models.py

필요 조건:
    pip install huggingface_hub
"""

from pathlib import Path
from huggingface_hub import snapshot_download

# 모델 저장 경로
MODELS_DIR = Path(__file__).parent.parent / "models"

# Base 모델 (HuggingFace 캐시에 저장)
BASE_MODEL = {
    "repo_id": "Qwen/Qwen3-VL-8B-Instruct",
    "description": "Base VLM 모델 (~17GB, 최초 1회만 다운로드)",
}

# LoRA 어댑터 (로컬 디렉토리에 저장)
LORA_MODEL = {
    "repo_id": "sanghoon1234/qwen3-vl-8b-lora-ko2en",
    "local_dir": MODELS_DIR / "qwen3" / "qwen3-vl-8b-lora-r64-e3-final",
    "description": "VLM 번역 모델 LoRA (~665MB)",
}


def main():
    print("=" * 60)
    print("VLM 모델 다운로드")
    print("=" * 60)

    # 1. Base 모델 다운로드 (HuggingFace 캐시)
    print(f"\n[1/2] Base 모델: {BASE_MODEL['description']}")
    print(f"      저장소: {BASE_MODEL['repo_id']}")
    print("      (HuggingFace 캐시에 저장됨)")
    print("-" * 60)

    try:
        print("다운로드 중... (최초 실행 시 ~17GB, 시간이 오래 걸릴 수 있습니다)")
        snapshot_download(
            repo_id=BASE_MODEL["repo_id"],
        )
        print("✓ Base 모델 다운로드 완료!")
    except Exception as e:
        print(f"✗ Base 모델 다운로드 실패: {e}")
        return

    # 2. LoRA 어댑터 다운로드
    print(f"\n[2/2] LoRA 어댑터: {LORA_MODEL['description']}")
    print(f"      저장소: {LORA_MODEL['repo_id']}")
    print(f"      경로: {LORA_MODEL['local_dir']}")
    print("-" * 60)

    try:
        LORA_MODEL["local_dir"].parent.mkdir(parents=True, exist_ok=True)
        print("다운로드 중...")
        snapshot_download(
            repo_id=LORA_MODEL["repo_id"],
            local_dir=str(LORA_MODEL["local_dir"]),
            local_dir_use_symlinks=False,
        )
        print("✓ LoRA 어댑터 다운로드 완료!")
    except Exception as e:
        print(f"✗ LoRA 어댑터 다운로드 실패: {e}")
        return

    print("\n" + "=" * 60)
    print("완료! 이제 서비스를 실행할 수 있습니다.")
    print("  npm run dev")
    print("=" * 60)


if __name__ == "__main__":
    main()
