"""
슬라이드 라우터
PDF 업로드 및 전처리 (OCR + VLM 번역)
"""
import asyncio
import hashlib
import json
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Query
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

# 라이브러리 메타데이터 저장 경로 — PDF 디렉토리와 분리해서 깔끔하게 관리
LIBRARY_DIR = _REPO_DIR / "uploads" / "library"
LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

# 처리 상태 저장 (메모리, 실제 서비스에서는 Redis 사용 권장)
slide_status: dict[str, dict] = {}
slide_data: dict[str, list[dict]] = {}
# 슬라이드별 한↔영 도메인 용어집 (실시간 NMT 환각 억제 — ws.py 가 lecture_start 시 가져감)
slide_glossary: dict[str, dict[str, str]] = {}

# slide_id 발급 전 취소된 client_token 보류 — {token: expires_at_monotonic}.
# 업로드 응답이 도착해 add_task 직전에 검사하면 즉시 폐기. 응답이 안 오는 케이스를 위해 TTL 청소.
_PENDING_CANCEL_TOKEN_TTL = 300.0  # 5분
pending_cancel_tokens: dict[str, float] = {}


def _gc_pending_cancel_tokens() -> None:
    """만료된 보류 토큰 제거 — 호출 시점마다 한 번씩 청소."""
    now = time.monotonic()
    expired = [t for t, exp in pending_cancel_tokens.items() if exp <= now]
    for t in expired:
        pending_cancel_tokens.pop(t, None)


def _consume_pending_cancel_token(token: Optional[str]) -> bool:
    """토큰이 보류 셋에 있으면 제거하고 True. 부수효과로 만료 청소도 수행."""
    _gc_pending_cancel_tokens()
    if not token:
        return False
    return pending_cancel_tokens.pop(token, None) is not None


def _is_cancelled(slide_id: str) -> bool:
    return slide_status.get(slide_id, {}).get("cancelled", False)


async def _cleanup_cancelled(slide_id: str) -> None:
    """취소된 슬라이드 정리 — VLM 언로드 + 파일/메모리/dedup 맵 일체 제거.
    save_metadata() 는 호출 안 되므로 meta.json 은 자연히 생성되지 않음."""
    try:
        from app.services.slide_translation.image_pipeline import unload_vlm_model
        await asyncio.to_thread(unload_vlm_model)
    except Exception as e:
        print(f"[Slides] {slide_id} 취소 정리 중 VLM 언로드 실패 (무시): {e}")
    ch = slide_status.get(slide_id, {}).get("content_hash")
    token = slide_status.get(slide_id, {}).get("client_token")
    _delete_slide_files(slide_id)
    if ch:
        _hash_to_slide_id.pop(ch, None)
    if token:
        pending_cancel_tokens.pop(token, None)
    print(f"[Slides] {slide_id} 취소 정리 완료")


def get_slide_glossary(slide_id: str) -> dict[str, str]:
    """주어진 slide_id 의 도메인 용어집 ({한글: 영어}) 반환. 없으면 빈 dict."""
    return slide_glossary.get(slide_id, {})


def _recover_glossary_from_cache(meta: dict) -> dict[str, str]:
    """metadata 에 glossary 필드가 없는 구버전 처리분 자료를 위한 자동 복원.
    page_data 의 첫 overlay_items 텍스트(=lecture_title 후보)로 glossary 캐시 디렉토리를
    탐색해 매칭되는 캐시가 있으면 그 terms 를 반환. 못 찾으면 빈 dict.
    """
    page_data = meta.get("page_data") or []
    if not page_data:
        return {}
    first_overlay = page_data[0].get("overlay_items") or []
    if not first_overlay:
        return {}
    candidate_title = (first_overlay[0].get("original") or "")[:50]
    if not candidate_title:
        return {}

    try:
        from app.services.glossary_builder import GLOSSARY_DIR
    except Exception:
        return {}

    if not GLOSSARY_DIR.exists():
        return {}

    for cache_file in GLOSSARY_DIR.glob("glossary_*.json"):
        try:
            with open(cache_file, encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("lecture_title", "") == candidate_title:
                return cache.get("terms", {}) or {}
        except Exception:
            continue
    return {}

# 콘텐츠 해시(SHA256) → 기존 slide_id 매핑 — 동일 파일 재업로드 dedup용
_hash_to_slide_id: dict[str, str] = {}


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
    "translate":50.0,  # Qwen2.5-VL 한 장 번역 추정치 (4bit GPU) — 실측보다 여유롭게 잡아 "잠시만" 시간 단축
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


# ─── 라이브러리 (영속성) 모델 ───────────────────────────────────────────────
class BatchDeleteRequest(BaseModel):
    slide_ids: list[str]


class BatchDeleteFailure(BaseModel):
    slide_id: str
    reason: str


class BatchDeleteResponse(BaseModel):
    deleted: list[str]
    failed: list[BatchDeleteFailure]


class RenameSlideRequest(BaseModel):
    filename: str


class RenameSlideResponse(BaseModel):
    slide_id: str
    filename: str


# ─── 메타데이터 저장 / 라이브러리 초기화 ─────────────────────────────────────
def _meta_path(slide_id: str) -> Path:
    return LIBRARY_DIR / f"{slide_id}.meta.json"


def save_metadata(slide_id: str) -> None:
    """슬라이드 처리 완료 시 메타데이터를 JSON 파일로 저장 — 서버 재시작 후에도 라이브러리 유지."""
    s = slide_status.get(slide_id)
    if s is None:
        return
    meta = {
        "slide_id": slide_id,
        "filename": s.get("filename", f"{slide_id}.pdf"),
        # 기존에 저장된 uploaded_at이 있으면 유지, 없으면 현재 시각
        "uploaded_at": s.get("uploaded_at") or datetime.now().isoformat(timespec="seconds"),
        "total_pages": s.get("total_pages", 0),
        "status": s.get("status", "completed"),
        "content_hash": s.get("content_hash"),  # 재업로드 dedup용 (없을 수도 있음 — migrate된 레거시)
        "last_page": s.get("last_page", 1),  # 마지막 본 페이지 (1-indexed) — 다음 로드 시 그 페이지부터 시작
        "page_data": slide_data.get(slide_id, []),
        # 실시간 NMT 환각 억제용 도메인 용어집 — 슬라이드 재로드 시 복원됨
        "glossary": slide_glossary.get(slide_id, {}),
    }
    try:
        with open(_meta_path(slide_id), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        # uploaded_at을 메모리에도 동기화 (이후 라이브러리 응답에서 일관성 유지)
        s["uploaded_at"] = meta["uploaded_at"]
        # 해시 → ID 맵 갱신 (다음 동일 파일 업로드 시 dedup 동작하도록)
        ch = meta.get("content_hash")
        if ch:
            _hash_to_slide_id[ch] = slide_id
    except Exception as e:
        print(f"[Slides] 메타데이터 저장 실패: {slide_id} - {e}")


def update_last_page(slide_id: str, page: int) -> None:
    """슬라이드의 마지막 본 페이지를 메타에 저장 — 다음 /load 시 해당 페이지부터 시작.
    페이지 변경 시마다 호출됨 (작은 파일이라 부담 적음)."""
    if page < 1:
        return
    s = slide_status.get(slide_id)
    if s is not None:
        s["last_page"] = page
    meta_path = _meta_path(slide_id)
    if not meta_path.exists():
        return  # 처리 안 끝난 슬라이드면 메타 없음 — 스킵
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["last_page"] = page
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Slides] last_page 저장 실패: {slide_id} - {e}")


def init_slide_library() -> None:
    """서버 시작 시 기존 메타파일 스캔 → 메모리 목록 복원 (page_data는 load 시 지연 로드)."""
    print("[Slides] 강의자료 라이브러리 초기화...")
    count = 0
    for meta_file in LIBRARY_DIR.glob("*.meta.json"):
        try:
            with open(meta_file, encoding="utf-8") as f:
                meta = json.load(f)
            sid = meta["slide_id"]
            slide_status[sid] = {
                "status": meta.get("status", "completed"),
                "total_pages": meta.get("total_pages", 0),
                "processed_pages": meta.get("total_pages", 0),
                "stage": "completed" if meta.get("status") == "completed" else meta.get("status", "pending"),
                "stage_current": meta.get("total_pages", 0),
                "stage_total": meta.get("total_pages", 0),
                "stage_started_at": time.time(),
                "last_page_at": time.time(),
                "avg_page_duration": 0.0,
                "error": None,
                "filename": meta.get("filename", f"{sid}.pdf"),
                "uploaded_at": meta.get("uploaded_at"),
                "content_hash": meta.get("content_hash"),
                "last_page": meta.get("last_page", 1),
            }
            # 해시 맵 복원 (재업로드 dedup용)
            ch = meta.get("content_hash")
            if ch:
                _hash_to_slide_id[ch] = sid
            count += 1
        except Exception as e:
            print(f"[Slides] 메타 로드 실패: {meta_file.name} - {e}")
    print(f"[Slides] {count}개 강의자료 발견")


def _reconstruct_page_data(slide_id: str, total_pages: int) -> list[dict]:
    """디스크에 있는 이미지/번역본 파일 기준으로 최소 page_data를 재구성.
    OCR overlay 정보는 손실되므로 빈 배열로 채움 (강의자료 보기/번역본 다운로드는 정상 동작)."""
    return [
        {
            "page_number": i,
            "ocr_text": None,
            "overlay_items": [],
            "has_translation": (TRANSLATED_DIR / f"{slide_id}_{i}.png").exists(),
        }
        for i in range(total_pages)
    ]


def migrate_existing_slides() -> None:
    """meta.json이 없는 기존 PDF에 대해 1회성 메타 생성 (이미지 파일로 페이지수 추정 + page_data 재구성)."""
    migrated = 0
    for pdf in UPLOAD_DIR.glob("*.pdf"):
        sid = pdf.stem
        if _meta_path(sid).exists():
            continue
        page_files = list(IMAGES_DIR.glob(f"{sid}_*.png"))
        if not page_files:
            continue
        total_pages = len(page_files)
        meta = {
            "slide_id": sid,
            "filename": f"{sid}.pdf",
            "uploaded_at": datetime.fromtimestamp(pdf.stat().st_mtime).isoformat(timespec="seconds"),
            "total_pages": total_pages,
            "status": "completed",
            "page_data": _reconstruct_page_data(sid, total_pages),
        }
        try:
            with open(_meta_path(sid), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            migrated += 1
            print(f"[Migration] {sid} 메타 생성")
        except Exception as e:
            print(f"[Migration] {sid} 메타 생성 실패: {e}")
    if migrated:
        print(f"[Migration] {migrated}개 기존 슬라이드 마이그레이션 완료")


def repair_legacy_metadata() -> None:
    """이전에 마이그레이션된 meta.json 중 page_data가 비어있는 항목 보정.
    (이전 버전의 마이그레이션은 page_data를 비어둬서 슬라이드 로드 시 0페이지로 표시됐음)"""
    repaired = 0
    for meta_file in LIBRARY_DIR.glob("*.meta.json"):
        try:
            with open(meta_file, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue
        page_data = meta.get("page_data") or []
        total_pages = meta.get("total_pages", 0)
        if page_data or total_pages <= 0:
            continue
        sid = meta.get("slide_id") or meta_file.stem.removesuffix(".meta")
        meta["page_data"] = _reconstruct_page_data(sid, total_pages)
        try:
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            repaired += 1
            print(f"[Repair] {sid} page_data 재구성")
        except Exception as e:
            print(f"[Repair] {sid} 보정 실패: {e}")
    if repaired:
        print(f"[Repair] {repaired}개 메타 파일 page_data 보정 완료")


# 모듈 로드 시 1회 실행 — 마이그레이션 → 레거시 보정 → 라이브러리 초기화
migrate_existing_slides()
repair_legacy_metadata()
init_slide_library()


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
    client_token: Optional[str] = Form(None),
):
    """
    PDF 슬라이드 업로드
    백그라운드에서 OCR + 번역 전처리 수행
    client_token: 응답 전 abort 케이스에서 프론트가 보낸 보류 토큰. 매칭되면 즉시 폐기.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "PDF 파일만 업로드 가능합니다")

    content = await file.read()

    # 동일 파일 재업로드 dedup — SHA256 해시 일치 시 기존 slide_id 재사용 (처리 스킵)
    content_hash = hashlib.sha256(content).hexdigest()
    existing_id = _hash_to_slide_id.get(content_hash)
    if existing_id and (UPLOAD_DIR / f"{existing_id}.pdf").exists():
        # 재사용 경로에서도 토큰이 있으면 그냥 소비 — 어차피 추가 처리는 없으니 정리만
        _consume_pending_cancel_token(client_token)
        print(f"[Slides] 동일 파일 재업로드 감지 → 기존 slide_id 재사용: {existing_id} (filename={file.filename})")
        return {
            "slide_id": existing_id,
            "message": "동일 파일이 이미 처리되어 있어 재사용합니다",
            "reused": True,
            "cancelled": False,
        }

    # 고유 ID 생성
    slide_id = str(uuid.uuid4())[:8]

    # 파일 저장
    save_path = UPLOAD_DIR / f"{slide_id}.pdf"
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
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        "content_hash": content_hash,
        "cancelled": False,
        "client_token": client_token,
    }

    # 응답 전 취소된 케이스 — 보류 토큰 매칭 시 add_task 생략 + 즉시 정리
    if _consume_pending_cancel_token(client_token):
        print(f"[Slides] {slide_id} 업로드 응답 전 취소 토큰 매칭 → 처리 스킵")
        _delete_slide_files(slide_id)
        return {
            "slide_id": slide_id,
            "message": "업로드 직후 취소 신호가 있어 처리하지 않았습니다",
            "reused": False,
            "cancelled": True,
        }

    # 백그라운드 처리 시작
    background_tasks.add_task(process_slide, slide_id, save_path)

    return {"slide_id": slide_id, "message": "업로드 완료, 처리 시작", "reused": False, "cancelled": False}


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
    # 메모리에 없으면 디스크 meta.json에서 lazy-load — 재시작 후 /load 안 거치고 바로 /pages 호출 시 안전망
    if slide_id not in slide_data:
        meta_path = _meta_path(slide_id)
        if meta_path.exists():
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                slide_data[slide_id] = meta.get("page_data", [])
            except Exception as e:
                print(f"[Slides] /pages lazy-load 실패: {slide_id} - {e}")
                raise HTTPException(404, "슬라이드를 찾을 수 없습니다")
        else:
            raise HTTPException(404, "슬라이드를 찾을 수 없습니다")

    pages = [
        PageData(
            pageNumber=page.get("page_number", idx) + 1,  # 1-indexed for frontend
            imageUrl=f"/slides/image/{slide_id}/{page.get('page_number', idx)}",
            ocrText=page.get("ocr_text"),
        )
        for idx, page in enumerate(slide_data[slide_id])
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


# ─── 라이브러리 / 로드 / 삭제 엔드포인트 ─────────────────────────────────────
@router.get("/library")
async def get_library(sort: str = Query("recent", pattern="^(recent|name|size)$")):
    """저장된 강의자료 목록 (파일 기반, 서버 재시작 후에도 유지)."""
    items = []
    for meta_file in LIBRARY_DIR.glob("*.meta.json"):
        try:
            with open(meta_file, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as e:
            print(f"[Slides] 메타 읽기 실패: {meta_file.name} - {e}")
            continue
        translated_pdf = TRANSLATED_DIR / f"{meta['slide_id']}_translated.pdf"
        # 원본 PDF 크기 — 라이브러리 정렬/표시용. 파일이 없거나 stat 실패해도 0으로 폴백.
        pdf_path = UPLOAD_DIR / f"{meta['slide_id']}.pdf"
        try:
            file_size = pdf_path.stat().st_size if pdf_path.exists() else 0
        except OSError:
            file_size = 0
        items.append({
            "slide_id": meta["slide_id"],
            "filename": meta.get("filename", f"{meta['slide_id']}.pdf"),
            "uploaded_at": meta.get("uploaded_at", ""),
            "total_pages": meta.get("total_pages", 0),
            "status": meta.get("status", "completed"),
            "has_translated": translated_pdf.exists(),
            "file_size": file_size,
        })

    if sort == "name":
        items.sort(key=lambda x: x["filename"].lower())
    elif sort == "size":
        items.sort(key=lambda x: x["file_size"], reverse=True)
    else:
        items.sort(key=lambda x: x["uploaded_at"], reverse=True)

    return {"items": items}


@router.post("/load/{slide_id}")
async def load_slide(slide_id: str):
    """저장된 강의자료를 메모리에 로드 (강의 시작 전 카드 클릭 시 호출)."""
    meta_path = _meta_path(slide_id)
    if not meta_path.exists():
        raise HTTPException(404, "강의자료를 찾을 수 없습니다")

    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as e:
        raise HTTPException(500, f"메타데이터 읽기 실패: {e}")

    if meta.get("status") != "completed":
        raise HTTPException(400, "처리가 완료되지 않은 강의자료입니다")

    total_pages = meta.get("total_pages", 0)
    page_data = meta.get("page_data") or []
    # 레거시 호환: page_data가 비어있으면 디스크에서 재구성 (overlay 정보는 손실)
    if not page_data and total_pages > 0:
        page_data = _reconstruct_page_data(slide_id, total_pages)

    # 메모리에 로드
    slide_status[slide_id] = {
        "status": meta["status"],
        "total_pages": total_pages,
        "processed_pages": total_pages,
        "stage": "completed",
        "stage_current": total_pages,
        "stage_total": total_pages,
        "stage_started_at": time.time(),
        "last_page_at": time.time(),
        "avg_page_duration": 0.0,
        "error": None,
        "filename": meta.get("filename", f"{slide_id}.pdf"),
        "uploaded_at": meta.get("uploaded_at"),
        "content_hash": meta.get("content_hash"),
        "last_page": meta.get("last_page", 1),
    }
    slide_data[slide_id] = page_data
    # 메타에 보존된 도메인 용어집 복원 (실시간 NMT 가 사용)
    saved_glossary = meta.get("glossary") or {}
    if not saved_glossary:
        # 구버전 처리분(이번 변경 이전) 자동 복원: glossary 캐시 디렉토리에서 lecture_title 매칭
        recovered = _recover_glossary_from_cache(meta)
        if recovered:
            saved_glossary = recovered
            # metadata 에 보강 저장 → 다음 로드 시엔 캐시 탐색 안 해도 됨
            try:
                meta["glossary"] = recovered
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
                print(f"[Slides] {slide_id} 용어집 자동 복원: {len(recovered)}개 (캐시 매칭 → metadata 보강)")
            except Exception as e:
                print(f"[Slides] {slide_id} 용어집 복원은 됐으나 metadata 저장 실패 (무시): {e}")
    if saved_glossary:
        slide_glossary[slide_id] = saved_glossary
        if meta.get("glossary"):
            print(f"[Slides] {slide_id} 용어집 복원: {len(saved_glossary)}개")

    return {
        "slide_id": slide_id,
        "message": "강의자료 로드 완료",
        "total_pages": total_pages,
        "last_page": meta.get("last_page", 1),
    }


def _delete_slide_files(slide_id: str, clear_memory: bool = True) -> list[str]:
    """단일 슬라이드의 모든 관련 파일/메모리 정리.

    Args:
        slide_id: 슬라이드 ID
        clear_memory: True면 slide_status/data/glossary도 삭제 (기본값)
                      False면 파일만 삭제 (취소 시 cancelled 플래그 유지용)

    Returns:
        삭제된 항목 종류 리스트 (없으면 빈 리스트)
    """
    deleted: list[str] = []
    skipped: list[str] = []
    print(f"[Slides] _delete_slide_files 시작: {slide_id} (clear_memory={clear_memory})")

    pdf_path = UPLOAD_DIR / f"{slide_id}.pdf"
    if pdf_path.exists():
        try:
            pdf_path.unlink()
            deleted.append("pdf")
            print(f"  삭제: {pdf_path}")
        except PermissionError:
            skipped.append("pdf (사용 중)")
            print(f"  스킵 (사용 중): {pdf_path}")
    else:
        print(f"  없음: {pdf_path}")

    meta_p = _meta_path(slide_id)
    if meta_p.exists():
        try:
            meta_p.unlink()
            deleted.append("meta")
            print(f"  삭제: {meta_p}")
        except PermissionError:
            skipped.append("meta (사용 중)")

    image_files = list(IMAGES_DIR.glob(f"{slide_id}_*.png"))
    img_deleted = 0
    for img in image_files:
        try:
            img.unlink()
            img_deleted += 1
        except PermissionError:
            pass
    if img_deleted:
        deleted.append("images")
        print(f"  삭제: images {img_deleted}개")

    translated_imgs = list(TRANSLATED_DIR.glob(f"{slide_id}_*.png"))
    trans_deleted = 0
    for img in translated_imgs:
        try:
            img.unlink()
            trans_deleted += 1
        except PermissionError:
            pass
    if trans_deleted:
        print(f"  삭제: translated images {trans_deleted}개")

    translated_pdf = TRANSLATED_DIR / f"{slide_id}_translated.pdf"
    if translated_pdf.exists():
        try:
            translated_pdf.unlink()
            deleted.append("translated")
            print(f"  삭제: {translated_pdf}")
        except PermissionError:
            skipped.append("translated_pdf (사용 중)")

    if skipped:
        print(f"[Slides] _delete_slide_files 완료: {slide_id} → 삭제={deleted}, 스킵={skipped}")
    else:
        print(f"[Slides] _delete_slide_files 완료: {slide_id} → {deleted}")

    # clear_memory=False면 여기서 종료 (cancelled 플래그 유지)
    if not clear_memory:
        return deleted

    # 보류 토큰 누수 방지 — slide_status pop 전에 token 추출
    token = slide_status.get(slide_id, {}).get("client_token")
    if token:
        pending_cancel_tokens.pop(token, None)

    # 해시 매핑 삭제 — 동일 파일 재업로드 시 새로 처리되도록
    content_hash = slide_status.get(slide_id, {}).get("content_hash")
    if content_hash:
        _hash_to_slide_id.pop(content_hash, None)

    slide_status.pop(slide_id, None)
    slide_data.pop(slide_id, None)
    slide_glossary.pop(slide_id, None)

    return deleted


@router.post("/cancel-pending")
async def cancel_pending(client_token: str = Query(...)):
    """slide_id 발급 전 취소된 토큰 보류.
    upload_slide 가 응답 직전에 이 토큰을 발견하면 add_task 를 생략하고 즉시 정리."""
    _gc_pending_cancel_tokens()
    pending_cancel_tokens[client_token] = time.monotonic() + _PENDING_CANCEL_TOKEN_TTL
    return {"mode": "pending_token", "client_token": client_token}


@router.post("/{slide_id}/cancel")
async def cancel_slide(slide_id: str):
    """업로드/처리 중인 슬라이드 취소.
    즉시 파일 삭제 + 플래그 set (VLM 블로킹 중에도 파일은 먼저 정리).
    완료/실패된 자료는 noop (라이브러리에 이미 등록됨, 영구삭제는 DELETE 사용)."""
    if slide_id not in slide_status:
        raise HTTPException(404, "슬라이드를 찾을 수 없습니다")
    status = slide_status[slide_id].get("status")
    if status in ("completed", "failed"):
        return {"slide_id": slide_id, "mode": "already_finalized"}

    # 1. 취소 플래그 set (체크포인트에서 감지용)
    slide_status[slide_id]["cancelled"] = True
    print(f"[Slides] {slide_id} 취소 플래그 set (status={status})")

    # 2. 즉시 파일 삭제 (clear_memory=False로 cancelled 플래그 유지)
    #    → 체크포인트에서 _is_cancelled() 감지 가능
    deleted = _delete_slide_files(slide_id, clear_memory=False)
    print(f"[Slides] {slide_id} 즉시 파일 삭제: {deleted}")

    # 3. 해시 매핑은 삭제 (재업로드 허용)
    content_hash = slide_status.get(slide_id, {}).get("content_hash")
    if content_hash:
        _hash_to_slide_id.pop(content_hash, None)

    return {"slide_id": slide_id, "mode": "cancelled_and_cleaned", "deleted": deleted}


@router.delete("/delete/{slide_id}")
async def delete_slide(slide_id: str):
    """강의자료 완전 삭제 (단건). UI에서는 직접 호출하지 않고 호환성용으로 유지."""
    deleted = _delete_slide_files(slide_id)
    if not deleted:
        raise HTTPException(404, "강의자료를 찾을 수 없습니다")

    return {
        "slide_id": slide_id,
        "message": "강의자료 삭제 완료",
        "deleted_files": deleted,
    }


_FORBIDDEN_RENAME_CHARS = set(r'\/:*?"<>|')


@router.patch("/{slide_id}/rename", response_model=RenameSlideResponse)
async def rename_slide(slide_id: str, payload: RenameSlideRequest):
    """강의자료 파일명 수정 — 사용자가 라이브러리에서 직접 변경.
    실제 디스크의 PDF 파일명은 그대로(slide_id) 유지하고 메타데이터의 filename만 갱신."""
    new_name = (payload.filename or "").strip()
    if not new_name:
        raise HTTPException(400, "파일명은 비어있을 수 없습니다")
    # 위험 문자 제거 + 제어문자 제거
    cleaned = "".join(c for c in new_name if c not in _FORBIDDEN_RENAME_CHARS and c.isprintable()).strip()
    if not cleaned:
        raise HTTPException(400, "유효하지 않은 파일명입니다")
    if len(cleaned) > 100:
        cleaned = cleaned[:100]
    # .pdf 확장자 보장
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"

    meta_path = _meta_path(slide_id)
    if not meta_path.exists():
        raise HTTPException(404, "강의자료를 찾을 수 없습니다")

    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["filename"] = cleaned
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(500, f"메타데이터 갱신 실패: {e}")

    # 메모리 동기화
    if slide_id in slide_status:
        slide_status[slide_id]["filename"] = cleaned

    return RenameSlideResponse(slide_id=slide_id, filename=cleaned)


@router.post("/delete-batch", response_model=BatchDeleteResponse)
async def delete_slides_batch(payload: BatchDeleteRequest):
    """다중 강의자료 일괄 삭제. 항목별 실패해도 나머지 진행, 부분 실패는 200 + failed로 보고."""
    if not payload.slide_ids:
        raise HTTPException(400, "삭제할 slide_ids가 비어있습니다")

    deleted: list[str] = []
    failed: list[BatchDeleteFailure] = []

    for slide_id in payload.slide_ids:
        try:
            removed = _delete_slide_files(slide_id)
            if not removed:
                failed.append(BatchDeleteFailure(
                    slide_id=slide_id,
                    reason="강의자료를 찾을 수 없습니다",
                ))
            else:
                deleted.append(slide_id)
        except Exception as e:
            failed.append(BatchDeleteFailure(slide_id=slide_id, reason=str(e)))

    return BatchDeleteResponse(deleted=deleted, failed=failed)


async def process_slide(slide_id: str, pdf_path: Path):
    """
    슬라이드 전처리 (백그라운드)
    PDF 텍스트 레이어가 있으면 → PDF 레이어 방식 (고품질)
    없으면 → 기존 OCR/VLM 방식
    """
    try:
        slide_status[slide_id]["status"] = "processing"

        # 체크포인트 ①: processing 진입 직후
        if _is_cancelled(slide_id):
            await _cleanup_cancelled(slide_id)
            return

        # PDF 텍스트 레이어 확인
        try:
            from app.services.slide_translation.pdf_text_extractor import check_pdf_has_text_layer
            layer_info = check_pdf_has_text_layer(str(pdf_path))
            has_text_layer = layer_info.get("has_text_layer", False)
            text_coverage = layer_info.get("text_coverage_ratio", 0)
            print(f"[Slides] PDF 텍스트 레이어 확인: has_layer={has_text_layer}, coverage={text_coverage}")
        except Exception as e:
            print(f"[Slides] 텍스트 레이어 확인 실패 (OCR 방식 사용): {e}")
            has_text_layer = False
            text_coverage = 0

        # 텍스트 레이어가 충분하면 PDF 레이어 방식 사용
        if has_text_layer and text_coverage >= 0.8:
            print(f"[Slides] PDF 레이어 방식으로 처리 시작...")
            await process_slide_pdf_layer(slide_id, pdf_path)
            return

        print(f"[Slides] 기존 OCR/VLM 방식으로 처리...")

        # PDF를 이미지로 변환
        images = await asyncio.to_thread(pdf_to_images, pdf_path)
        total_pages = len(images)
        slide_status[slide_id]["total_pages"] = total_pages

        # 체크포인트 ②: pdf_to_images 완료 후 (OCR 진입 직전)
        if _is_cancelled(slide_id):
            await _cleanup_cancelled(slide_id)
            return

        slide_data[slide_id] = []

        # VLM 번역 함수 임포트
        try:
            from app.services.slide_translation.image_pipeline import (
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
            # 체크포인트 ③: OCR 루프 각 페이지 시작
            if _is_cancelled(slide_id):
                await _cleanup_cancelled(slide_id)
                return

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

        # 체크포인트 ④: OCR 루프 종료 후 — 용어집 빌드 전
        if _is_cancelled(slide_id):
            await _cleanup_cancelled(slide_id)
            return

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
                # 실시간 NMT 가 가져갈 수 있게 slide_id 별로 보존
                if glossary:
                    slide_glossary[slide_id] = glossary
                    print(f"[Slides] {slide_id} 용어집 보존: {len(glossary)}개 (실시간 NMT 활용)")
            except Exception as e:
                print(f"[Slides] 용어집 빌드 실패 (무시): {e}")

        # ========== 2단계: 모든 페이지 번역 (VLM) ==========
        _set_stage(slide_id, "translate", total_pages)
        for i, (image_path, regions) in enumerate(ocr_results):
            # 체크포인트 ⑤: VLM 번역 루프 각 페이지 시작 (가장 무거운 50s/page 진입 직전)
            if _is_cancelled(slide_id):
                await _cleanup_cancelled(slide_id)
                return

            translated_path = TRANSLATED_DIR / f"{slide_id}_{i}.png"
            overlay_items = []

            if vlm_available and regions is not None:
                try:
                    print(f"[Slides] {slide_id} 페이지 {i + 1}/{total_pages} VLM 번역 중...")
                    regions = await asyncio.to_thread(stage_translate, str(image_path), regions, glossary)

                    # 체크포인트 ⑥: stage_translate(~50s) 끝난 직후 — overlay/save/다음 페이지 진입을 건너뜀
                    if _is_cancelled(slide_id):
                        await _cleanup_cancelled(slide_id)
                        return

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

        # 체크포인트 ⑦: 번역 루프 종료 후 — bundling 진입 직전
        if _is_cancelled(slide_id):
            await _cleanup_cancelled(slide_id)
            return

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

        # 취소된 경우 메타데이터 저장하지 않음 (해시 매핑 재생성 방지)
        if _is_cancelled(slide_id):
            print(f"[Slides] {slide_id} 처리 완료 전 취소됨 - 메타데이터 저장 스킵")
            await _cleanup_cancelled(slide_id)
            return

        slide_status[slide_id]["status"] = "completed"
        slide_status[slide_id]["stage"] = "completed"
        # 라이브러리 영속화 — 서버 재시작 후에도 자료 유지
        save_metadata(slide_id)
        print(f"[Slides] {slide_id} 전처리 완료! (번역 포함)")

    except Exception as e:
        slide_status[slide_id]["status"] = "failed"
        slide_status[slide_id]["stage"] = "failed"
        slide_status[slide_id]["error"] = str(e)
        print(f"[Slides] {slide_id} 처리 실패: {e}")
        # 예외 발생 시에도 VLM 언로드 보장
        try:
            from app.services.slide_translation.image_pipeline import unload_vlm_model
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


async def process_slide_pdf_layer(slide_id: str, pdf_path: Path):
    """
    PDF 레이어 방식 슬라이드 처리 (Stage 기반 배치 구조)

    Stage 1: 페이지 분류
    Stage 2: PDF Layer 처리
    Stage 3: OCR 배치 (Surya 한 번 로드)
    Stage 4: VLM 번역 배치 (VLM 한 번 로드)
    Stage 5: Overlay/rendering (CPU)
    Stage 6: PDF 합성
    """
    import fitz
    import re
    from app.services.slide_translation.pdf_pipeline import PDFLayerPipeline

    try:
        # ========== Stage 1: 페이지 분류 ==========
        print("\n" + "=" * 60)
        print(f"[Stage 1] 페이지 분류")
        print("=" * 60)

        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)

        pdf_layer_pages = []  # 텍스트 레이어 있는 페이지
        ocr_pages = []        # 텍스트 레이어 없는 페이지
        image_region_pages = []  # 이미지 영역 OCR 필요 (PDF 레이어 처리 후 판단)

        for page_idx, page in enumerate(doc):
            text_dict = page.get_text("dict")
            text_blocks = [b for b in text_dict.get("blocks", []) if b.get("type") == 0]
            image_blocks = [b for b in text_dict.get("blocks", []) if b.get("type") == 1]

            has_text_layer = len(text_blocks) >= 2

            if has_text_layer:
                pdf_layer_pages.append(page_idx)

                # 이미지 영역 비율 계산 (나중에 OCR fallback 필요 여부)
                page_area = page.rect.width * page.rect.height
                image_area = sum(
                    (b["bbox"][2] - b["bbox"][0]) * (b["bbox"][3] - b["bbox"][1])
                    for b in image_blocks
                )
                image_ratio = image_area / page_area if page_area > 0 else 0

                if image_ratio >= 0.10:  # 10% 이상 이미지
                    image_region_pages.append(page_idx)
            else:
                ocr_pages.append(page_idx)

        doc.close()

        print(f"  PDF 레이어 페이지: {len(pdf_layer_pages)}개")
        print(f"  OCR 필요 페이지: {len(ocr_pages)}개")
        print(f"  이미지 영역 OCR 필요: {len(image_region_pages)}개")

        slide_status[slide_id]["total_pages"] = total_pages
        slide_data[slide_id] = [{} for _ in range(total_pages)]

        # 체크포인트: 페이지 분석 완료 후 — PDF 레이어 파이프라인 진입 직전
        if _is_cancelled(slide_id):
            await _cleanup_cancelled(slide_id)
            return

        # 출력 경로
        translated_pdf_path = TRANSLATED_DIR / f"{slide_id}_translated.pdf"

        # ========== Stage 2: PDF Layer 처리 ==========
        _set_stage(slide_id, "translate", total_pages)

        if pdf_layer_pages:
            print("\n" + "=" * 60)
            print(f"[Stage 2] PDF Layer 처리 ({len(pdf_layer_pages)}개 페이지)")
            print("=" * 60)

            def on_page_done(current_page: int):
                _page_completed(slide_id, current_page)
                slide_status[slide_id]["processed_pages"] = current_page

            glossary = slide_glossary.get(slide_id, {})
            if glossary:
                print(f"  용어집 {len(glossary)}개 용어 적용")

            pipeline = PDFLayerPipeline(
                output_dir=str(TRANSLATED_DIR),
                on_page_complete=on_page_done,
                glossary=glossary,
                should_cancel=lambda sid=slide_id: _is_cancelled(sid),
            )
            result = await asyncio.to_thread(
                pipeline.run,
                str(pdf_path),
                str(translated_pdf_path)
            )

            # 파이프라인이 내부 체크포인트에서 취소 감지하고 빠져나왔으면 즉시 정리
            if result.get("cancelled"):
                print(f"[Slides] {slide_id} PDF 레이어 파이프라인 내부 취소 감지")
                await _cleanup_cancelled(slide_id)
                return

            print(f"  결과: replaced={result.get('replaced', 0)}, "
                  f"review_needed={result.get('review_needed', 0)}, "
                  f"failed={result.get('failed', 0)}")

        # 체크포인트: PDF 레이어 파이프라인 종료 후 — OCR 배치 진입 직전
        if _is_cancelled(slide_id):
            await _cleanup_cancelled(slide_id)
            return

        # ========== Stage 3: OCR 배치 (Surya 한 번 로드) ==========
        # OCR 대상: ocr_pages (텍스트 레이어 없음) + image_region_pages (이미지 영역)
        all_ocr_pages = list(set(ocr_pages + image_region_pages))
        all_ocr_pages.sort()

        ocr_results = {}
        image_paths_map = {}

        if all_ocr_pages:
            print("\n" + "=" * 60)
            print(f"[Stage 3] OCR 배치 ({len(all_ocr_pages)}개 페이지)")
            print("=" * 60)

            try:
                from app.services.slide_translation.image_pipeline import (
                    batch_ocr_surya, batch_translate_vlm, batch_overlay,
                    unload_vlm_model, clear_cache
                )

                # 이미지 준비
                print("  이미지 준비 중...")
                image_paths_for_ocr = []

                # ocr_pages: 원본 PDF에서 추출
                if ocr_pages:
                    doc = fitz.open(str(pdf_path))
                    for page_idx in ocr_pages:
                        page = doc[page_idx]
                        mat = fitz.Matrix(2, 2)
                        pix = page.get_pixmap(matrix=mat)
                        img_path = IMAGES_DIR / f"{slide_id}_{page_idx}.png"
                        pix.save(str(img_path))
                        image_paths_for_ocr.append((page_idx, str(img_path)))
                        image_paths_map[page_idx] = str(img_path)
                    doc.close()

                # image_region_pages: 원본 PDF에서 추출 (번역 전 한글 텍스트 감지 위해)
                if image_region_pages:
                    orig_doc = fitz.open(str(pdf_path))
                    for page_idx in image_region_pages:
                        if page_idx not in [p[0] for p in image_paths_for_ocr]:
                            page = orig_doc[page_idx]
                            mat = fitz.Matrix(2, 2)
                            pix = page.get_pixmap(matrix=mat)
                            img_path = IMAGES_DIR / f"{slide_id}_{page_idx}_region.png"
                            pix.save(str(img_path))
                            image_paths_for_ocr.append((page_idx, str(img_path)))
                            image_paths_map[page_idx] = str(img_path)
                    orig_doc.close()

                # 배치 OCR 실행 (Surya 한 번 로드)
                ocr_results = await asyncio.to_thread(
                    batch_ocr_surya,
                    image_paths_for_ocr,
                    slide_id
                )

                print(f"  OCR 완료: {len(ocr_results)}개 페이지")

            except ImportError as e:
                print(f"  OCR 모듈 없음: {e}")
            except Exception as e:
                print(f"  OCR 배치 실패: {e}")
                import traceback
                traceback.print_exc()

        # 체크포인트: OCR 배치 완료 후 — VLM 번역 진입 직전
        if _is_cancelled(slide_id):
            await _cleanup_cancelled(slide_id)
            return

        # ========== Stage 4: VLM 번역 배치 (VLM 한 번 로드) ==========
        translate_results = {}

        if ocr_results:
            # 한글이 포함된 페이지만 필터링
            pages_with_korean = {}
            for page_idx, regions in ocr_results.items():
                korean_regions = []
                for region in regions:
                    ocr_text = region.get("ocr_text", "")
                    if re.search(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]', ocr_text):
                        korean_regions.append(region)

                if korean_regions:
                    pages_with_korean[page_idx] = korean_regions
                    print(f"  페이지 {page_idx+1}: 한글 {len(korean_regions)}개 영역")

            if pages_with_korean:
                print("\n" + "=" * 60)
                print(f"[Stage 4] VLM 번역 배치 ({len(pages_with_korean)}개 페이지)")
                print("=" * 60)

                try:
                    from app.services.slide_translation.image_pipeline import (
                        batch_translate_vlm, unload_vlm_model
                    )

                    glossary = slide_glossary.get(slide_id, {})

                    # 배치 번역 실행 (VLM 한 번 로드)
                    translate_results = await asyncio.to_thread(
                        batch_translate_vlm,
                        pages_with_korean,
                        image_paths_map,
                        slide_id,
                        glossary
                    )

                    print(f"  번역 완료: {len(translate_results)}개 페이지")

                    # VLM 언로드
                    await asyncio.to_thread(unload_vlm_model)

                except Exception as e:
                    print(f"  VLM 번역 배치 실패: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print("\n[Stage 4] 번역할 한글 없음 - 스킵")

        # ========== Stage 5: Overlay/rendering (CPU) ==========
        if translate_results:
            print("\n" + "=" * 60)
            print(f"[Stage 5] Overlay 렌더링 ({len(translate_results)}개 페이지)")
            print("=" * 60)

            try:
                from app.services.slide_translation.image_pipeline import batch_overlay

                output_paths = await asyncio.to_thread(
                    batch_overlay,
                    translate_results,
                    image_paths_map,
                    str(TRANSLATED_DIR),
                    slide_id
                )

                # slide_data 업데이트
                for page_idx, regions in translate_results.items():
                    method = "ocr" if page_idx in ocr_pages else "pdf_layer+ocr_fallback"
                    slide_data[slide_id][page_idx] = {
                        "page_number": page_idx,
                        "ocr_text": None,
                        "overlay_items": [
                            {"original": r.get("ocr_text", ""), "translated": r.get("english", "")}
                            for r in regions if not r.get("skip_translate", False)
                        ],
                        "has_translation": True,
                        "method": method,
                    }
                    _page_completed(slide_id, page_idx + 1)

                print(f"  Overlay 완료: {len(output_paths)}개 페이지")

            except Exception as e:
                print(f"  Overlay 실패: {e}")
                import traceback
                traceback.print_exc()

        # OCR 결과가 없는 ocr_pages는 원본 이미지 복사
        for page_idx in ocr_pages:
            if page_idx not in translate_results:
                orig_img = IMAGES_DIR / f"{slide_id}_{page_idx}.png"
                trans_img = TRANSLATED_DIR / f"{slide_id}_{page_idx}.png"
                if orig_img.exists() and not trans_img.exists():
                    shutil.copy(orig_img, trans_img)
                slide_data[slide_id][page_idx] = {
                    "page_number": page_idx,
                    "ocr_text": None,
                    "overlay_items": [],
                    "has_translation": trans_img.exists(),
                    "method": "ocr",
                }

        # 체크포인트: bundling 진입 직전
        if _is_cancelled(slide_id):
            await _cleanup_cancelled(slide_id)
            return

        # ========== Stage 6: 이미지 추출 및 PDF 합성 ==========
        print("\n" + "=" * 60)
        print(f"[Stage 6] PDF 합성")
        print("=" * 60)
        _set_stage(slide_id, "bundling", total_pages)

        # PDF 레이어 페이지 이미지 추출
        if translated_pdf_path.exists():
            trans_doc = fitz.open(str(translated_pdf_path))
            for i, page in enumerate(trans_doc):
                if i in pdf_layer_pages:
                    img_path = TRANSLATED_DIR / f"{slide_id}_{i}.png"
                    if not img_path.exists():
                        mat = fitz.Matrix(2, 2)
                        pix = page.get_pixmap(matrix=mat)
                        pix.save(str(img_path))

                        slide_data[slide_id][i] = {
                            "page_number": i,
                            "ocr_text": None,
                            "overlay_items": [],
                            "has_translation": True,
                            "method": "pdf_layer",
                        }
            trans_doc.close()

        # 원본 이미지 추출
        orig_doc = fitz.open(str(pdf_path))
        for i in pdf_layer_pages:
            img_path = IMAGES_DIR / f"{slide_id}_{i}.png"
            if not img_path.exists():
                page = orig_doc[i]
                mat = fitz.Matrix(2, 2)
                pix = page.get_pixmap(matrix=mat)
                pix.save(str(img_path))
        orig_doc.close()

        # temp 이미지 정리
        for page_idx in image_region_pages:
            temp_img = TRANSLATED_DIR / f"{slide_id}_{page_idx}_temp.png"
            if temp_img.exists():
                temp_img.unlink()

        # Hybrid PDF 생성
        if ocr_pages or image_region_pages:
            print("  Hybrid PDF 생성 중...")
            try:
                from PIL import Image

                all_images = []
                for i in range(total_pages):
                    trans_img = TRANSLATED_DIR / f"{slide_id}_{i}.png"
                    if trans_img.exists():
                        img = Image.open(trans_img).convert("RGB")
                        all_images.append(img)

                if all_images:
                    all_images[0].save(
                        translated_pdf_path,
                        format="PDF",
                        save_all=True,
                        append_images=all_images[1:] if len(all_images) > 1 else [],
                        resolution=150.0
                    )
                    print(f"  Hybrid PDF 저장: {translated_pdf_path}")

                    for img in all_images:
                        img.close()
            except Exception as e:
                print(f"  Hybrid PDF 생성 실패: {e}")

        # 취소된 경우 메타데이터 저장하지 않음 (해시 매핑 재생성 방지)
        if _is_cancelled(slide_id):
            print(f"[Slides] {slide_id} 처리 완료 전 취소됨 - 메타데이터 저장 스킵")
            await _cleanup_cancelled(slide_id)
            return

        # 완료
        slide_status[slide_id]["status"] = "completed"
        slide_status[slide_id]["stage"] = "completed"
        slide_status[slide_id]["processed_pages"] = total_pages
        save_metadata(slide_id)

        print("\n" + "=" * 60)
        print(f"[완료] {slide_id}")
        print(f"  PDF 레이어: {len(pdf_layer_pages)}개")
        print(f"  OCR: {len(ocr_pages)}개")
        print(f"  이미지 영역 OCR: {len(image_region_pages)}개")
        print("=" * 60)

    except Exception as e:
        print(f"[Slides] 처리 실패: {e}")
        import traceback
        traceback.print_exc()
        slide_status[slide_id]["status"] = "failed"
        slide_status[slide_id]["stage"] = "failed"
        slide_status[slide_id]["error"] = str(e)
        try:
            from app.services.slide_translation.image_pipeline import unload_vlm_model
            await asyncio.to_thread(unload_vlm_model)
        except Exception:
            pass


