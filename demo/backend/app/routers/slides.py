"""
슬라이드 라우터
PDF 업로드 및 전처리 (OCR + 번역)
"""
import asyncio
import hashlib
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
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
    bbox: list
    confidence: float


class PageData(BaseModel):
    page_number: int
    image_hash: str
    overlay_items: list[OverlayItem]


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
async def get_pages(slide_id: str) -> list[PageData]:
    """처리된 페이지 데이터 조회"""
    if slide_id not in slide_data:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")

    return [
        PageData(
            page_number=page["page_number"],
            image_hash=page["image_hash"],
            overlay_items=page.get("overlay_items", []),
        )
        for page in slide_data[slide_id]
    ]


@router.get("/page/{slide_id}/{page_number}")
async def get_page(slide_id: str, page_number: int) -> PageData:
    """특정 페이지 데이터 조회"""
    if slide_id not in slide_data:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")

    pages = slide_data[slide_id]
    if page_number < 0 or page_number >= len(pages):
        raise HTTPException(404, "페이지를 찾을 수 없습니다")

    page = pages[page_number]
    return PageData(
        page_number=page["page_number"],
        image_hash=page["image_hash"],
        overlay_items=page.get("overlay_items", []),
    )


async def process_slide(slide_id: str, pdf_path: Path):
    """
    슬라이드 전처리 (백그라운드)
    PDF → 이미지 → OCR → 번역
    """
    try:
        slide_status[slide_id]["status"] = "processing"

        # PDF를 이미지로 변환
        images = await asyncio.to_thread(pdf_to_images, pdf_path)
        total_pages = len(images)
        slide_status[slide_id]["total_pages"] = total_pages

        slide_data[slide_id] = []

        for i, image in enumerate(images):
            # 이미지 해시 (페이지 매칭용)
            image_hash = compute_image_hash(image)

            # OCR로 텍스트와 위치 정보 추출
            ocr_results = await asyncio.to_thread(
                _ocr_service.extract_with_positions, image
            )

            # 번역 및 오버레이 데이터 생성
            overlay_items = []
            for item in ocr_results:
                text = item["text"]
                if text.strip():
                    translated = await asyncio.to_thread(
                        _nmt_service.translate, text
                    )
                    # bbox 형식 변환: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] -> [x1, y1, x3, y3]
                    raw_bbox = item["bbox"]
                    if len(raw_bbox) == 4:
                        # 4 꼭짓점에서 좌상단(0), 우하단(2) 추출
                        bbox = [
                            raw_bbox[0][0],  # x1
                            raw_bbox[0][1],  # y1
                            raw_bbox[2][0],  # x2
                            raw_bbox[2][1],  # y2
                        ]
                    else:
                        bbox = raw_bbox

                    overlay_items.append({
                        "original": text,
                        "translated": translated,
                        "bbox": bbox,
                        "confidence": item["confidence"],
                    })

            # 저장
            slide_data[slide_id].append({
                "page_number": i,
                "image_hash": image_hash,
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


def compute_image_hash(image_bytes: bytes) -> str:
    """이미지 해시 계산 (페이지 매칭용)"""
    # 간단한 MD5 해시 (실제로는 pHash 등 사용 권장)
    return hashlib.md5(image_bytes).hexdigest()[:16]
