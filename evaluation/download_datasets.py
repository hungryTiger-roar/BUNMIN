"""
평가 데이터셋 다운로드 스크립트

자동 생성:
  TTS : NMT 데이터셋(ko_en_pairs.json)의 영어 문장 사용
        → 실제 서비스에서 TTS가 받을 텍스트와 동일 도메인

수동 다운로드 (AI Hub 로그인 필요):
  ASR : 한국어 강의 음성        → https://aihub.or.kr/aidata/30708
  NMT : 한국어-영어 번역 코퍼스  → https://aihub.or.kr/aidata/87
  OCR : 문서 OCR               → https://aihub.or.kr/aidata/33

사용법:
    python evaluation/download_datasets.py       # TTS 생성
    python evaluation/download_datasets.py --tts # TTS만
    python evaluation/download_datasets.py --guide # 수동 다운로드 안내 출력
"""
import sys
import json
import argparse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EVAL_DIR = Path(__file__).parent
TTS_DIR  = EVAL_DIR / "datasets" / "tts_samples"
NMT_DIR  = EVAL_DIR / "datasets" / "nmt_samples"

TTS_SAMPLES = 100


# ────────────────────────────────────────────────────────────────────
# TTS : ko_en_pairs.json의 영어 문장 사용
# ────────────────────────────────────────────────────────────────────
def download_tts():
    print("\n" + "="*60)
    print("[TTS] TTS 평가 텍스트 생성")
    print("  출처: NMT 데이터셋 (ko_en_pairs.json) 영어 문장")
    print(f"  목표: {TTS_SAMPLES}개")
    print("="*60)

    nmt_path = NMT_DIR / "ko_en_pairs.json"
    if not nmt_path.exists():
        print(f"[ERROR] {nmt_path} 없음. NMT 데이터셋을 먼저 준비하세요.")
        return False

    with open(nmt_path, encoding="utf-8") as f:
        pairs = json.load(f)

    TTS_DIR.mkdir(parents=True, exist_ok=True)

    texts = [s["en"] for s in pairs if len(s["en"].split()) >= 5][:TTS_SAMPLES]

    if not texts:
        print("[ERROR] 텍스트 추출 실패.")
        return False

    out_path = TTS_DIR / "texts.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(texts, f, ensure_ascii=False, indent=2)

    print(f"\n  ✓ {len(texts)}개 텍스트 저장 완료")
    print(f"    위치: {out_path}")
    print(f"    예시: {texts[0]}")
    return True


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
    print("[TTS] NMT 데이터셋에서 자동 생성")
    print("  python evaluation/download_datasets.py --tts")

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
    parser = argparse.ArgumentParser(description="평가 데이터셋 준비")
    parser.add_argument("--tts",   action="store_true", help="TTS 텍스트 생성")
    parser.add_argument("--guide", action="store_true", help="수동 다운로드 안내 출력")
    args = parser.parse_args()

    if args.guide:
        print_guide()
        return

    ok = download_tts()

    print("\n" + "="*60)
    print("결과")
    print("="*60)
    print(f"  TTS : {'✓ 완료' if ok else '✗ 실패'} (NMT 영어 문장 {TTS_SAMPLES}개)")
    print("  ASR : 수동 다운로드 필요 (https://aihub.or.kr/aidata/30708)")
    print("  NMT : 수동 다운로드 필요 (https://aihub.or.kr/aidata/87)")
    print("  OCR : 수동 다운로드 필요 (https://aihub.or.kr/aidata/33)")
    print("\n  수동 다운로드 안내: python evaluation/download_datasets.py --guide")


if __name__ == "__main__":
    main()
