# 강의자료 라이브러리 - 백엔드 설계

## 개요

강의자료(슬라이드)의 영속성을 지원하여 서버 재시작 후에도 기존 자료를 불러올 수 있게 함.

> 프론트엔드 변경사항(`SLIDE_LIBRARY_FRONTEND.md`)에 맞춰 다음을 추가/수정한다.
> - **일괄 삭제 API** 신규 추가 (선택 모드에서 사용)
> - 라이브러리 조회 API에 **정렬 옵션** 명시 (`?sort=recent|name`, 기본 `recent`)
> - 단건 삭제 API는 호환성을 위해 유지 (UI에서는 직접 호출하지 않음)

## 현재 문제점

- 모든 슬라이드 상태가 메모리에만 저장됨 (`slide_status`, `slide_data`)
- 서버 재시작 시 모든 데이터 손실
- 강의 시작 시 매번 PDF 업로드 + 전처리 필요 (불편)

## 설계 방향

### 저장 방식: JSON 파일 기반

**선택 이유:**
- 현재 프로젝트에 DB 없음
- 단일 서버 배포 환경
- 구현/디버깅 용이
- 백업/이동 간편

### 디렉토리 구조

```
uploads/
├── slides/
│   ├── {slide_id}.pdf          # 원본 PDF
│   └── {slide_id}.meta.json    # 메타데이터 (신규)
├── images/
│   └── {slide_id}_{page}.png   # 원본 이미지
└── translated/
    ├── {slide_id}_{page}.png   # 번역 이미지
    └── {slide_id}_translated.pdf
```

---

## 데이터 모델

### meta.json 스키마

```json
{
  "slide_id": "abc12345",
  "filename": "알고리즘_강의.pdf",
  "uploaded_at": "2025-04-29T10:30:00",
  "total_pages": 15,
  "status": "completed",
  "page_data": [
    {
      "page_number": 0,
      "ocr_text": "슬라이드 제목...",
      "overlay_items": [
        {
          "original": "Hello",
          "translated": "안녕하세요",
          "bbox": [100, 200, 300, 250],
          "confidence": 0.95
        }
      ]
    }
  ]
}
```

### Pydantic 모델

```python
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime

class SlideMetadata(BaseModel):
    slide_id: str
    filename: str
    uploaded_at: datetime
    total_pages: int
    status: str  # pending, processing, completed, failed
    page_data: Optional[list[dict]] = None  # 목록 조회 시 제외 가능

class SlideLibraryItem(BaseModel):
    slide_id: str
    filename: str
    uploaded_at: datetime
    total_pages: int
    status: str
    has_translated: bool

# 일괄 삭제 요청 본문
class BatchDeleteRequest(BaseModel):
    slide_ids: list[str]

# 일괄 삭제 응답
class BatchDeleteFailure(BaseModel):
    slide_id: str
    reason: str

class BatchDeleteResponse(BaseModel):
    deleted: list[str]
    failed: list[BatchDeleteFailure]

# 정렬 옵션 타입 힌트
SortOrder = Literal["recent", "name"]
```

---

## API 설계

### 1. GET /slides/library

저장된 강의자료 목록 조회 (서버 재시작 후에도 유지)

**Query Parameters:**

| 이름 | 타입 | 기본값 | 설명 |
|-----|-----|------|-----|
| `sort` | `recent` \| `name` | `recent` | 정렬 기준 (최신순/이름순) |

> 정렬은 프론트엔드에서도 클라이언트 측으로 처리하지만, 서버에서도 동일 순서를 보장하기 위해 옵션을 제공한다.

**Response:**
```json
{
  "items": [
    {
      "slide_id": "abc12345",
      "filename": "알고리즘_강의.pdf",
      "uploaded_at": "2025-04-29T10:30:00",
      "total_pages": 15,
      "status": "completed",
      "has_translated": true
    }
  ]
}
```

**구현:**
```python
from fastapi import Query

@router.get("/library")
async def get_library(sort: str = Query("recent", regex="^(recent|name)$")):
    """저장된 강의자료 목록 (파일 기반)"""
    items = []
    for meta_file in UPLOAD_DIR.glob("*.meta.json"):
        with open(meta_file) as f:
            meta = json.load(f)
        translated_pdf = TRANSLATED_DIR / f"{meta['slide_id']}_translated.pdf"
        items.append({
            "slide_id": meta["slide_id"],
            "filename": meta["filename"],
            "uploaded_at": meta["uploaded_at"],
            "total_pages": meta["total_pages"],
            "status": meta["status"],
            "has_translated": translated_pdf.exists(),
        })

    if sort == "name":
        items.sort(key=lambda x: x["filename"].lower())
    else:
        # 기본: 최신순
        items.sort(key=lambda x: x["uploaded_at"], reverse=True)

    return {"items": items}
```

---

### 2. POST /slides/load/{slide_id}

기존 강의자료를 메모리에 로드 (강의 시작용 / 프론트의 카드 클릭 동작)

**Response:**
```json
{
  "slide_id": "abc12345",
  "message": "강의자료 로드 완료",
  "total_pages": 15
}
```

**구현:**
```python
@router.post("/load/{slide_id}")
async def load_slide(slide_id: str):
    """저장된 강의자료를 메모리에 로드"""
    meta_path = UPLOAD_DIR / f"{slide_id}.meta.json"
    if not meta_path.exists():
        raise HTTPException(404, "강의자료를 찾을 수 없습니다")

    with open(meta_path) as f:
        meta = json.load(f)

    if meta["status"] != "completed":
        raise HTTPException(400, "처리가 완료되지 않은 강의자료입니다")

    # 메모리에 로드
    slide_status[slide_id] = {
        "status": meta["status"],
        "total_pages": meta["total_pages"],
        "processed_pages": meta["total_pages"],
        "stage": "completed",
        "filename": meta["filename"],
        # ...
    }
    slide_data[slide_id] = meta.get("page_data", [])

    return {
        "slide_id": slide_id,
        "message": "강의자료 로드 완료",
        "total_pages": meta["total_pages"]
    }
```

---

### 3. DELETE /slides/delete/{slide_id} (단건, 호환성 유지)

> 프론트 UI에서는 직접 호출하지 않으나, 외부/관리용으로 유지한다.
> 내부적으로 일괄 삭제 핸들러가 이 함수를 재사용한다.

**Response:**
```json
{
  "slide_id": "abc12345",
  "message": "강의자료 삭제 완료",
  "deleted_files": ["pdf", "meta", "images", "translated"]
}
```

**구현:**
```python
def _delete_slide_files(slide_id: str) -> list[str]:
    """단일 슬라이드의 모든 관련 파일/메모리 정리. 삭제된 항목 종류 리스트 반환."""
    deleted: list[str] = []

    # 1. 원본 PDF
    pdf_path = UPLOAD_DIR / f"{slide_id}.pdf"
    if pdf_path.exists():
        pdf_path.unlink()
        deleted.append("pdf")

    # 2. 메타데이터
    meta_path = UPLOAD_DIR / f"{slide_id}.meta.json"
    if meta_path.exists():
        meta_path.unlink()
        deleted.append("meta")

    # 3. 원본 이미지들
    image_files = list(IMAGES_DIR.glob(f"{slide_id}_*.png"))
    for img in image_files:
        img.unlink()
    if image_files:
        deleted.append("images")

    # 4. 번역 이미지들
    translated_imgs = list(TRANSLATED_DIR.glob(f"{slide_id}_*.png"))
    for img in translated_imgs:
        img.unlink()

    # 5. 번역 PDF
    translated_pdf = TRANSLATED_DIR / f"{slide_id}_translated.pdf"
    if translated_pdf.exists():
        translated_pdf.unlink()
        deleted.append("translated")

    # 6. 메모리에서 제거
    slide_status.pop(slide_id, None)
    slide_data.pop(slide_id, None)

    return deleted


@router.delete("/delete/{slide_id}")
async def delete_slide(slide_id: str):
    """강의자료 완전 삭제 (단건)"""
    deleted = _delete_slide_files(slide_id)
    if not deleted:
        raise HTTPException(404, "강의자료를 찾을 수 없습니다")

    return {
        "slide_id": slide_id,
        "message": "강의자료 삭제 완료",
        "deleted_files": deleted
    }
```

---

### 4. POST /slides/delete-batch (신규, 일괄 삭제)

선택 모드에서 다중 선택된 항목을 한 번에 삭제. 부분 실패도 보고한다.

**Request:**
```json
{
  "slide_ids": ["abc12345", "def67890"]
}
```

**Response (200):**
```json
{
  "deleted": ["abc12345", "def67890"],
  "failed": []
}
```

**Response (부분 실패):**
```json
{
  "deleted": ["abc12345"],
  "failed": [
    { "slide_id": "def67890", "reason": "강의자료를 찾을 수 없습니다" }
  ]
}
```

**구현:**
```python
@router.post("/delete-batch", response_model=BatchDeleteResponse)
async def delete_slides_batch(payload: BatchDeleteRequest):
    """다중 강의자료 일괄 삭제. 항목별로 실패해도 나머지는 진행."""
    if not payload.slide_ids:
        raise HTTPException(400, "삭제할 slide_ids가 비어있습니다")

    deleted: list[str] = []
    failed: list[dict] = []

    for slide_id in payload.slide_ids:
        try:
            removed = _delete_slide_files(slide_id)
            if not removed:
                failed.append({
                    "slide_id": slide_id,
                    "reason": "강의자료를 찾을 수 없습니다",
                })
            else:
                deleted.append(slide_id)
        except Exception as e:
            failed.append({"slide_id": slide_id, "reason": str(e)})

    return {"deleted": deleted, "failed": failed}
```

**설계 메모:**
- 멱등성: 이미 삭제된 항목을 다시 요청해도 `failed`에 "찾을 수 없음"으로 보고할 뿐 5xx는 던지지 않는다.
- 부분 실패 시에도 200 OK를 반환하고 `failed` 배열로 구분 (프론트가 결과 토스트로 노출).
- 큰 배치 입력에 대비해 추후 비동기 큐 전환 여지를 남긴다 (현 단계에서는 동기 처리).

---

### 5. POST /slides/upload (기존 수정)

업로드 완료 시 메타데이터 저장 추가

**수정 사항:**
```python
async def process_slide(slide_id: str, pdf_path: Path):
    # ... 기존 처리 로직 ...

    # 처리 완료 후 메타데이터 저장
    if status == "completed":
        save_metadata(slide_id)

def save_metadata(slide_id: str):
    """메타데이터를 JSON 파일로 저장"""
    meta = {
        "slide_id": slide_id,
        "filename": slide_status[slide_id].get("filename"),
        "uploaded_at": datetime.now().isoformat(),
        "total_pages": slide_status[slide_id].get("total_pages"),
        "status": "completed",
        "page_data": slide_data.get(slide_id, []),
    }
    meta_path = UPLOAD_DIR / f"{slide_id}.meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
```

---

## 서버 시작 시 초기화

```python
# slides.py 상단 또는 main.py

def init_slide_library():
    """서버 시작 시 메타파일 스캔 (목록용, 상세 데이터는 로드하지 않음)"""
    print("[Slides] 강의자료 라이브러리 초기화...")
    count = 0
    for meta_file in UPLOAD_DIR.glob("*.meta.json"):
        try:
            with open(meta_file) as f:
                meta = json.load(f)
            # 목록용 기본 정보만 메모리에 (page_data는 load 시 로드)
            slide_id = meta["slide_id"]
            slide_status[slide_id] = {
                "status": meta["status"],
                "total_pages": meta["total_pages"],
                "filename": meta["filename"],
                "stage": "completed" if meta["status"] == "completed" else meta["status"],
            }
            count += 1
        except Exception as e:
            print(f"[Slides] 메타 로드 실패: {meta_file} - {e}")
    print(f"[Slides] {count}개 강의자료 발견")

# 모듈 로드 시 실행
init_slide_library()
```

---

## 에러 처리

| 상황 | HTTP 코드 | 메시지 |
|-----|----------|--------|
| 존재하지 않는 slide_id (단건 삭제/로드) | 404 | "강의자료를 찾을 수 없습니다" |
| 처리 미완료 자료 로드 시도 | 400 | "처리가 완료되지 않은 강의자료입니다" |
| 일괄 삭제 요청 본문 비어있음 | 400 | "삭제할 slide_ids가 비어있습니다" |
| 일괄 삭제 중 항목 실패 | 200 | `failed` 배열에 사유 포함 |
| 메타 파일 손상 | 500 | "메타데이터 읽기 실패" |
| 잘못된 sort 값 | 422 | (FastAPI 자동 검증) |

---

## 마이그레이션

기존에 처리된 슬라이드가 있으나 meta.json이 없는 경우:

```python
def migrate_existing_slides():
    """기존 슬라이드에 대해 메타파일 생성 (1회성)"""
    for pdf in UPLOAD_DIR.glob("*.pdf"):
        slide_id = pdf.stem
        meta_path = UPLOAD_DIR / f"{slide_id}.meta.json"
        if not meta_path.exists():
            # 이미지 파일로 페이지 수 추정
            pages = len(list(IMAGES_DIR.glob(f"{slide_id}_*.png")))
            if pages > 0:
                meta = {
                    "slide_id": slide_id,
                    "filename": f"{slide_id}.pdf",
                    "uploaded_at": datetime.fromtimestamp(pdf.stat().st_mtime).isoformat(),
                    "total_pages": pages,
                    "status": "completed",
                    "page_data": [],  # 상세 데이터 없음
                }
                with open(meta_path, "w") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
                print(f"[Migration] {slide_id} 메타 생성")
```

---

## 테스트 체크리스트

- [ ] 새 PDF 업로드 → meta.json 생성 확인
- [ ] 서버 재시작 → /slides/library에서 기존 자료 조회
- [ ] /slides/library?sort=recent → 최신순 정렬 (기본값)
- [ ] /slides/library?sort=name → 파일명 오름차순 정렬
- [ ] /slides/load/{id} → 메모리 로드 및 뷰어 동작
- [ ] /slides/delete/{id} → 모든 관련 파일 삭제 (단건)
- [ ] /slides/delete-batch → 정상 케이스 일괄 삭제 (모두 성공)
- [ ] /slides/delete-batch → 부분 실패 시 `deleted` / `failed` 분리 응답
- [ ] /slides/delete-batch → 빈 배열 요청 시 400
- [ ] /slides/delete-batch → 동일 ID 중복 요청 시 멱등 동작
- [ ] 삭제 후 /slides/library에서 제외 확인
