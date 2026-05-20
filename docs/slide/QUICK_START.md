# Quick Start - 슬라이드 번역 파이프라인

> 처음 사용하는 개발자를 위한 빠른 시작 가이드

---

## 1. 환경 설정

### 1.1 Python 의존성 설치

```bash
cd backend
pip install -r requirements.txt
```

**주요 패키지:**
| 패키지 | 용도 |
|--------|------|
| `PyMuPDF (fitz)` | PDF 텍스트 추출/교체 |
| `transformers` | VLM 모델 로드 |
| `bitsandbytes` | 4bit 양자화 |
| `surya-ocr` | 이미지 OCR |
| `Pillow` | 이미지 처리 |

### 1.2 모델 다운로드

```bash
# 프로젝트 루트에서
npm run setup
```

또는 수동 다운로드:
```bash
# VLM 모델 (Qwen3-VL-4B-Instruct)
# 자동으로 HuggingFace에서 다운로드됨 (~3GB)

# Surya OCR
# 첫 실행 시 자동 다운로드 (~2GB)
```

### 1.3 환경 변수 (.env)

```bash
# backend/.env 또는 프로젝트 루트/.env

# 슬라이드 파이프라인
USE_NEW_SLIDE_PIPELINE=true
OCR_CHUNK_SIZE=5

# 폰트 경로 (Windows)
KOREAN_FONT_PATH=C:/Windows/Fonts/malgun.ttf

# 폰트 경로 (Linux/Mac)
# KOREAN_FONT_PATH=/usr/share/fonts/truetype/nanum/NanumGothic.ttf
```

---

## 2. 서버 실행

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

서버 확인:
```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

---

## 3. API 사용법

### 3.1 PDF 업로드 및 번역

```bash
curl -X POST http://localhost:8000/slides/upload \
  -F "file=@lecture.pdf"
```

**응답:**
```json
{
  "slide_id": "63b275cd",
  "status": "processing",
  "message": "Slide uploaded successfully",
  "total_pages": 4
}
```

### 3.2 번역 상태 확인

```bash
curl http://localhost:8000/slides/63b275cd/status
```

**응답 (처리 중):**
```json
{
  "slide_id": "63b275cd",
  "status": "processing",
  "progress": 50,
  "current_stage": "translating"
}
```

**응답 (완료):**
```json
{
  "slide_id": "63b275cd",
  "status": "completed",
  "progress": 100,
  "output_path": "/uploads/translated/63b275cd_translated.pdf"
}
```

### 3.3 번역된 PDF 다운로드

```bash
curl -O http://localhost:8000/slides/63b275cd/download
```

---

## 4. 파이프라인 흐름

**핵심 설계: extract → translate → apply 분리**

```
PDF 업로드
    │
    ▼
┌─────────────────────────────────────┐
│ [Stage 1] 페이지 분류                │
│  - 텍스트 레이어 있음 → PDF Layer    │
│  - 텍스트 레이어 없음 → OCR          │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ [Stage 2] 텍스트 추출 (Extract)      │
│  - PDFLayerPipeline.extract()       │
│  - OCRPipeline.extract() (Surya)    │
│  - OCR 보정 (ocr_corrections.csv)   │
│  ↓ list[TextBlock] 반환             │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ [Stage 3] 공통 번역 (Translate)      │
│  - translate_blocks() - VLM 번역    │
│  - 용어집 적용 (term_corrections)   │
│  - PDF + OCR 블록 함께 번역         │
│  ↓ TranslationResult 반환           │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ [Stage 4] 번역 적용 (Apply)          │
│  - PDFLayerPipeline.apply()         │
│  - OCRPipeline.apply()              │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ [Stage 5] PDF 합성                   │
│  - PDF Layer + OCR 이미지 합성      │
└─────────────────────────────────────┘
    │
    ▼
번역된 PDF 출력
```

**장점:**
- PDF Layer와 OCR이 동일한 용어집과 문서 맥락 공유
- 용어 일관성 향상 (예: "기회비용"이 항상 "Opportunity Cost"로 번역)

---

## 5. 출력 파일 구조

```
uploads/
├── slides/
│   └── 63b275cd.pdf              # 원본 PDF
│
├── translated/
│   ├── 63b275cd_translated.pdf   # 번역된 PDF
│   ├── pdf_layer_pipeline.log    # 파이프라인 로그
│   ├── source_texts.json         # 원본 텍스트 (디버깅용)
│   └── translations.json         # 번역 결과 (디버깅용)
│
└── cache/
    └── 63b275cd/
        ├── ocr_000.json          # 페이지별 OCR 캐시
        └── translate_000.json    # 페이지별 번역 캐시
```

---

## 6. 번역 결과 확인

### 6.1 로그 확인

```bash
cat uploads/translated/pdf_layer_pipeline.log
```

```
[20:47:54.740] ============================================================
[20:47:54.740] PDF Layer Translation Pipeline
[20:47:54.740] Input: uploads/slides/63b275cd.pdf
[20:47:54.740] ============================================================
[20:47:54.740] [Stage 1] Classifying pages...
[20:47:54.782]   - Total pages: 4
[20:47:54.782]   - PDF Layer pages: 3
[20:47:54.782]   - OCR pages: 1
[20:47:54.782] [Stage 2] Extracting text blocks...
[20:47:54.799]   - PDF blocks: 15
[20:47:54.850]   - OCR blocks: 5
[20:48:00.000] [Stage 3] Translating all blocks...
[20:48:30.000]   - Translated: 20/20
[20:48:30.100] [Stage 4] Applying translations...
[20:48:30.500]   - PDF Layer: 15 blocks applied
[20:48:31.000]   - OCR: 5 blocks rendered
```

### 6.2 번역 결과 확인

```bash
cat uploads/translated/translations.json | jq '.[0]'
```

```json
{
  "block_id": "pdf_p0_b0",
  "source": "pdf",
  "page": 0,
  "original": "경제학의 10대 기본원리",
  "translated": "10 Fundamental Principles of Economics",
  "role": "heading"
}
```

---

## 7. 용어집 사용

### 7.1 용어집 위치

```
config/glossary.csv    # 한국어 → 영어 번역 용어
config/ocr_corrections.csv     # OCR 오타 → 교정 (선택)
```

### 7.2 용어 추가 (glossary.csv)

```csv
korean,english
한계비용,Marginal Cost
기회비용,Opportunity Cost
# 새 용어 추가
수요곡선,Demand Curve
```

### 7.3 OCR 오타 교정 (ocr_corrections.csv)

```csv
typo,correct
# OCR이 잘못 인식한 한글 → 올바른 한글
기게학습,기계학습
컴뷰터,컴퓨터
```

### 7.4 주의사항

- 2글자 이상만 등록 (단일 글자는 무시됨)
- 긴 용어가 먼저 매칭됨
- 파일 수정 후 서버 재시작 불필요 (자동 리로드)
- OCR 보정은 번역 전 extract 단계에서 적용됨

---

## 8. Python 코드에서 직접 호출

### 8.1 전체 파이프라인 (권장)

```python
from app.services.slide_translation import (
    PDFLayerPipeline,
    OCRPipeline,
    translate_blocks,
)

# 파이프라인 생성
pdf_pipeline = PDFLayerPipeline(output_dir="uploads/translated")
ocr_pipeline = OCRPipeline()

# Stage 2: Extract
pdf_blocks = pdf_pipeline.extract("lecture.pdf")
ocr_blocks = ocr_pipeline.extract([(0, "page_0.png"), (1, "page_1.png")])

# 모든 블록 합치기
all_blocks = pdf_blocks + ocr_blocks

# Stage 3: Translate (공통 번역)
translations = translate_blocks(all_blocks, target_lang="en")

# Stage 4: Apply
pdf_pipeline.apply("lecture.pdf", pdf_blocks, translations.translations, "output.pdf")
ocr_pipeline.apply({0: "page_0.png"}, ocr_blocks, translations.translations, "output_dir")
```

### 8.2 PDF Layer만 사용 (간단한 경우)

```python
from app.services.slide_translation import PDFLayerPipeline

# 파이프라인 생성
pipeline = PDFLayerPipeline(output_dir="uploads/translated")

# 간편 실행 (extract → translate → apply 자동)
result = pipeline.run(
    pdf_path="uploads/slides/lecture.pdf",
    target_lang="en"
)

# 결과 확인
print(f"Success: {result['success']}")
print(f"Output: {result['output_path']}")
print(f"Translated: {result['translated_blocks']}/{result['total_blocks']}")
```

---

## 9. 다음 단계

- [PIPELINE_FLOW.md](./PIPELINE_FLOW.md) - 전체 파이프라인 상세 흐름
- [STAGE_BATCH_ARCHITECTURE.md](./STAGE_BATCH_ARCHITECTURE.md) - Stage 기반 배치 + GPU 관리
- [pdf-translation-pipeline.md](./pdf-translation-pipeline.md) - PDF Layer 파이프라인 상세
- [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) - 문제 해결 가이드
- [TODO_OCR_POSTPROCESS.md](./TODO_OCR_POSTPROCESS.md) - OCR 후처리 개선 (향후 과제)

---

## 10. 자주 묻는 질문

### Q: 번역이 너무 느려요
**A:** VLM 모델 로드에 ~10초, 페이지당 번역에 ~3초 소요됩니다. 정상입니다.

### Q: CUDA out of memory 에러가 발생해요
**A:** Surya와 VLM이 동시에 로드되면 OOM 발생합니다. 새 아키텍처에서는 Stage별로 순차 처리하여 이 문제를 방지합니다.

### Q: 특정 용어가 잘못 번역돼요
**A:** `config/glossary.csv`에 올바른 번역을 추가하세요. translate_blocks()에서 자동으로 적용됩니다.

### Q: OCR 인식이 틀려서 번역이 이상해요
**A:** `config/ocr_corrections.csv`에 OCR 오타 교정을 추가하세요. 또는 [TODO_OCR_POSTPROCESS.md](./TODO_OCR_POSTPROCESS.md)의 향후 개선 방안을 참고하세요.

### Q: 한글이 일부 남아있어요
**A:** [fix-korean-remnants-bug.md](./fix-korean-remnants-bug.md) 참고. bbox padding 관련 이슈일 수 있습니다.

### Q: Windows에서 폰트 에러가 발생해요
**A:** `.env`에서 `KOREAN_FONT_PATH`가 올바른지 확인하세요:
```bash
KOREAN_FONT_PATH=C:/Windows/Fonts/malgun.ttf
```

### Q: PDF Layer와 OCR이 다른 용어로 번역돼요
**A:** 새 아키텍처에서는 translate_blocks()로 공통 번역하므로 용어 일관성이 보장됩니다. 기존 코드라면 새 파이프라인을 사용하세요.
