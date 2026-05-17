# 강의자료 번역 파이프라인 문서

## 개요

PDF 강의자료를 한국어 → 영어로 번역하는 파이프라인입니다.

---

## 진입점

```python
# backend/app/routers/slides.py

# 1. API 엔드포인트 (파일 업로드)
POST /slides/upload
async def upload_slide(file: UploadFile) -> dict

# 2. 번역 처리 (내부 호출)
async def process_slide_pdf_layer(slide_id: str, pdf_path: Path)
```

**호출 흐름 (통합 번역 파이프라인):**
```
upload_slide()
  → process_slide_pdf_layer()
    → [Stage 1] 페이지 분류
    → [Stage 2] 텍스트 추출 (extract)
        ├─ PDFLayerPipeline.extract() → list[TextBlock]
        └─ OCRPipeline.extract() → list[TextBlock]
    → [Stage 3] 공통 번역 (translate_blocks)
        └─ PDF + OCR 블록 함께 번역 (문서 맥락 공유)
    → [Stage 4] 번역 적용 (apply)
        ├─ PDFLayerPipeline.apply()
        └─ OCRPipeline.apply()
    → [Stage 5] PDF 합성
```

**핵심 설계: extract → translate → apply 분리**
```
[기존 문제]
PDF Layer와 OCR이 각각 독립적으로 번역
→ 용어 일관성 부족, 문서 맥락 공유 안 됨

[신규 구조]
모든 텍스트 먼저 추출 → 공통 번역 → 각자 적용
→ 문서 전체 맥락 공유, 용어 일관성 향상
```

**파이프라인 VRAM 구조:**
```
Surya OCR (~4GB) - extract 단계에서 사용
    ↓ 언로드
VLM (Qwen3-VL-4B, 4bit ~4GB) - translate 단계에서 사용
    ↓ 언로드
Overlay (CPU only) - apply 단계
```

---

## 문서 목록

| 문서 | 설명 | 읽는 순서 |
|------|------|----------|
| [QUICK_START.md](./QUICK_START.md) | **처음 사용자를 위한 빠른 시작 가이드** | **1 (필독)** |
| [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) | **문제 해결 가이드** | **2 (필독)** |
| [PIPELINE_FLOW.md](./PIPELINE_FLOW.md) | 전체 파이프라인 흐름도 + 파일 구조 | 3 |
| [STAGE_BATCH_ARCHITECTURE.md](./STAGE_BATCH_ARCHITECTURE.md) | Stage 기반 배치 + GPU 메모리 관리 | 4 |
| [pdf-translation-pipeline.md](./pdf-translation-pipeline.md) | PDF Layer 파이프라인 상세 | 5 |
| [DEPENDENCY_REPORT.md](./DEPENDENCY_REPORT.md) | 모듈 의존성 + 파일 구조 | 6 |
| [TODO_OCR_POSTPROCESS.md](./TODO_OCR_POSTPROCESS.md) | OCR 후처리 개선 (향후 과제) | 참고 |
| [batch-stage-refactor.md](./batch-stage-refactor.md) | 리팩토링 배경 (Before/After) | 참고 |
| [fix-korean-remnants-bug.md](./fix-korean-remnants-bug.md) | 한글 잔상 버그 수정 | 참고 |

---

## 핵심 파일

```
backend/app/
├── routers/
│   └── slides.py                  # API + Stage 오케스트레이션
│
└── services/
    └── slide_translation/
        ├── __init__.py            # 모듈 export
        │
        │  # 공통 모듈
        ├── models.py              # TextBlock, FontInfo, TranslationResult
        ├── translator.py          # translate_blocks() 공통 번역 함수
        │
        │  # PDF Layer 파이프라인
        ├── pdf_pipeline.py        # PDFLayerPipeline (extract/apply)
        ├── pdf_text_extractor.py  # 텍스트 + bbox 추출
        ├── pdf_text_replacer.py   # Redaction + 텍스트 삽입
        ├── pdf_font_handler.py    # 폰트 매핑
        ├── bbox_analyzer.py       # 휴리스틱 레이아웃 분석
        │
        │  # OCR 파이프라인
        ├── image_pipeline.py      # OCRPipeline (extract/apply) + VLM 관리
        │
        │  # 용어집
        └── term_corrections.py    # 번역 용어집 + OCR 보정
```

### 모듈 역할

| 모듈 | 역할 |
|------|------|
| `models.py` | **공통 데이터 모델** (TextBlock, FontInfo, TranslationResult) |
| `translator.py` | **공통 번역 함수** (translate_blocks) - PDF/OCR 블록 통합 번역 |
| `pdf_pipeline.py` | **PDF Layer 파이프라인** - extract(), apply() |
| `image_pipeline.py` | **OCR 파이프라인** - OCRPipeline.extract(), apply() + VLM 관리 |
| `term_corrections.py` | 번역 용어집 (537개) + OCR 오타 보정 |

### TextBlock 데이터 구조

PDF Layer와 OCR 파이프라인의 공통 데이터 구조:

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
    font: Optional[FontInfo]
    line_colors: list[int]

    # OCR 전용
    confidence: Optional[float]  # 진단용 (스킵 기준 아님)
```

### VLM 모델 (Qwen3-VL-4B)

**Qwen3-VL-4B-Instruct** 사용, 4bit 양자화:
- `get_vlm_model()`: 모델 로드 (싱글톤)
- `unload_vlm_model()`: 메모리 해제
- `translate_text_vlm(prompt)`: VLM 기반 번역

### 용어집 (term_corrections.csv)

`config/term_corrections.csv`에서 537개 용어 매핑 로드:
- `load_term_corrections()`: CSV 로드
- `get_terms_in_text()`: 텍스트에서 용어 추출
- `build_term_replacer()`: 번역 후 용어 교정기 생성

### OCR 보정 (ocr_corrections.csv)

`config/ocr_corrections.csv`에서 OCR 오타 보정 매핑:
- `load_ocr_corrections()`: CSV 로드
- `correct_ocr_text()`: OCR 텍스트 보정
- **TODO**: fuzzy matching, 맞춤법 검사기 통합 필요 (TODO_OCR_POSTPROCESS.md 참조)

---

## GPU 메모리 관리

```
[Stage 순서 - 신규 아키텍처]

Stage 2: Extract (텍스트 추출)
    Surya OCR (~4GB) - OCR 페이지 처리
        ↓ 언로드

Stage 3: Translate (공통 번역)
    VLM (Qwen3-VL-4B, 4bit ~4GB)
        - PDF Layer 블록 번역
        - OCR 블록 번역
        - 용어집 공유, 문서 맥락 공유
        ↓ 언로드

Stage 4: Apply (번역 적용)
    PDF Layer: PyMuPDF (CPU)
    OCR: PIL/OpenCV (CPU)
```

- **Surya와 VLM 동시 로드 금지** (각각 ~4GB)
- Stage 전환 시 `gc.collect()` + `torch.cuda.empty_cache()`
- 모델 로드는 필요 시 1회만

---

## 모델 다운로드 (npm run setup)

| 모델 | 용도 | 크기 |
|------|------|------|
| ASR (Whisper) | 실시간 음성인식 | ~1GB |
| NMT 600M | 실시간 번역 | ~600MB |
| **VLM (Qwen3-VL-4B)** | **슬라이드 번역 (품질 우선)** | **~3GB (4bit)** |
| Surya OCR | 텍스트 인식 | ~2GB |

**총 예상 용량: ~6.6GB**

---

## 설정 옵션 (.env)

| 환경변수 | 기본값 | 설명 |
|---------|--------|------|
| `USE_NEW_SLIDE_PIPELINE` | true | 신규 파이프라인 사용 |
| `OCR_CHUNK_SIZE` | 5 | Surya 배치 크기 |
| `KOREAN_FONT_PATH` | C:/Windows/Fonts/malgun.ttf | 한글 폰트 |

---

## PDF Layer vs OCR 파이프라인

| 항목 | PDF Layer | OCR |
|------|-----------|-----|
| **텍스트 정확도** | 100% (원본 추출) | OCR 오류 가능 |
| **bbox 정확도** | 정확 (PDF 메타데이터) | 추정값 (이미지 분석) |
| **폰트/크기** | 정확 | 추정 |
| **속도** | 빠름 | 느림 (이미지 변환 + OCR) |
| **출력 품질** | 깔끔 (벡터 유지) | 이미지 기반 |
| **번역** | translate_blocks() 공유 | translate_blocks() 공유 |

**PDF Layer 우선 사용 이유**: 품질이 우수하고 속도가 빠름
**OCR은 fallback**: PDF에 텍스트 레이어가 없거나 이미지로 임베딩된 경우

### extract → translate → apply 흐름

```
[Extract]
PDFLayerPipeline.extract(pdf_path)
    → list[TextBlock] (source="pdf")

OCRPipeline.extract(image_paths)
    → list[TextBlock] (source="ocr")

[Translate]
all_blocks = pdf_blocks + ocr_blocks
translate_blocks(all_blocks, target_lang="en")
    → TranslationResult {block_id: translated_text}

[Apply]
PDFLayerPipeline.apply(pdf_path, pdf_blocks, translations, output_path)
    → 번역된 PDF

OCRPipeline.apply(image_paths, ocr_blocks, translations, output_dir)
    → 번역된 이미지들
```

---

## 페이지 분류 기준

| 분류 | 조건 | 처리 방식 |
|------|------|----------|
| `pdf_layer_pages` | 텍스트 블록 ≥ 2개 | PDF Layer extract → translate → apply |
| `ocr_pages` | 텍스트 블록 < 2개 | OCR extract → translate → apply |
| `image_region_pages` | 텍스트 블록 ≥ 2개 AND 이미지 ≥ 10% | PDF Layer + OCR 병행 |

---

## 캐시 구조

```
uploads/cache/{slide_id}/
├── ocr_000.json       # 페이지 0 OCR 결과
├── ocr_001.json       # 페이지 1 OCR 결과
├── translate_000.json # 페이지 0 번역 결과
└── translate_001.json # 페이지 1 번역 결과
```

중간 실패 시 캐시된 결과 재사용 가능.
