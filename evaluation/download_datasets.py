"""
평가 데이터셋 다운로드 안내 스크립트

수동 다운로드 (AI Hub 로그인 필요):
  ASR : 한국어 강의 음성        → https://aihub.or.kr/aidata/30708
  NMT : 한국어-영어 번역 코퍼스  → https://aihub.or.kr/aidata/87
  OCR : 문서 OCR               → https://aihub.or.kr/aidata/33

사용법:
    python evaluation/download_datasets.py        # 수동 다운로드 안내 출력
    python evaluation/download_datasets.py --guide # 동일
"""
import sys
import argparse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EVAL_DIR = Path(__file__).parent


# ────────────────────────────────────────────────────────────────────
# 수동 다운로드 안내
# ────────────────────────────────────────────────────────────────────
def print_guide():
    print("\n" + "="*60)
    print("[ASR] 수동 다운로드 — AI Hub 한국어 강의 음성")
    print("  URL : https://aihub.or.kr/aidata/30708")
    print("  권장 샘플 수: 200개 (8~15초 발화, D11~D19 도메인)")
    print("  저장 위치: evaluation/datasets/asr_samples/")
    print("""  ground_truth.json 형식:
  [
    {"file": "파일명.wav", "text": "정답텍스트", "duration_sec": 3.5},
    ...
  ]""")

    print("\n" + "="*60)
    print("[NMT] 수동 다운로드 — AI Hub 한국어-영어 번역 코퍼스")
    print("  URL : https://aihub.or.kr/aidata/87")
    print("  권장 샘플 수: 200개 (구어체/대화체 도메인)")
    print("  저장 위치: evaluation/datasets/nmt_samples/")
    print("""  ko_en_pairs.json 형식:
  [
    {"ko": "한국어 문장", "en": "English sentence", "source": "AI Hub"},
    ...
  ]""")

    print("\n" + "="*60)
    print("[OCR] 수동 다운로드 — AI Hub 문서 OCR")
    print("  URL : https://aihub.or.kr/aidata/33")
    print("  권장 샘플 수: 300개 이상 (다양한 레이아웃 커버리지)")
    print("  저장 위치: evaluation/datasets/ocr_samples/")
    print("""  ground_truth.json 형식:
  [
    {"file": "이미지파일.png", "text": "슬라이드 텍스트 내용"},
    ...
  ]""")


# ────────────────────────────────────────────────────────────────────
# 메인
# ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="평가 데이터셋 준비 안내")
    parser.add_argument("--guide", action="store_true", help="수동 다운로드 안내 출력")
    args = parser.parse_args()

    print_guide()


if __name__ == "__main__":
    main()
