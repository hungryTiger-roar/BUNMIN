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

# HuggingFace 저장소
MODEL = {
    "repo_id": "sanghoon1234/qwen3-vl-8b-lora-ko2en",
    "local_dir": MODELS_DIR / "qwen3" / "qwen3-vl-8b-lora-r64-e3-final",
    "description": "VLM 번역 모델 (LoRA r=64, ~665MB)",
}


def main():
    print("=" * 60)
    print("VLM 모델 다운로드")
    print("=" * 60)
    print(f"\n모델: {MODEL['description']}")
    print(f"저장소: {MODEL['repo_id']}")
    print(f"경로: {MODEL['local_dir']}")
    print("=" * 60)

    try:
        # 디렉토리 생성
        MODEL["local_dir"].parent.mkdir(parents=True, exist_ok=True)

        # 다운로드
        print("\n다운로드 중...")
        snapshot_download(
            repo_id=MODEL["repo_id"],
            local_dir=str(MODEL["local_dir"]),
            local_dir_use_symlinks=False,
        )
        print(f"\n✓ 다운로드 완료!")
        print(f"  경로: {MODEL['local_dir']}")

    except Exception as e:
        print(f"\n✗ 다운로드 실패: {e}")
        return

    print("\n" + "=" * 60)
    print("완료! 이제 서비스를 실행할 수 있습니다.")
    print("  npm run dev")
    print("=" * 60)


if __name__ == "__main__":
    main()
