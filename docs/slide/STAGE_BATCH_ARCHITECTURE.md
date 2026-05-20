# Stage 기반 배치 아키텍처

> `pipeline-memory.md`와 `slide-pdf-pipeline.md` 통합 문서

---

## 개요

GPU 메모리 효율을 위해 Stage 기반 배치 처리 구조를 사용합니다.
VLM과 Surya OCR을 동시에 로드하지 않고, Stage별로 순차 처리합니다.

**번역 모델**: Qwen3-VL-4B-Instruct (4bit 양자화, ~4GB VRAM)
**OCR 모델**: Surya (~4GB VRAM)

**핵심 설계: extract → translate → apply 분리**
```
[기존 문제]
PDF Layer와 OCR이 각각 독립적으로 번역
→ 용어 일관성 부족, 문서 맥락 공유 안 됨

[신규 구조]
모든 텍스트 먼저 추출 → 공통 번역 → 각자 적용
→ 문서 전체 맥락 공유, 용어 일관성 향상
```

---

## 파이프라인 흐름

```
┌─────────────────────────────────────────────────────────────┐
│                 process_slide_pdf_layer                      │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  [Stage 1] 페이지 분류                                       │
│  ├─ pdf_layer_pages: 텍스트 레이어 있는 페이지               │
│  ├─ ocr_pages: 텍스트 레이어 없는 페이지                     │
│  └─ image_region_pages: 이미지 영역 ≥10% (OCR fallback)      │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  [Stage 2] 텍스트 추출 (Extract)                             │
│  ├─ PDFLayerPipeline.extract() → list[TextBlock]            │
│  ├─ Surya OCR 로드 (1회)                                    │
│  ├─ OCRPipeline.extract() → list[TextBlock]                 │
│  ├─ OCR 보정 (ocr_corrections.csv)                          │
│  └─ Surya 언로드 + GPU 캐시 클리어                          │
└─────────────────────────────────────────────────────────────┘
                              │
                    all_blocks = pdf_blocks + ocr_blocks
                              │
┌─────────────────────────────────────────────────────────────┐
│  [Stage 3] 공통 번역 (Translate)                             │
│  ├─ VLM 로드 (Qwen3-VL-4B 4bit, 1회)                        │
│  ├─ translate_blocks(all_blocks, target_lang="en")          │
│  │   ├─ PDF Layer 블록 번역                                 │
│  │   └─ OCR 블록 번역                                       │
│  │   └─ 용어집 공유 (glossary.csv)                  │
│  ├─ 결과 → TranslationResult {block_id: translated_text}    │
│  └─ VLM 언로드 + GPU 캐시 클리어                            │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  [Stage 4] 번역 적용 (Apply) - CPU only                      │
│  ├─ PDFLayerPipeline.apply(pdf_path, blocks, translations)  │
│  │   ├─ 원본 텍스트 Redaction                               │
│  │   └─ 번역된 텍스트 삽입 (폰트 매핑)                      │
│  └─ OCRPipeline.apply(image_paths, blocks, translations)    │
│      ├─ 배경 복원 (inpainting)                              │
│      ├─ 폰트 크기 추정                                      │
│      └─ 번역된 텍스트 렌더링                                │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  [Stage 5] PDF 합성                                          │
│  └─ PDF Layer 결과 + OCR 이미지 → Hybrid PDF 생성           │
└─────────────────────────────────────────────────────────────┘
```

---

## GPU 메모리 흐름

```
시간 →

[Stage 2: Extract]    [Stage 3: Translate]    [Stage 4-5: Apply]
       │                      │                      │
       ▼                      ▼                      ▼
   ┌──────┐              ┌──────┐              ┌──────┐
   │Surya │              │ VLM  │              │ CPU  │
   │ ~4GB │       →      │ ~4GB │       →      │ only │
   │      │              │(4bit)│              │      │
   └──────┘              └──────┘              └──────┘
       ↓                  ↑    ↓
    언로드             GPU캐시  언로드
   GPU캐시              클리어  GPU캐시
    클리어                      클리어
```

**핵심: Surya(Extract)와 VLM(Translate)이 절대 동시에 GPU에 올라가지 않음**

---

## TextBlock 공통 데이터 구조

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

**block_id 규칙:**
- PDF Layer: `pdf_p{page}_b{block_index}` (예: `pdf_p0_b1`)
- OCR: `ocr_p{page}_r{region_index}` (예: `ocr_p2_r3`)

---

## Before vs After

### Before (페이지 단위, 독립 번역)

```
10페이지 OCR+번역 시:

[문제 1: 과도한 모델 전환]
Page 1: Surya 로드(8s) → OCR → Surya 해제 → VLM 로드(10s) → 번역
Page 2: Surya 로드(8s) → OCR → Surya 해제 → VLM 로드(10s) → 번역
...
Page 10: Surya 로드(8s) → OCR → Surya 해제 → VLM 로드(10s) → 번역

총 모델 로드: Surya 10회 + VLM 10회 = ~180초 오버헤드

[문제 2: 독립 번역]
- PDF Layer와 OCR이 각각 독립적으로 번역
- 동일 문서 내 용어 불일치 (예: "기회비용" → "Opportunity cost" vs "cost of opportunity")
- 문서 맥락 공유 없음
```

### After (Stage 기반 배치, 공통 번역)

```
10페이지 OCR+번역 시:

[Stage 2: Extract] Surya 로드(8s) → Page 1~10 OCR → Surya 해제
                   ↓ list[TextBlock] 반환
[Stage 3: Translate] VLM 로드(10s) → 전체 블록 번역 → VLM 해제
                   ↓ TranslationResult 반환
[Stage 4: Apply] CPU에서 번역 적용

총 모델 로드: Surya 1회 + VLM 1회 = ~18초 오버헤드

장점:
- OOM 방지, 메모리 안정
- 문서 전체 맥락 공유 (용어 일관성)
- 재시작 가능 (캐시)
```

---

## 성능 비교

| 항목 | Before (페이지 단위) | After (Stage 배치) |
|------|---------------------|-------------------|
| 10페이지 모델 로드 | Surya 10회 + VLM 10회 | Surya 1회 + VLM 1회 |
| 모델 로딩 오버헤드 | ~180초 | ~18초 |
| OOM 위험 | 높음 (매번 전환) | 낮음 (순차 처리) |
| 메모리 fragmentation | 발생 | 최소화 |
| 중간 실패 시 | 처음부터 재시작 | 캐시된 Stage부터 재개 |
| 용어 일관성 | 낮음 (독립 번역) | 높음 (공통 번역) |

---

## 중간 결과 캐시

```
uploads/cache/{slide_id}/
├── ocr_000.json         # 페이지 0 OCR 결과
├── ocr_001.json         # 페이지 1 OCR 결과
├── ocr_002.json         # 페이지 2 OCR 결과
├── translate_000.json   # 페이지 0 번역 결과
├── translate_001.json   # 페이지 1 번역 결과
└── translate_002.json   # 페이지 2 번역 결과
```

**재시작 시:**
- Stage 2 실패 → OCR 캐시 있는 페이지는 스킵
- Stage 3 실패 → 번역 캐시 있는 페이지는 스킵

---

## 주요 함수 및 클래스

### VLM 관리 (image_pipeline.py)

```python
get_vlm_model()            # 싱글톤 로드 (Qwen3-VL-4B 4bit)
is_vlm_loaded()            # 로드 상태 확인
unload_vlm_model()         # 메모리 해제
translate_text_vlm(prompt) # VLM 번역 호출
```

### PDFLayerPipeline (pdf_pipeline.py)

```python
class PDFLayerPipeline:
    def extract(self, pdf_path: str) -> list[TextBlock]:
        """PDF에서 텍스트 블록 추출 (번역 없이)"""

    def apply(self, pdf_path: str, blocks: list[TextBlock],
              translations: dict[str, str], output_path: str) -> str:
        """번역 결과를 PDF에 적용"""
```

### OCRPipeline (image_pipeline.py)

```python
class OCRPipeline:
    def extract(self, image_paths: list[tuple[int, str]],
                chunk_size: int = 5) -> list[TextBlock]:
        """이미지들에서 텍스트 블록 추출 (Surya OCR)"""
        # OCR 보정 (ocr_corrections.csv) 자동 적용

    def apply(self, image_paths: dict[int, str], blocks: list[TextBlock],
              translations: dict[str, str], output_dir: str) -> dict[int, str]:
        """번역 결과를 이미지에 오버레이"""
```

### translate_blocks (translator.py)

```python
def translate_blocks(
    blocks: list[TextBlock],      # PDF + OCR 블록 혼합 가능
    target_lang: str = "en",
    batch_size: int = 15,
    custom_terms: dict = None     # 추가 용어 (선택)
) -> TranslationResult:
    """공통 번역 함수 - 문서 맥락 공유"""
    # glossary.csv 자동 로드
    # 결과: {block_id: translated_text, ...}
```

---

## 모델 로드/언로드 타이밍

```
[Stage 2: Extract]
  ├─ PDF Layer: PyMuPDF (CPU) - 항상 사용 가능
  └─ OCR:
      ├─ Surya 로드 (한 번)
      ├─ 전체 OCR 대상 페이지 처리
      └─ Surya 삭제 (del + gc.collect + torch.cuda.empty_cache)

[Stage 3: Translate]
  ├─ VLM 로드 (한 번)
  ├─ translate_blocks() 호출
  │   ├─ 모든 한글 블록 (PDF + OCR) 일괄 번역
  │   └─ 용어집 자동 적용
  └─ VLM 삭제 (del + gc.collect + torch.cuda.empty_cache)

[Stage 4: Apply]
  ├─ PDF Layer: PyMuPDF (CPU)
  │   ├─ Redaction (원본 텍스트 제거)
  │   └─ 번역 텍스트 삽입
  └─ OCR: PIL/OpenCV (CPU)
      ├─ 배경 복원
      └─ 텍스트 렌더링
```

- **Stage 내**: 모델 한 번 로드 → 전체 페이지 배치 처리 (싱글톤처럼)
- **Stage 전환**: Surya ↔ VLM 서로 메모리 충돌 방지 위해 내렸다 올림
- **페이지별 gc.collect()**: 이미지 객체 정리용, 모델 자체는 Stage 끝날 때만 내림

---

## 설정 옵션

| 환경변수 | 기본값 | 설명 |
|---------|--------|------|
| `OCR_CHUNK_SIZE` | 5 | Surya 한 번에 처리할 페이지 수 |
| `CACHE_DIR` | uploads/cache | 중간 결과 캐시 디렉토리 |
| `USE_NEW_SLIDE_PIPELINE` | true | 새 파이프라인 사용 여부 |
| `KOREAN_FONT_PATH` | C:/Windows/Fonts/malgun.ttf | 한글 폰트 경로 |

---

## 핵심 정책

1. **Surya와 VLM 동시 로드 금지** - GPU 메모리 부족 방지
2. **extract → translate → apply 분리** - 문서 맥락 공유
3. **모델 단위 배치 처리** - 페이지마다 로드/언로드 하지 않음
4. **TextBlock 공통 데이터 구조** - PDF와 OCR 블록 통합 관리
5. **중간 결과 캐싱** - JSON 파일로 저장, 재시작 시 재사용
6. **GPU 메모리 정리 철저** - Stage 전환 시:
   ```python
   gc.collect()
   torch.cuda.empty_cache()
   torch.cuda.synchronize()
   ```
7. **용어집 (glossary.csv) 공통 적용** - translate_blocks()에서 자동 로드
8. **OCR 보정 (ocr_corrections.csv) 적용** - extract 단계에서 자동 교정

---

## 관련 파일

| 파일 | 역할 |
|-----|------|
| `slides.py` | Stage 기반 오케스트레이션 |
| `models.py` | TextBlock, FontInfo, TranslationResult 정의 |
| `translator.py` | translate_blocks() 공통 번역 함수 |
| `pdf_pipeline.py` | PDFLayerPipeline (extract/apply) |
| `image_pipeline.py` | OCRPipeline (extract/apply) + VLM 관리 |
| `term_corrections.py` | 용어집 + OCR 보정 로더 |
| `config/glossary.csv` | 한국어→영어 용어 매핑 |
| `config/ocr_corrections.csv` | OCR 오타→교정 매핑 |
