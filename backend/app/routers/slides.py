"""
슬라이드 라우터
PDF 업로드 및 전처리 (OCR + VLM 번역)
"""
import asyncio
import shutil
import sys
import time
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
_ocr_service = None


def set_ocr_service(service):
    global _ocr_service
    _ocr_service = service


# 슬라이드 저장 경로
UPLOAD_DIR = _REPO_DIR / "uploads" / "slides"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 이미지 저장 경로 (원본)
IMAGES_DIR = _REPO_DIR / "uploads" / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# 번역된 이미지 저장 경로
TRANSLATED_DIR = _REPO_DIR / "uploads" / "translated"
TRANSLATED_DIR.mkdir(parents=True, exist_ok=True)

# 처리 상태 저장 (메모리, 실제 서비스에서는 Redis 사용 권장)
slide_status: dict[str, dict] = {}
slide_data: dict[str, list[dict]] = {}


class SlideStatus(BaseModel):
    slide_id: str
    status: str  # pending, processing, completed, failed
    total_pages: int
    processed_pages: int
    stage: str  # pending, ocr, translate, bundling, completed, failed
    stage_current: int
    stage_total: int
    eta_seconds: Optional[float] = None  # 페이지 완료 시점에 갱신되는 앵커 — /status 응답 시점까지 흐른 시간만큼 감산됨
    error: Optional[str] = None


_BASELINE_SECONDS_PER_PAGE = {
    "ocr": 15.0,       # Surya OCR 한 장 처리 추정치 (초) — 실측보다 약간 여유롭게
    "translate":50.0,  # Qwen3-VL 한 장 번역 추정치 (4bit GPU) — 실측보다 여유롭게 잡아 "잠시만" 시간 단축
}
_BUNDLING_BASELINE = 3.0  # PDF 묶기 짧은 고정값


def _unified_remaining(stage: str, total: int, current: int, avg: float, elapsed_on_current: float) -> Optional[float]:
    """현재 단계 + 후속 단계의 남은 작업 시간을 합산.
    진행 중 페이지가 baseline을 초과하면 ETA가 자연스럽게 0까지 떨어진다 (overrun floor 없음).
    번역 마지막 페이지 overrun 시점에는 bundling baseline도 빼서 ETA=0 → '잠시만 기다려주세요'가 안정적으로 유지되도록."""
    pages_remaining = max(0, total - current)

    def _in_progress(per_page: float) -> float:
        return max(0.0, per_page - elapsed_on_current)

    if stage == "ocr":
        per_page = avg if avg > 0 else _BASELINE_SECONDS_PER_PAGE["ocr"]
        ocr_remaining = (_in_progress(per_page) + per_page * (pages_remaining - 1)) if pages_remaining > 0 else 0.0
        translate_remaining = _BASELINE_SECONDS_PER_PAGE["translate"] * total  # 아직 시작 안 한 단계
        return ocr_remaining + translate_remaining + _BUNDLING_BASELINE

    if stage == "translate":
        per_page = avg if avg > 0 else _BASELINE_SECONDS_PER_PAGE["translate"]
        if pages_remaining > 0:
            ip = _in_progress(per_page)
            translate_remaining = ip + per_page * (pages_remaining - 1)
        else:
            translate_remaining = 0.0
        # bundling baseline은 더하지 않음 — 더하면 카운트다운이 3초에서 잠시만으로 점프(거의 다 됨/2초/1초 스킵)
        # bundling은 어차피 짧고(~3초) bundling 단계로 전환되면 그 안에서 따로 카운트다운됨
        return translate_remaining

    if stage == "bundling":
        return max(0.0, _BUNDLING_BASELINE - elapsed_on_current)

    return None


def _compute_eta_seconds(s: dict, now: float) -> Optional[float]:
    """현재 상태로부터 ETA 즉시 계산 — /status 응답 시점에 호출.
    anchor 캐싱 안 함 → 현재 페이지가 baseline 초과해도 ETA가 0으로 떨어지지 않음."""
    stage = s.get("stage", "pending")
    if stage in ("pending", "completed", "failed"):
        return None

    total = s.get("stage_total", 0)
    current = s.get("stage_current", 0)
    avg = s.get("avg_page_duration", 0.0)

    if stage == "bundling":
        elapsed = max(0.0, now - s.get("stage_started_at", now))
    else:
        elapsed = max(0.0, now - s.get("last_page_at", now))

    return _unified_remaining(stage, total, current, avg, elapsed)


def _set_stage(slide_id: str, stage: str, total: int) -> None:
    """현재 처리 단계 전환 — 카운터/타이머 리셋. avg는 단계마다 리셋(다른 작업이라 평균 의미 다름).
    ETA는 /status 응답 시점에 _compute_eta_seconds 가 즉시 계산하므로 따로 저장 안 함."""
    s = slide_status.get(slide_id)
    if s is None:
        return
    now = time.time()
    s["stage"] = stage
    s["stage_current"] = 0
    s["stage_total"] = total
    s["stage_started_at"] = now
    s["last_page_at"] = now
    s["avg_page_duration"] = 0.0


def _page_completed(slide_id: str, current: int) -> None:
    """페이지 완료 시점에 평균 갱신.
    첫 페이지는 baseline과 실측치를 5:5로 블렌딩, 이후는 느린 EMA(alpha=0.25)."""
    s = slide_status.get(slide_id)
    if s is None:
        return
    now = time.time()
    s["stage_current"] = current

    duration = max(0.0, now - s.get("last_page_at", now))
    s["last_page_at"] = now

    stage = s.get("stage", "")
    prev = s.get("avg_page_duration", 0.0)
    if prev == 0.0:
        # 첫 페이지: baseline과 실측치를 절반씩 블렌딩 (실측이 baseline과 크게 어긋나도 점프 절반으로 줄임)
        baseline = _BASELINE_SECONDS_PER_PAGE.get(stage, duration)
        s["avg_page_duration"] = 0.5 * baseline + 0.5 * duration
    else:
        # 두 번째부터는 느린 EMA — 페이지간 편차에 덜 휘둘림
        s["avg_page_duration"] = 0.75 * prev + 0.25 * duration


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
    now = time.time()
    slide_status[slide_id] = {
        "status": "pending",
        "total_pages": 0,
        "processed_pages": 0,
        "stage": "pending",
        "stage_current": 0,
        "stage_total": 0,
        "stage_started_at": now,
        "last_page_at": now,
        "avg_page_duration": 0.0,
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

    # ETA: 현재 상태 + 진행 중 페이지의 elapsed 시간을 반영해 매 응답마다 즉시 계산
    # (anchor 캐싱하면 페이지가 baseline 초과할 때 ETA가 0으로 떨어져버림)
    eta_seconds = _compute_eta_seconds(status, time.time())

    return SlideStatus(
        slide_id=slide_id,
        status=status["status"],
        total_pages=status["total_pages"],
        processed_pages=status["processed_pages"],
        stage=status.get("stage", "pending"),
        stage_current=status.get("stage_current", 0),
        stage_total=status.get("stage_total", 0),
        eta_seconds=eta_seconds,
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
    try:
        slide_status[slide_id]["status"] = "processing"

        # PDF를 이미지로 변환
        images = await asyncio.to_thread(pdf_to_images, pdf_path)
        total_pages = len(images)
        slide_status[slide_id]["total_pages"] = total_pages

        slide_data[slide_id] = []

        # VLM 번역 함수 임포트
        try:
            from translate_slide_v3 import (
                stage_ocr_surya, stage_translate, stage_overlay,
                unload_vlm_model,
                build_glossary_from_ocr_results
            )
            vlm_available = True
            print(f"[Slides] VLM 번역 모듈 로드 완료")
        except ImportError as e:
            vlm_available = False
            print(f"[Slides] VLM 번역 모듈 없음 (원본만 저장): {e}")

        # ========== 1단계: 모든 페이지 원본 저장 + OCR (Surya) ==========
        _set_stage(slide_id, "ocr", total_pages)
        ocr_results = []  # [(image_path, regions), ...]
        for i, image_bytes in enumerate(images):
            image_path = IMAGES_DIR / f"{slide_id}_{i}.png"
            with open(image_path, "wb") as f:
                f.write(image_bytes)
            print(f"[Slides] {slide_id} 페이지 {i + 1}/{total_pages} 원본 저장")

            if vlm_available:
                try:
                    print(f"[Slides] {slide_id} 페이지 {i + 1}/{total_pages} OCR 중...")
                    regions = await asyncio.to_thread(stage_ocr_surya, str(image_path))
                    ocr_results.append((image_path, regions))
                except Exception as e:
                    print(f"[Slides] OCR 예외: {e}")
                    ocr_results.append((image_path, None))
            else:
                ocr_results.append((image_path, None))

            _page_completed(slide_id, i + 1)

        # ========== 용어집 빌드 (전체 슬라이드 1회) ==========
        glossary = {}
        if vlm_available:
            try:
                # 강의 제목: 첫 페이지 첫 번째 텍스트 또는 기본값
                lecture_title = "Lecture"
                if ocr_results and ocr_results[0][1]:
                    first_text = ocr_results[0][1][0].get("ocr_text", "")
                    if first_text:
                        lecture_title = first_text[:50]  # 최대 50자
                glossary = await asyncio.to_thread(
                    build_glossary_from_ocr_results, ocr_results, lecture_title
                )
            except Exception as e:
                print(f"[Slides] 용어집 빌드 실패 (무시): {e}")

        # ========== 2단계: 모든 페이지 번역 (VLM) ==========
        _set_stage(slide_id, "translate", total_pages)
        for i, (image_path, regions) in enumerate(ocr_results):
            translated_path = TRANSLATED_DIR / f"{slide_id}_{i}.png"
            overlay_items = []

            if vlm_available and regions is not None:
                try:
                    print(f"[Slides] {slide_id} 페이지 {i + 1}/{total_pages} VLM 번역 중...")
                    regions = await asyncio.to_thread(stage_translate, str(image_path), regions, glossary)
                    await asyncio.to_thread(stage_overlay, str(image_path), regions, str(translated_path))

                    for region in regions:
                        if not region.get("skip_translate", False):
                            overlay_items.append({
                                "original": region.get("ocr_text", ""),
                                "translated": region.get("english", ""),
                                "bbox": region.get("bbox"),
                                "confidence": region.get("confidence", 0.9),
                            })
                    print(f"[Slides] {slide_id} 페이지 {i + 1}/{total_pages} VLM 번역 완료!")
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
            _page_completed(slide_id, i + 1)

        # VLM 모델 언로드 (GPU 메모리 해제 — ASR과 VRAM 경합 방지)
        if vlm_available:
            print(f"[Slides] VLM 번역 완료, 모델 언로드...")
            await asyncio.to_thread(unload_vlm_model)

        # 번역된 이미지들을 PDF로 변환
        _set_stage(slide_id, "bundling", 0)
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
                    format="PDF",
                    save_all=True,
                    append_images=translated_images[1:] if len(translated_images) > 1 else [],
                    resolution=150.0
                )
                print(f"[Slides] {slide_id} 번역 PDF 저장: {pdf_path}")

                # 이미지 리소스 정리
                for img in translated_images:
                    img.close()
        except Exception as e:
            print(f"[Slides] {slide_id} PDF 생성 실패: {e}")

        slide_status[slide_id]["status"] = "completed"
        slide_status[slide_id]["stage"] = "completed"
        print(f"[Slides] {slide_id} 전처리 완료! (번역 포함)")

    except Exception as e:
        slide_status[slide_id]["status"] = "failed"
        slide_status[slide_id]["stage"] = "failed"
        slide_status[slide_id]["error"] = str(e)
        print(f"[Slides] {slide_id} 처리 실패: {e}")
        # 예외 발생 시에도 VLM 언로드 보장
        try:
            from translate_slide_v3 import unload_vlm_model
            await asyncio.to_thread(unload_vlm_model)
        except Exception:
            pass


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


