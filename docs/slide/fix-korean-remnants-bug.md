# 한글 잔상 버그 수정

## 문제 현상

번역된 PDF/이미지에서 원본 한글 텍스트가 완전히 제거되지 않고 잔상으로 남아있음.

- 영어 번역 텍스트 **왼쪽**에 한글 글자가 남음
- "운영", "것", "하드", "효", "얻", "형", "게", "선택의" 등

---

## 원인 분석

### 문제 코드

```python
# slides.py (Line 1397-1409)

# image_region_pages: 원본 PDF에서 추출 (번역 전 한글 텍스트 감지 위해)
if image_region_pages:
    orig_doc = fitz.open(str(pdf_path))  # ← 원본 PDF 사용!
    for page_idx in image_region_pages:
        ...
        pix = page.get_pixmap(matrix=mat)
        ...
```

### 버그 메커니즘

`image_region_pages`는 텍스트 레이어가 있으면서 이미지 영역도 ≥10%인 페이지:

```
┌─────────────────────────────────────────────────────────────┐
│  [Stage 2] PDF Layer 처리                                    │
│  └─ 텍스트 레이어 번역 → translated_pdf.pdf 저장             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  [Stage 3] OCR 배치 (버그!)                                  │
│  └─ image_region_pages 이미지 추출                          │
│     └─ 원본 PDF에서 추출 (pdf_path) ← 문제!                 │
│     └─ 원본 한글 텍스트가 그대로 있음                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  [Stage 5] Overlay 렌더링                                    │
│  └─ 원본 이미지 위에 영어 텍스트 렌더링                      │
│  └─ OCR bbox가 원본 한글을 완전히 덮지 못함                  │
│  └─ 한글 잔상 발생!                                          │
└─────────────────────────────────────────────────────────────┘
```

**핵심 문제:**
1. PDF Layer가 텍스트 레이어를 번역 → `translated_pdf.pdf`
2. OCR용 이미지를 **원본 PDF**에서 추출 → 원본 한글 텍스트 포함
3. Overlay가 원본 이미지 위에 영어 렌더링 → PDF Layer 번역 결과 무시
4. OCR bbox가 정확하지 않아 원본 한글 일부가 덮이지 않음 → **잔상**

---

## 수정 내용

### 변경된 코드

```python
# slides.py (Line 1397-1410)

# image_region_pages: 번역된 PDF에서 추출 (PDF Layer로 텍스트 번역 후 이미지 영역만 OCR)
# 원본 PDF가 아닌 번역된 PDF를 사용해야 텍스트 레이어 번역 결과가 보존됨
if image_region_pages and translated_pdf_path.exists():
    trans_doc = fitz.open(str(translated_pdf_path))  # ← 번역된 PDF 사용!
    for page_idx in image_region_pages:
        ...
        pix = page.get_pixmap(matrix=mat)
        ...
```

### 수정 후 흐름

```
┌─────────────────────────────────────────────────────────────┐
│  [Stage 2] PDF Layer 처리                                    │
│  └─ 텍스트 레이어 번역 → translated_pdf.pdf 저장             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  [Stage 3] OCR 배치 (수정됨!)                                │
│  └─ image_region_pages 이미지 추출                          │
│     └─ 번역된 PDF에서 추출 (translated_pdf_path) ← 수정!    │
│     └─ 텍스트 레이어는 이미 영어로 번역됨                    │
│     └─ 이미지 영역의 한글만 OCR 감지                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  [Stage 5] Overlay 렌더링                                    │
│  └─ 번역된 이미지 위에 추가 영어 텍스트 렌더링               │
│  └─ PDF Layer 번역 결과 보존됨!                              │
│  └─ 이미지 영역 한글만 추가로 번역됨                         │
└─────────────────────────────────────────────────────────────┘
```

## 관련 파일

| 파일 | 역할 |
|------|------|
| `backend/app/routers/slides.py` | 파이프라인 오케스트레이션, **수정됨** |
| `backend/app/services/slide_translation/image_pipeline.py` | VLM 번역/OCR/Overlay 처리 |
| `backend/app/services/slide_translation/pdf_pipeline.py` | PDF Layer 파이프라인 |

---

## 추가 수정 사항

### PDF Layer 파이프라인

| 문제 | 원인 | 수정 |
|------|------|------|
| prefix 영역 한글 잔존 | `keep_prefix=True`면 `x0 + prefix_width`부터 redact | `pdf_text_replacer.py`: redaction bbox에 padding 추가 |

### OCR/Image 파이프라인

| 문제 | 원인 | 수정 |
|------|------|------|
| symbol 영역 한글 잔존 | 마스크/배경복원이 `render_bbox` 사용 | `image_pipeline.py`: 마스크/배경복원에 원본 bbox + padding 사용 |

---

## 테스트

수정 후 다음을 확인:

1. PDF Layer 페이지: 텍스트 레이어 번역 정상
2. OCR 페이지: 이미지 기반 번역 정상
3. **image_region_pages**: 텍스트 레이어 번역 + 이미지 영역 번역 모두 정상
4. 한글 잔상 없음

---

## 관련 문서

- [PIPELINE_FLOW.md](./PIPELINE_FLOW.md) - 전체 파이프라인 흐름
- [pipeline-memory.md](./pipeline-memory.md) - Stage 기반 배치 구조
