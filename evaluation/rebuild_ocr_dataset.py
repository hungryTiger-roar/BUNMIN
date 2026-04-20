"""
OCR 평가 데이터셋 구성 스크립트

KOCW(https://www.kocw.net) 등에서 수동으로 받은 한국어 강의 PDF를
이미지로 변환하고 ground_truth.json을 생성합니다.

사용법:
    1. evaluation/datasets/ocr_pdfs/ 에 PDF 파일을 넣는다
    2. python evaluation/rebuild_ocr_dataset.py

출력:
    evaluation/datasets/ocr_samples/
    ├── <강의명>_p001.png
    ├── <강의명>_p002.png
    ├── ...
    └── ground_truth.json
"""
import json
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PDF_DIR            = Path(__file__).parent / "datasets" / "ocr_samples"
OCR_DIR            = Path(__file__).parent / "datasets" / "ocr_samples"
GT_FILE            = OCR_DIR / "ground_truth.json"
DPI                = 150
MAX_SLIDES_PER_SUBJECT = 5    # 과목당 최대 슬라이드 수 (총 ~150장 목표)

# 슬라이드 선별 기준
MIN_CHARS   = 50    # 너무 짧은 슬라이드 제외 (제목 한 줄 등)
MAX_CHARS   = 500   # 너무 긴 슬라이드 제외 (참고문헌, 빽빽한 논문 인용 등)
MIN_KO_RATIO = 0.4  # 한글 비율 40% 미만 제외 (수식·코드·영문 위주)


def _ko_ratio(text: str) -> float:
    """한글 문자 비율 계산"""
    if not text:
        return 0.0
    ko_chars = sum(1 for c in text if '\uAC00' <= c <= '\uD7A3')
    return ko_chars / len(text)


def _is_good_slide(text: str) -> bool:
    """선별 기준 통과 여부"""
    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        return False
    if _ko_ratio(text) < MIN_KO_RATIO:
        return False
    return True


def main():
    print("=" * 60)
    print("OCR 평가 데이터셋 구성 (KOCW 한국어 강의 PDF)")
    print("=" * 60)

    # PDF 확인
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(PDF_DIR.glob("*.pdf"))

    if not pdfs:
        print(f"\n[안내] {PDF_DIR} 에 PDF 파일이 없습니다.")
        print("  KOCW(https://www.kocw.net)에서 강의 자료 PDF를 다운로드한 뒤")
        print("  해당 폴더에 넣고 다시 실행하세요.")
        print("\n  권장 분야: 인문학, 사회과학, 자연과학, 공학, IT 등")
        sys.exit(0)

    # PyMuPDF 확인
    try:
        import fitz
    except ImportError:
        print("[ERROR] PyMuPDF 미설치: pip install pymupdf")
        sys.exit(1)

    # 기존 이미지·JSON만 정리 (PDF는 보존)
    print(f"\n[1/2] 기존 이미지·JSON 정리 중...")
    OCR_DIR.mkdir(parents=True, exist_ok=True)
    for f in OCR_DIR.iterdir():
        if f.suffix.lower() in (".png", ".jpg", ".jpeg") or f.name == "ground_truth.json":
            f.unlink()
    print(f"  완료: {OCR_DIR}")

    # PDF → 이미지 + ground truth
    print(f"\n[2/2] PDF 변환 중 ({len(pdfs)}개)...")
    print(f"  선별 기준: {MIN_CHARS}~{MAX_CHARS}자, 한글 비율 {MIN_KO_RATIO*100:.0f}% 이상, 과목당 최대 {MAX_SLIDES_PER_SUBJECT}장")
    ground_truth = []
    skipped = 0
    filtered = 0
    subject_counts: dict[str, int] = {}

    for pdf_path in pdfs:
        subject = pdf_path.stem.split("_")[0]
        if subject_counts.get(subject, 0) >= MAX_SLIDES_PER_SUBJECT:
            continue

        doc = fitz.open(str(pdf_path))

        for page_num in range(len(doc)):
            if subject_counts.get(subject, 0) >= MAX_SLIDES_PER_SUBJECT:
                break

            page = doc[page_num]
            text = page.get_text("text").strip()

            if not text:
                skipped += 1
                continue

            if not _is_good_slide(text):
                filtered += 1
                continue

            filename   = f"{pdf_path.stem}_p{page_num + 1:03d}.png"
            image_path = OCR_DIR / filename

            mat = fitz.Matrix(DPI / 72, DPI / 72)
            pix = page.get_pixmap(matrix=mat)
            pix.save(str(image_path))

            ground_truth.append({"file": filename, "text": text})
            subject_counts[subject] = subject_counts.get(subject, 0) + 1
            print(f"  [OK] {subject:12s} ({subject_counts[subject]}/{MAX_SLIDES_PER_SUBJECT})  {filename[-30:]}  {len(text)}자  한글{_ko_ratio(text)*100:.0f}%")

        doc.close()

    GT_FILE.write_text(
        json.dumps(ground_truth, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print(f"완료: {len(ground_truth)}개 슬라이드 생성")
    print(f"  제외: 텍스트 없음 {skipped}개 / 선별 기준 미달 {filtered}개")
    print(f"  과목 수: {len(subject_counts)}개")
    for subj, cnt in sorted(subject_counts.items()):
        print(f"    {subj}: {cnt}장")
    print(f"저장 위치: {OCR_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
