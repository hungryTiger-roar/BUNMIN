"""
슬라이드 라우터
PDF 업로드 및 전처리 (OCR + VLM 번역)
"""
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel

# translate_slide_v3 모듈 경로 추가
_REPO_DIR = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_REPO_DIR))

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

# 이미지 저장 경로 (원본)
IMAGES_DIR = Path("uploads/images")
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# 번역된 이미지 저장 경로
TRANSLATED_DIR = Path("uploads/translated")
TRANSLATED_DIR.mkdir(parents=True, exist_ok=True)

# 처리 상태 저장 (메모리, 실제 서비스에서는 Redis 사용 권장)
slide_status: dict[str, dict] = {}
slide_data: dict[str, list[dict]] = {}

# 번역 상태 별도 관리
translation_status: dict[str, dict] = {}


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
        "filename": file.filename or f"{slide_id}.pdf",
    }

    # 백그라운드 처리 시작
    background_tasks.add_task(process_slide, slide_id, save_path)

    return {"slide_id": slide_id, "message": "업로드 완료, 처리 시작"}


@router.get("/list")
async def list_slides():
    """업로드된 강의자료 전체 목록 — 수강자가 번역본 다운로드용으로 조회"""
    items = []
    for sid, info in slide_status.items():
        translated_pdf = TRANSLATED_DIR / f"{sid}_translated.pdf"
        items.append({
            "slide_id": sid,
            "filename": info.get("filename", f"{sid}.pdf"),
            "status": info.get("status"),
            "total_pages": info.get("total_pages", 0),
            "has_translated": translated_pdf.exists(),
        })
    return {"items": items}


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


@router.get("/translation-status/{slide_id}")
async def get_translation_status(slide_id: str):
    """번역 진행 상태 조회 (VLM 번역은 별도 진행)"""
    if slide_id not in translation_status:
        return {
            "slide_id": slide_id,
            "status": "not_started",
            "total_pages": 0,
            "translated_pages": 0,
            "error": None,
        }

    ts = translation_status[slide_id]
    return {
        "slide_id": slide_id,
        "status": ts["status"],
        "total_pages": ts["total_pages"],
        "translated_pages": ts["translated_pages"],
        "error": ts["error"],
    }


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
    filename = slide_status.get(slide_id, {}).get("filename")
    return {"pages": pages, "filename": filename}


@router.get("/image/{slide_id}/{page_number}")
async def get_image(slide_id: str, page_number: int, translated: bool = False):
    """
    슬라이드 이미지 반환
    - translated=false: 원본 이미지
    - translated=true: 번역된 이미지
    """
    if translated:
        image_path = TRANSLATED_DIR / f"{slide_id}_{page_number}.png"
        # 번역본 없으면 원본 반환
        if not image_path.exists():
            image_path = IMAGES_DIR / f"{slide_id}_{page_number}.png"
    else:
        image_path = IMAGES_DIR / f"{slide_id}_{page_number}.png"

    if not image_path.exists():
        raise HTTPException(404, "이미지를 찾을 수 없습니다")
    return FileResponse(image_path, media_type="image/png")


_FORBIDDEN_FILENAME_CHARS = set(r'\/:*?"<>|')


def _safe_filename_stem(title: Optional[str], fallback_stem: str) -> str:
    """다운로드용 파일명(확장자 제외) 생성 — title을 우선하되 공격 가능한 문자 제거."""
    if not title:
        return fallback_stem
    cleaned = "".join(c for c in title if c not in _FORBIDDEN_FILENAME_CHARS).strip()
    # 제어 문자 제거
    cleaned = "".join(c for c in cleaned if c.isprintable())
    if not cleaned:
        return fallback_stem
    return cleaned[:100]


@router.get("/download/{slide_id}")
async def download_slide(
    slide_id: str,
    type: str = "original",
    title: Optional[str] = None,
):
    """
    슬라이드 PDF 다운로드
    - type=original: 원본 PDF
    - type=translated: 번역본 PDF
    - title (optional): 강의 제목. 지정 시 파일명에 사용.
    """
    stored_title = slide_status.get(slide_id, {}).get("filename", "")
    fallback_stem_base = (
        _safe_filename_stem(stored_title.removesuffix(".pdf"), f"강의자료_{slide_id}")
        if stored_title
        else f"강의자료_{slide_id}"
    )
    stem = _safe_filename_stem(title, fallback_stem_base)

    if type == "original":
        pdf_path = UPLOAD_DIR / f"{slide_id}.pdf"
        if not pdf_path.exists():
            raise HTTPException(404, "PDF 파일을 찾을 수 없습니다")
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=f"{stem}.pdf",
        )
    elif type == "translated":
        translated_pdf_path = TRANSLATED_DIR / f"{slide_id}_translated.pdf"
        if translated_pdf_path.exists():
            return FileResponse(
                translated_pdf_path,
                media_type="application/pdf",
                filename=f"{stem}_번역본.pdf",
            )
        else:
            raise HTTPException(404, "번역본 PDF가 아직 생성되지 않았습니다. 처리 완료 후 다시 시도하세요.")
    else:
        raise HTTPException(400, "type은 'original' 또는 'translated'여야 합니다")


async def process_slide(slide_id: str, pdf_path: Path):
    """
    슬라이드 전처리 (백그라운드)
    PDF → 이미지 저장 → VLM 번역 → 완료
    """
    import shutil

    try:
        slide_status[slide_id]["status"] = "processing"

        # PDF를 이미지로 변환
        images = await asyncio.to_thread(pdf_to_images, pdf_path)
        total_pages = len(images)
        slide_status[slide_id]["total_pages"] = total_pages

        slide_data[slide_id] = []

        # VLM 번역 함수 임포트
        try:
            from translate_slide_v3 import translate_slide
            vlm_available = True
            print(f"[Slides] VLM 번역 모듈 로드 완료")
        except ImportError as e:
            vlm_available = False
            print(f"[Slides] VLM 번역 모듈 없음 (원본만 저장): {e}")

        # 각 페이지 처리
        for i, image_bytes in enumerate(images):
            # 원본 이미지 저장
            image_path = IMAGES_DIR / f"{slide_id}_{i}.png"
            with open(image_path, "wb") as f:
                f.write(image_bytes)
            print(f"[Slides] {slide_id} 페이지 {i + 1}/{total_pages} 원본 저장")

            # VLM 번역
            translated_path = TRANSLATED_DIR / f"{slide_id}_{i}.png"
            overlay_items = []

            if vlm_available:
                try:
                    print(f"[Slides] {slide_id} 페이지 {i + 1}/{total_pages} VLM 번역 중...")
                    result = await asyncio.to_thread(
                        translate_slide,
                        str(image_path),
                        str(translated_path)
                    )

                    if result["success"]:
                        for region in result.get("regions", []):
                            if not region.get("skip_translate", False):
                                overlay_items.append({
                                    "original": region.get("ocr_text", ""),
                                    "translated": region.get("english", ""),
                                    "bbox": region.get("bbox"),
                                    "confidence": region.get("confidence", 0.9),
                                })
                        print(f"[Slides] {slide_id} 페이지 {i + 1}/{total_pages} 번역 완료!")
                    else:
                        print(f"[Slides] {slide_id} 페이지 {i + 1} 번역 실패: {result.get('error')}")
                        shutil.copy(image_path, translated_path)
                except Exception as e:
                    print(f"[Slides] VLM 번역 예외 (원본 사용): {e}")
                    shutil.copy(image_path, translated_path)
            else:
                shutil.copy(image_path, translated_path)

            slide_data[slide_id].append({
                "page_number": i,
                "ocr_text": None,
                "overlay_items": overlay_items,
                "has_translation": translated_path.exists(),
            })

            slide_status[slide_id]["processed_pages"] = i + 1

        # 번역된 이미지들을 PDF로 변환
        print(f"[Slides] {slide_id} 번역 PDF 생성 중...")
        try:
            from PIL import Image
            translated_images = []
            for i in range(total_pages):
                img_path = TRANSLATED_DIR / f"{slide_id}_{i}.png"
                if img_path.exists():
                    img = Image.open(img_path).convert("RGB")
                    translated_images.append(img)

            if translated_images:
                pdf_path = TRANSLATED_DIR / f"{slide_id}_translated.pdf"
                translated_images[0].save(
                    pdf_path,
                    save_all=True,
                    append_images=translated_images[1:] if len(translated_images) > 1 else [],
                    resolution=150.0
                )
                print(f"[Slides] {slide_id} 번역 PDF 저장: {pdf_path}")
        except Exception as e:
            print(f"[Slides] {slide_id} PDF 생성 실패: {e}")

        slide_status[slide_id]["status"] = "completed"
        print(f"[Slides] {slide_id} 전처리 완료! (번역 포함)")

    except Exception as e:
        slide_status[slide_id]["status"] = "failed"
        slide_status[slide_id]["error"] = str(e)
        print(f"[Slides] {slide_id} 처리 실패: {e}")


async def process_translation(slide_id: str):
    """
    VLM 번역 처리 (별도 백그라운드 태스크)
    원본 이미지를 하나씩 번역하여 translated 폴더에 저장
    """
    import shutil

    try:
        translation_status[slide_id]["status"] = "translating"
        total_pages = translation_status[slide_id]["total_pages"]

        # VLM 번역 함수 임포트
        try:
            from translate_slide_v3 import translate_slide
            vlm_available = True
            print(f"[Translation] VLM 모듈 로드 완료")
        except ImportError as e:
            vlm_available = False
            print(f"[Translation] VLM 모듈 없음: {e}")
            # VLM 없으면 원본 복사만
            for i in range(total_pages):
                src = IMAGES_DIR / f"{slide_id}_{i}.png"
                dst = TRANSLATED_DIR / f"{slide_id}_{i}.png"
                if src.exists():
                    shutil.copy(src, dst)
            translation_status[slide_id]["status"] = "completed"
            translation_status[slide_id]["translated_pages"] = total_pages
            return

        # 각 페이지 번역
        for i in range(total_pages):
            image_path = IMAGES_DIR / f"{slide_id}_{i}.png"
            translated_path = TRANSLATED_DIR / f"{slide_id}_{i}.png"

            if not image_path.exists():
                print(f"[Translation] {slide_id} 페이지 {i + 1} 원본 없음, 스킵")
                continue

            try:
                print(f"[Translation] {slide_id} 페이지 {i + 1}/{total_pages} 번역 시작...")
                result = await asyncio.to_thread(
                    translate_slide,
                    str(image_path),
                    str(translated_path)
                )

                if result["success"]:
                    # overlay_items 업데이트
                    overlay_items = []
                    for region in result.get("regions", []):
                        if not region.get("skip_translate", False):
                            overlay_items.append({
                                "original": region.get("ocr_text", ""),
                                "translated": region.get("english", ""),
                                "bbox": region.get("bbox"),
                                "confidence": region.get("confidence", 0.9),
                            })

                    if slide_id in slide_data and i < len(slide_data[slide_id]):
                        slide_data[slide_id][i]["overlay_items"] = overlay_items
                        slide_data[slide_id][i]["has_translation"] = True

                    print(f"[Translation] {slide_id} 페이지 {i + 1}/{total_pages} 번역 완료!")
                else:
                    print(f"[Translation] {slide_id} 페이지 {i + 1} 번역 실패: {result.get('error')}")
                    shutil.copy(image_path, translated_path)

            except Exception as e:
                print(f"[Translation] {slide_id} 페이지 {i + 1} 예외: {e}")
                shutil.copy(image_path, translated_path)

            translation_status[slide_id]["translated_pages"] = i + 1

        translation_status[slide_id]["status"] = "completed"
        print(f"[Translation] {slide_id} 전체 번역 완료!")

    except Exception as e:
        translation_status[slide_id]["status"] = "failed"
        translation_status[slide_id]["error"] = str(e)
        print(f"[Translation] {slide_id} 번역 실패: {e}")


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


