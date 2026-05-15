# Slide Translation Module Dependency Report

> **최종 업데이트**: 2025-05-14

## 개요: 두 가지 파이프라인 병행 사용

| 파이프라인 | 메인 파일 | 용도 | 번역 모델 |
|-----------|----------|------|----------|
| **PDF Layer** | `pdf_pipeline.py` | PDF 텍스트 레이어 직접 수정 | VLM (Qwen2.5-VL) |
| **Image OCR** | `image_pipeline.py` | 이미지 OCR + 오버레이 | VLM (Qwen2.5-VL) |

---

## 현재 파일 구조 (8개)

```
backend/app/services/slide_translation/
├── __init__.py            # 모듈 export
├── image_pipeline.py      # VLM 모델 관리 + OCR/번역/Overlay 처리
├── pdf_pipeline.py        # PDF 텍스트 레이어 번역 파이프라인
├── pdf_text_extractor.py  # PDF에서 한글 텍스트 블록 추출
├── pdf_text_replacer.py   # PDF 텍스트 교체, multi-color 렌더링
├── pdf_font_handler.py    # 한글→영어 폰트 매핑, 색상 변환
├── bbox_analyzer.py       # 휴리스틱 레이아웃 분석
└── term_corrections.py    # CSV 기반 용어집

config/
└── term_corrections.csv   # 537개 한국어-영어 용어 매핑
```

---

## 호출 흐름

### Image OCR 파이프라인

```
slides.py (router)
└── image_pipeline.py
    ├── batch_ocr_surya()      # Surya OCR 배치 실행 → 언로드
    ├── batch_translate_vlm()  # VLM 번역 배치 실행 (Qwen2.5-VL)
    │   └── translate_text_vlm()  # VLM 모델 호출
    │   └── term_corrections.py   # 용어집 프롬프트 포함
    └── batch_overlay()        # 이미지에 텍스트 오버레이 (CPU)
```

### PDF Layer 파이프라인

```
slides.py (router)
└── pdf_pipeline.py (메인 오케스트레이터)
    ├── pdf_text_extractor.py  # PDF 텍스트 추출
    ├── bbox_analyzer.py       # 휴리스틱 레이아웃 분석
    ├── image_pipeline.py      # translate_text_vlm() → VLM 번역
    │   └── term_corrections.py   # 용어집 프롬프트 포함
    ├── pdf_text_replacer.py   # PDF 텍스트 교체
    │   └── pdf_font_handler.py   # 폰트 매핑
```

---

## 모듈 상세

### image_pipeline.py

**VLM 모델 관리 + OCR/번역/Overlay 처리:**

| 함수 | 역할 |
|------|------|
| `get_vlm_model()` | VLM 모델 로드 (싱글톤, 4bit) |
| `is_vlm_loaded()` | VLM 로드 상태 확인 |
| `unload_vlm_model()` | VLM 메모리 해제 |
| `translate_text_vlm(prompt)` | VLM 기반 번역 |
| `stage_ocr_surya()` | 단일 페이지 OCR |
| `stage_translate()` | 단일 페이지 번역 |
| `stage_overlay()` | 단일 페이지 오버레이 |
| `batch_ocr_surya()` | 배치 OCR |
| `batch_translate_vlm()` | 배치 VLM 번역 |
| `batch_overlay()` | 배치 오버레이 |
| `clear_cache()` | 캐시 정리 |

### pdf_pipeline.py

**PDF Layer 파이프라인 오케스트레이터:**

| 클래스/함수 | 역할 |
|------------|------|
| `PDFLayerPipeline` | 파이프라인 메인 클래스 |
| `run()` | 전체 파이프라인 실행 |
| `_translate_texts()` | 텍스트 번역 처리 |
| `_translate_batch()` | 배치 번역 (VLM 호출) |
| `_apply_merge_groups()` | 휴리스틱 병합 적용 |

### term_corrections.py

**CSV 기반 용어집 (537개 용어):**

| 함수 | 역할 |
|------|------|
| `load_term_corrections()` | CSV 파일 로드 |
| `get_mandatory_terms()` | 필수 용어 목록 반환 |
| `get_terms_in_text(text)` | 텍스트에서 해당 용어 추출 |
| `build_term_replacer()` | 번역 후 용어 교정기 생성 |
| `replace_terms_in_text()` | 번역 결과 용어 교정 |

### bbox_analyzer.py

**휴리스틱 기반 레이아웃 분석:**

| 함수 | 역할 |
|------|------|
| `analyze_page_layout()` | 페이지 레이아웃 분석 |

분석 결과:
- `on_image_background`: 이미지 위 텍스트 여부 (휴리스틱 추정)
- `expand_allowed`: bbox 확장 허용 여부
- `keep_prefix`: prefix 유지 여부

### pdf_text_extractor.py

**PDF 텍스트 추출:**

| 함수 | 역할 |
|------|------|
| `check_pdf_has_text_layer()` | 텍스트 레이어 존재 확인 |
| `extract_korean_texts_for_translation()` | 한글 텍스트 블록 추출 |
| `_group_adjacent_lines()` | 인접 라인 그룹화 |
| `_infer_line_role()` | 텍스트 역할 추론 |

### pdf_text_replacer.py

**PDF 텍스트 교체:**

| 함수 | 역할 |
|------|------|
| `replace_texts_in_pdf()` | 메인 교체 함수 |
| `replace_text_block()` | 단일 블록 교체 |
| `_render_multi_color_text()` | 다중 색상 텍스트 렌더링 |
| `_is_invalid_for_rendering()` | 렌더링 유효성 검사 |

### pdf_font_handler.py

**폰트 처리:**

| 함수 | 역할 |
|------|------|
| `map_korean_to_english_font()` | 한글→영어 폰트 매핑 |
| `int_color_to_rgb()` | 정수 색상 → RGB 변환 |
| `rgb_to_int_color()` | RGB → 정수 색상 변환 |
| `estimate_text_width()` | 텍스트 너비 추정 |

---

## 의존성 그래프

```
slides.py (router)
    │
    ├──→ pdf_pipeline.py
    │        │
    │        ├──→ pdf_text_extractor.py
    │        ├──→ bbox_analyzer.py
    │        ├──→ image_pipeline.py (translate_text_vlm)
    │        │        └──→ term_corrections.py
    │        └──→ pdf_text_replacer.py
    │                 └──→ pdf_font_handler.py
    │
    └──→ image_pipeline.py
             │
             ├──→ term_corrections.py
             └──→ (Surya OCR - 외부 라이브러리)
```

---

## 파이프라인 VRAM 구조

```
VLM 번역 → 언로드 → Surya OCR → 언로드 → VLM 번역 → 언로드 → Overlay(CPU)
  ~4GB              ~4GB              ~4GB
```

- **VLM**: Qwen2.5-VL-3B-Instruct (4bit 양자화)
- **Surya**: Detection + Recognition Predictor

**핵심 원칙:**
- VLM과 Surya 동시 로드 금지
- Stage 전환 시 명시적 메모리 해제

---

## 삭제된 파일 (이전 버전에서 제거됨)

| 파일 | 제거 이유 |
|------|----------|
| `nmt_slide_service.py` | VLM으로 대체 |
| `llm_client.py` | VLM으로 대체 |
| `text_utils.py` | 불필요 |
| `glossary_builder.py` | CSV 용어집으로 대체 |
| 기타 19개 파일 | 리팩토링으로 통합/제거 |

---

## 용어집 구조

### term_corrections.csv

```csv
Korean,English
미시경제학,Microeconomics
거시경제학,Macroeconomics
한계비용,Marginal Cost
...
(총 537개 용어)
```

### 사용 방식

1. **프롬프트 포함**: 번역 시 관련 용어를 프롬프트에 자동 포함
2. **후처리 교정**: 번역 결과에서 용어 일관성 교정
