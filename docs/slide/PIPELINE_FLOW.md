# 강의자료 번역 파이프라인 흐름

## 개요

PDF 업로드부터 번역된 PDF 생성까지의 전체 파이프라인 흐름을 정리합니다.

**핵심 아키텍처: extract → translate → apply 분리**

---

## 전체 흐름

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         PDF 업로드                                       │
│                    slides.py: upload_slide()                             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  [Stage 1] 페이지 분류 (slides.py: process_slide_pdf_layer)              │
│                                                                          │
│  for page in doc:                                                        │
│    ├─ text_blocks >= 2 → pdf_layer_pages (텍스트 레이어 있음)            │
│    │   └─ image_ratio >= 10% → image_region_pages (OCR fallback 필요)   │
│    └─ text_blocks < 2 → ocr_pages (텍스트 레이어 없음)                   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  [Stage 2] 텍스트 추출 (Extract)                                         │
│                                                                          │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐       │
│  │  PDFLayerPipeline.extract() │  │  OCRPipeline.extract()      │       │
│  │  → list[TextBlock]          │  │  → list[TextBlock]          │       │
│  │  (source="pdf")             │  │  (source="ocr")             │       │
│  └─────────────────────────────┘  └─────────────────────────────┘       │
│                    │                            │                        │
│                    └────────────┬───────────────┘                        │
│                                 ▼                                        │
│                     all_blocks = pdf_blocks + ocr_blocks                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  [Stage 3] 공통 번역 (Translate)                                         │
│                                                                          │
│  translator.py: translate_blocks(all_blocks, target_lang="en")           │
│                                                                          │
│  ├─ PDF/OCR 블록 분리 배치 (OCR 노이즈 격리)                             │
│  ├─ 용어집 공유 (term_corrections.csv)                                   │
│  ├─ 문서 전체 맥락 공유 → 용어 일관성 향상                               │
│  └─ VLM 호출 (Qwen3-VL-4B 4bit)                                         │
│                                                                          │
│  결과: TranslationResult {block_id: translated_text}                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  [Stage 4] 번역 적용 (Apply)                                             │
│                                                                          │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐       │
│  │  PDFLayerPipeline.apply()   │  │  OCRPipeline.apply()        │       │
│  │  → 번역된 PDF               │  │  → 번역된 이미지들          │       │
│  │                             │  │                             │       │
│  │  • Redaction (원본 제거)    │  │  • 배경 복원 (단색/inpaint) │       │
│  │  • insert_textbox()         │  │  • 텍스트 렌더링            │       │
│  └─────────────────────────────┘  └─────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  [Stage 5] PDF 합성                                                     │
│                                                                          │
│  PDF Layer 결과 + OCR Overlay → Hybrid PDF                              │
│  └─ PIL Image → PDF 변환                                                │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                        translated_{slide_id}.pdf (최종)
```

---

## Stage 2: Extract (텍스트 추출)

### PDF Layer Extract

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PDFLayerPipeline.extract(pdf_path) → list[TextBlock]                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Step 1: 텍스트 레이어 확인                                              │
│    └─ pdf_text_extractor.py: check_pdf_has_text_layer()                 │
│                                                                          │
│  Step 2: 한글 텍스트 추출                                                │
│    └─ pdf_text_extractor.py: extract_korean_texts_for_translation()     │
│       ├─ PyMuPDF page.get_text("dict")로 텍스트 + bbox 추출             │
│       ├─ 한글 포함 블록만 필터링                                         │
│       └─ prefix 분리 (bullet 등)                                        │
│                                                                          │
│  Step 3: TextBlock 변환                                                  │
│    └─ block_id = "pdf_p{page}_b{block}"                                 │
│    └─ source = "pdf"                                                    │
│    └─ font, line_colors 등 PDF 메타데이터 보존                          │
│                                                                          │
│  결과: list[TextBlock] (번역 없이 원문만)                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### OCR Extract

```
┌─────────────────────────────────────────────────────────────────────────┐
│  OCRPipeline.extract(image_paths) → list[TextBlock]                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Step 1: PDF → 이미지 변환                                               │
│    └─ PyMuPDF page.get_pixmap() → PNG                                   │
│                                                                          │
│  Step 2: Surya OCR (~4GB VRAM)                                          │
│    ├─ FoundationPredictor (한 번 로드)                                   │
│    ├─ DetectionPredictor → 텍스트 영역 감지                              │
│    └─ RecognitionPredictor → 텍스트 인식 + bbox + confidence            │
│                                                                          │
│  Step 3: OCR 보정 (번역 전)                                              │
│    └─ term_corrections.py: correct_ocr_text()                           │
│    └─ ocr_corrections.csv에서 오타 → 정상 한글 매핑                     │
│                                                                          │
│  Step 4: TextBlock 변환                                                  │
│    └─ block_id = "ocr_p{page}_r{region}"                                │
│    └─ source = "ocr"                                                    │
│    └─ confidence 포함 (진단용, 스킵 기준 아님)                          │
│    └─ font = None (OCR은 폰트 정보 없음)                                │
│                                                                          │
│  결과: list[TextBlock] (번역 없이 원문만)                                │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Stage 3: Translate (공통 번역)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  translator.py: translate_blocks(blocks, target_lang, chunk_size)       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. PDF/OCR 블록 분리                                                    │
│     ├─ pdf_blocks = [b for b in blocks if b.source == "pdf"]            │
│     └─ ocr_blocks = [b for b in blocks if b.source == "ocr"]            │
│     (OCR 노이즈가 PDF 번역에 영향 주지 않도록 격리)                       │
│                                                                          │
│  2. 용어집 추출                                                          │
│     └─ term_corrections.py: get_terms_in_text(all_text)                 │
│     └─ 모든 배치에서 공유 → 용어 일관성                                  │
│                                                                          │
│  3. 청크 생성 (페이지 단위)                                              │
│     └─ chunk_size 이하로 페이지 경계 유지                                │
│                                                                          │
│  4. VLM 호출 (Qwen3-VL-4B 4bit)                                         │
│     └─ image_pipeline.py: translate_text_vlm(prompt)                    │
│     └─ 프롬프트에 용어집 + 번역 규칙 포함                                │
│                                                                          │
│  결과: TranslationResult                                                 │
│     ├─ translations: {block_id: translated_text}                        │
│     └─ failed_ids: [실패한 block_id들]                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 번역 프롬프트 구조

```
Translate the following Korean texts to EN.
This is for slide/PDF layout replacement, so translations must be concise.

=== MANDATORY TERMINOLOGY ===
  기계학습 = Machine learning
  한계비용 = Marginal cost
  ...
=== END TERMINOLOGY ===

Rules by text type:
- TITLE: Use a concise slide title.
- HEADING: Use a clear, compact section heading.
- BODY: Translate naturally but compactly.
...

Texts to translate:
[pdf_p0_b1] (TITLE): 경제학의 기본 원리
[pdf_p0_b2] (BODY): 시장 경제에서 가격은...
[ocr_p1_r0] (BODY): 그래프에서 보이는 것처럼...

Translations:
```

---

## Stage 4: Apply (번역 적용)

### PDF Layer Apply

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PDFLayerPipeline.apply(pdf_path, blocks, translations, output_path)    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. TextBlock + translations → legacy 형식 변환                         │
│     └─ block.with_translation(translations[block.block_id])             │
│                                                                          │
│  2. Redaction 준비                                                       │
│     └─ page.add_redact_annot(rect, fill=color)                          │
│     └─ 원본 텍스트 영역 배경색으로 채움                                  │
│                                                                          │
│  3. Redaction 적용                                                       │
│     └─ page.apply_redactions()                                          │
│     └─ 원본 텍스트 제거                                                  │
│                                                                          │
│  4. 번역된 텍스트 삽입                                                   │
│     ├─ page.insert_textbox() (단일 색상)                                │
│     └─ _render_multi_color_text() (다중 색상)                           │
│                                                                          │
│  결과: 번역된 PDF 파일                                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### OCR Apply

```
┌─────────────────────────────────────────────────────────────────────────┐
│  OCRPipeline.apply(image_paths, blocks, translations, output_dir)       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  페이지별 처리:                                                          │
│                                                                          │
│  1. 배경 처리 (원문 제거)                                                │
│     ├─ 단색 배경: rectangle fill                                        │
│     └─ 복잡한 배경: cv2.inpaint()                                       │
│                                                                          │
│  2. 폰트 추정                                                            │
│     └─ bbox 높이에서 크기 역산                                           │
│     └─ 색상: 배경 대비로 결정 (명도 기반)                                │
│                                                                          │
│  3. 텍스트 렌더링                                                        │
│     └─ PIL ImageDraw.text()                                             │
│     └─ 오버플로우 처리: 줄바꿈 + 폰트 축소 (최소 8pt)                    │
│                                                                          │
│  결과: {page_idx: output_path} 딕셔너리                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## GPU 메모리 관리

```
시간 →

[Stage 2]              [Stage 3]              [Stage 4-5]
Extract                Translate              Apply
    │                      │                      │
    ▼                      ▼                      ▼
┌──────────┐          ┌──────────┐           ┌──────────┐
│  Surya   │          │   VLM    │           │   CPU    │
│  OCR     │    →     │ Qwen3-VL │     →     │   only   │
│  ~4GB    │          │  ~4GB    │           │          │
└──────────┘          └──────────┘           └──────────┘
     ↓                     ↓
  언로드              GPU캐시 클리어
  GPU캐시 클리어
```

**핵심 원칙:**
- Surya와 VLM 동시 로드 금지 (각각 ~4GB)
- Stage 전환 시 `gc.collect()` + `torch.cuda.empty_cache()` + `torch.cuda.synchronize()`
- 모델 로드는 Stage당 1회만

---

## 데이터 구조

### TextBlock

```python
@dataclass
class TextBlock:
    block_id: str           # "pdf_p0_b1" / "ocr_p0_r2"
    source: Literal["pdf", "ocr"]
    page: int
    text: str               # 원문 (apply까지 유지)
    bbox: tuple[float, float, float, float]
    role: str               # title, heading, body, bullet 등

    # PDF Layer 전용
    font: Optional[FontInfo]     # name, size, color
    line_colors: list[int]
    prefix_width: float
    has_multi_color: bool
    redaction_fill_color: tuple

    # OCR 전용
    confidence: Optional[float]  # 진단용 (스킵 기준 아님)
```

### TranslationResult

```python
@dataclass
class TranslationResult:
    translations: dict[str, str]  # {block_id: translated_text}
    failed_ids: list[str]         # 번역 실패한 block_id들
```

---

## 파일 구조

```
backend/app/
├── routers/
│   └── slides.py                 # 업로드 API, Stage 오케스트레이션
│
└── services/
    └── slide_translation/        # 10개 파일
        ├── __init__.py           # 모듈 export
        │
        │  # 공통 모듈
        ├── models.py             # TextBlock, FontInfo, TranslationResult
        ├── translator.py         # translate_blocks() 공통 번역 함수
        │
        │  # PDF Layer 파이프라인
        ├── pdf_pipeline.py       # PDFLayerPipeline (extract/apply)
        ├── pdf_text_extractor.py # 텍스트 + bbox 추출
        ├── pdf_text_replacer.py  # Redaction + 텍스트 삽입
        ├── pdf_font_handler.py   # 폰트 처리
        ├── bbox_analyzer.py      # 휴리스틱 레이아웃 분석
        │
        │  # OCR 파이프라인
        ├── image_pipeline.py     # OCRPipeline (extract/apply) + VLM 관리
        │
        │  # 용어집
        └── term_corrections.py   # 번역 용어집 + OCR 보정

config/
├── term_corrections.csv          # 537개 용어 매핑 (한글 → 영어)
└── ocr_corrections.csv           # OCR 오타 보정 (오타 → 정상 한글)
```

---

## 용어집 시스템

### term_corrections.csv (번역 용어집)

```csv
korean,english
미시경제학,Microeconomics
거시경제학,Macroeconomics
한계비용,Marginal Cost
```

- VLM 번역 프롬프트에 관련 용어 자동 포함
- 번역 결과 후처리로 용어 교정

### ocr_corrections.csv (OCR 보정)

```csv
typo,correct
기게학습,기계학습
컴뷰터,컴퓨터
```

- OCR 추출 직후 (번역 전) 적용
- TODO: fuzzy matching 개선 필요 (TODO_OCR_POSTPROCESS.md 참조)

---

## 한글 잔상 문제 및 해결

### 원인

| 파이프라인 | 문제 | 원인 |
|-----------|------|------|
| **PDF Layer** | prefix 영역 한글 잔존 | `keep_prefix=True`면 `x0 + prefix_width`부터 redact |
| **OCR/Image** | symbol 영역 한글 잔존 | 마스크/배경복원이 `render_bbox` 사용 |
| **image_region_pages** | 텍스트 레이어 번역 무시 | 원본 PDF에서 이미지 추출 |

### 해결

| 파이프라인 | 파일 | 수정 내용 |
|-----------|------|----------|
| **PDF Layer** | `pdf_text_replacer.py` | redaction bbox에 padding 추가 |
| **OCR/Image** | `image_pipeline.py` | 원본 bbox + padding 사용 |
| **image_region_pages** | `slides.py` | `translated_pdf_path`에서 이미지 추출 |
