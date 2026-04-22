"""
슬라이드 라우터
PDF 업로드 및 전처리 (OCR + 번역)
"""
import asyncio
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(prefix="/slides", tags=["Slides"])

# 서비스 인스턴스
_nmt_service = None
_ocr_service = None


def set_nmt_service(service):
    global _nmt_service
    _nmt_service = service


def set_ocr_service(service):
    global _ocr_service
    _ocr_service = service


# 슬라이드 저장 경로
UPLOAD_DIR = Path("uploads/slides")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 이미지 저장 경로
IMAGES_DIR = Path("uploads/images")
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# 처리 상태 저장 (메모리, 실제 서비스에서는 Redis 사용 권장)
slide_status: dict[str, dict] = {}
slide_data: dict[str, list[dict]] = {}


class SlideStatus(BaseModel):
    slide_id: str
    status: str  # pending, processing, completed, failed
    total_pages: int
    processed_pages: int
    error: Optional[str] = None


class OverlayItem(BaseModel):
    original: str
    translated: str
    bbox: Optional[list]
    confidence: float


class PageData(BaseModel):
    pageNumber: int
    imageUrl: str
    ocrText: Optional[str] = None


def get_page_ocr_text(slide_id: str, page_number: int) -> str:
    """현재 슬라이드 페이지의 OCR 텍스트 반환 (NMT 컨텍스트용, 0-indexed)"""
    if slide_id not in slide_data:
        return ""
    pages = slide_data[slide_id]
    if page_number < 0 or page_number >= len(pages):
        return ""
    return pages[page_number].get("ocr_text") or ""


def get_page_overlay(slide_id: str, page_number: int) -> list[dict]:
    """특정 페이지의 오버레이 데이터 반환"""
    if slide_id not in slide_data:
        return []
    pages = slide_data[slide_id]
    if page_number < 0 or page_number >= len(pages):
        return []
    return pages[page_number].get("overlay_items", [])


@router.post("/upload")
async def upload_slide(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    PDF 슬라이드 업로드
    백그라운드에서 OCR + 번역 전처리 수행
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "PDF 파일만 업로드 가능합니다")

    # 고유 ID 생성
    slide_id = str(uuid.uuid4())[:8]

    # 파일 저장
    save_path = UPLOAD_DIR / f"{slide_id}.pdf"
    content = await file.read()

    with open(save_path, "wb") as f:
        f.write(content)

    # 상태 초기화
    slide_status[slide_id] = {
        "status": "pending",
        "total_pages": 0,
        "processed_pages": 0,
        "error": None,
    }

    # 백그라운드 처리 시작
    background_tasks.add_task(process_slide, slide_id, save_path)

    return {"slide_id": slide_id, "message": "업로드 완료, 처리 시작"}


@router.get("/status/{slide_id}")
async def get_status(slide_id: str) -> SlideStatus:
    """슬라이드 처리 상태 조회"""
    if slide_id not in slide_status:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")

    status = slide_status[slide_id]
    return SlideStatus(
        slide_id=slide_id,
        status=status["status"],
        total_pages=status["total_pages"],
        processed_pages=status["processed_pages"],
        error=status["error"],
    )


@router.get("/pages/{slide_id}")
async def get_pages(slide_id: str):
    """처리된 페이지 데이터 조회"""
    if slide_id not in slide_data:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")

    pages = [
        PageData(
            pageNumber=page["page_number"] + 1,  # 1-indexed for frontend
            imageUrl=f"/slides/image/{slide_id}/{page['page_number']}",
            ocrText=page.get("ocr_text"),
        )
        for page in slide_data[slide_id]
    ]
    return {"pages": pages}


@router.get("/image/{slide_id}/{page_number}")
async def get_image(slide_id: str, page_number: int):
    """슬라이드 이미지 반환"""
    image_path = IMAGES_DIR / f"{slide_id}_{page_number}.png"
    if not image_path.exists():
        raise HTTPException(404, "이미지를 찾을 수 없습니다")
    return FileResponse(image_path, media_type="image/png")


@router.get("/download/{slide_id}")
async def download_slide(slide_id: str, type: str = "original"):
    """
    슬라이드 PDF 다운로드
    - type=original: 원본 PDF
    - type=translated: 번역본 PDF (TODO)
    """
    if type == "original":
        pdf_path = UPLOAD_DIR / f"{slide_id}.pdf"
        if not pdf_path.exists():
            raise HTTPException(404, "PDF 파일을 찾을 수 없습니다")
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=f"강의자료_{slide_id}.pdf"
        )
    elif type == "translated":
        # TODO: 번역본 PDF 생성 기능 추가 필요
        raise HTTPException(501, "번역본 다운로드는 아직 준비 중입니다")
    else:
        raise HTTPException(400, "type은 'original' 또는 'translated'여야 합니다")


async def process_slide(slide_id: str, pdf_path: Path):
    """
    슬라이드 전처리 (백그라운드)
    PDF → 이미지 저장 (OCR/번역은 AI 서비스가 있을 때만)
    """
    try:
        slide_status[slide_id]["status"] = "processing"

        # PDF를 이미지로 변환
        images = await asyncio.to_thread(pdf_to_images, pdf_path)
        total_pages = len(images)
        slide_status[slide_id]["total_pages"] = total_pages

        slide_data[slide_id] = []

        for i, image_bytes in enumerate(images):
            # 이미지 파일로 저장
            image_path = IMAGES_DIR / f"{slide_id}_{i}.png"
            with open(image_path, "wb") as f:
                f.write(image_bytes)

            # OCR + 번역 (서비스가 있을 때만)
            ocr_text = None
            overlay_items = []

            if _ocr_service and _nmt_service:
                try:
                    ocr_results = await asyncio.to_thread(
                        _ocr_service.extract_with_positions, image_bytes
                    )

                    texts = []
                    for item in ocr_results:
                        text = item["text"]
                        if text.strip():
                            texts.append(text)

                    ocr_text = "\n".join(texts)

                    # 번역 — 페이지 내 모든 텍스트를 배치로 한 번에 처리
                    valid_items = [
                        item for item in ocr_results if item["text"].strip()
                    ]
                    batch_texts = [item["text"] for item in valid_items]

                    if batch_texts:
                        translations = await asyncio.to_thread(
                            _nmt_service.translate_batch, batch_texts
                        )
                        for item, translated in zip(valid_items, translations):
                            if not translated.strip():
                                continue
                            raw_bbox = item["bbox"]
                            if raw_bbox is None:
                                bbox = None
                            elif len(raw_bbox) == 4:
                                bbox = [
                                    raw_bbox[0][0], raw_bbox[0][1],
                                    raw_bbox[2][0], raw_bbox[2][1],
                                ]
                            else:
                                bbox = raw_bbox
                            overlay_items.append({
                                "original": item["text"],
                                "translated": translated,
                                "bbox": bbox,
                                "confidence": item["confidence"],
                            })
                except Exception as e:
                    print(f"[Slides] OCR/번역 실패 (무시): {e}")

            # 저장
            slide_data[slide_id].append({
                "page_number": i,
                "ocr_text": ocr_text,
                "overlay_items": overlay_items,
            })

            slide_status[slide_id]["processed_pages"] = i + 1
            print(f"[Slides] {slide_id} 페이지 {i + 1}/{total_pages} 처리 완료")

        slide_status[slide_id]["status"] = "completed"
        print(f"[Slides] {slide_id} 전처리 완료")

    except Exception as e:
        slide_status[slide_id]["status"] = "failed"
        slide_status[slide_id]["error"] = str(e)
        print(f"[Slides] {slide_id} 처리 실패: {e}")


def pdf_to_images(pdf_path: Path) -> list[bytes]:
    """PDF를 이미지 리스트로 변환"""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise RuntimeError("PyMuPDF가 설치되지 않았습니다: pip install pymupdf")

    doc = fitz.open(str(pdf_path))
    images = []

    for page in doc:
        # 2배 해상도로 렌더링
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        images.append(pix.tobytes("png"))

    doc.close()
    return images


