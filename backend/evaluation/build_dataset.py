"""
OCR 평가 데이터셋 구성 스크립트

pdfs/ 폴더의 PDF를 읽어:
1. PyMuPDF로 텍스트 추출 (Ground Truth)
2. 페이지를 이미지로 변환
3. dataset/ 폴더에 저장
"""
import json
from pathlib import Path

import fitz  # PyMuPDF

PDF_DIR = Path(__file__).parent / "pdfs"
DATASET_DIR = Path(__file__).parent / "dataset"
IMAGE_DIR = DATASET_DIR / "images"
GT_FILE = DATASET_DIR / "ground_truth.json"

DPI = 150  # 슬라이드 이미지 해상도


def extract_page(doc: fitz.Document, page_num: int, image_path: Path) -> str:
    page = doc[page_num]

    # Ground Truth: PyMuPDF 텍스트 추출
    text = page.get_text("text").strip()

    # 이미지 변환
    mat = fitz.Matrix(DPI / 72, DPI / 72)
    pix = page.get_pixmap(matrix=mat)
    pix.save(str(image_path))

    return text


def build(pdf_dir: Path = PDF_DIR):
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        print(f"[ERROR] {pdf_dir} 에 PDF 파일이 없습니다.")
        print("  → python download_pdfs.py 를 먼저 실행하거나 PDF를 직접 넣어주세요.")
        return

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    ground_truth = []

    for pdf_path in pdfs:
        print(f"\n[PDF] {pdf_path.name}")
        doc = fitz.open(str(pdf_path))

        for page_num in range(len(doc)):
            stem = f"{pdf_path.stem}_p{page_num + 1:03d}"
            image_path = IMAGE_DIR / f"{stem}.png"

            text = extract_page(doc, page_num, image_path)

            # 텍스트가 없는 페이지(이미지 전용 슬라이드) 제외
            if not text:
                image_path.unlink(missing_ok=True)
                continue

            ground_truth.append({
                "id": stem,
                "image": str(image_path.relative_to(DATASET_DIR)),
                "source_pdf": pdf_path.name,
                "page": page_num + 1,
                "ground_truth": text,
            })

            print(f"  [OK] {stem} ({len(text)}자)")

        doc.close()

    GT_FILE.write_text(json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n데이터셋 구성 완료: {len(ground_truth)}개 슬라이드")
    print(f"저장 위치: {DATASET_DIR}")


if __name__ == "__main__":
    build()
