# VLM 슬라이드 번역 파이프라인 가이드

> AunionAI 강의 슬라이드 한→영 번역 시스템 종합 문서

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [전체 파이프라인 흐름](#2-전체-파이프라인-흐름)
3. [OCR 단계 상세](#3-ocr-단계-상세)
4. [번역(MT) 단계 상세](#4-번역mt-단계-상세)
5. [렌더링 단계 상세](#5-렌더링-단계-상세)
6. [서비스 통합](#6-서비스-통합)
7. [설정 및 환경변수](#7-설정-및-환경변수)
8. [트러블슈팅](#8-트러블슈팅)

---

## 1. 시스템 개요

### 1.1 목적
한국어 강의 슬라이드(PDF/이미지)를 영어로 번역하여 외국인 유학생이 이해할 수 있도록 지원

### 1.2 핵심 구성요소

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   PDF/IMG   │───▶│     OCR     │───▶│   VLM MT    │───▶│   Render    │
│   (입력)     │    │  (텍스트추출) │    │  (한→영번역) │    │  (오버레이)  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                         │                   │                   │
                    Surya OCR           Qwen3-VL-8B         OpenCV
                    (Transformer)                           Inpainting
```

### 1.3 주요 파일

| 파일 | 역할 |
|------|------|
| `translate_slide_v3.py` | 번역 파이프라인 메인 |
| `backend/config.yaml` | 설정 파일 (OCR, 레이아웃, VLM) |
| `backend/app/routers/slides.py` | FastAPI 엔드포인트 |

---

## 2. 전체 파이프라인 흐름

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         translate_slide() 함수                           │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────┐                                                         │
│  │ 1. PDF→IMG  │  pymupdf로 PDF 페이지를 이미지로 변환                   │
│  └──────┬──────┘                                                         │
│         ▼                                                                │
│  ┌─────────────┐                                                         │
│  │ 2. OCR      │  Surya OCR로 텍스트 영역 + 내용 추출                    │
│  │             │  - bbox: [x_min, y_min, x_max, y_max]                  │
│  │             │  - text: "한글 텍스트"                                  │
│  │             │  - confidence: 0.95                                     │
│  └──────┬──────┘                                                         │
│         ▼                                                                │
│  ┌─────────────┐                                                         │
│  │ 3. 필터링    │  번역 불필요 영역 스킵                                  │
│  │             │  - 영어/숫자만: skip                                    │
│  │             │  - 코드 영역: skip (원본 유지)                          │
│  │             │  - 1글자 한글: skip                                     │
│  │             │  - 수식: skip                                           │
│  └──────┬──────┘                                                         │
│         ▼                                                                │
│  ┌─────────────┐                                                         │
│  │ 4. 배치번역  │  VLM에 텍스트 리스트 전달 (이미지 없음!)               │
│  │             │  "1. 컴퓨터 구조\n2. 운영체제\n3. 알고리즘"             │
│  │             │  → "1. Computer Architecture\n2. OS\n3. Algorithm"     │
│  └──────┬──────┘                                                         │
│         ▼                                                                │
│  ┌─────────────┐                                                         │
│  │ 5. 렌더링   │  원본 이미지에 번역 오버레이                            │
│  │             │  - 배경 복원 (Inpainting)                               │
│  │             │  - 영어 텍스트 렌더링                                   │
│  │             │  - 폰트 크기 자동 조정                                  │
│  └──────┬──────┘                                                         │
│         ▼                                                                │
│  ┌─────────────┐                                                         │
│  │ 6. 저장     │  translated_slide.png / .json 저장                     │
│  └─────────────┘                                                         │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. OCR 단계 상세

### 3.1 OCR 엔진 선택

| 엔진 | 특징 | 한글 정확도 | 속도 |
|------|------|-------------|------|
| **Surya** (현재) | Transformer 기반 | **95%+** | 중 |
| EasyOCR | CNN 기반 | 85% | 빠름 |
| RapidOCR | ONNX 경량화 | 80% | 매우빠름 |

### 3.2 Surya OCR 동작

```python
# 1. Detection: 텍스트 영역(bbox) 검출
det_predictor = DetectionPredictor()
det_results = det_predictor([image])

# 2. Recognition: 각 영역의 텍스트 인식
rec_predictor = RecognitionPredictor()
rec_results = rec_predictor([image], det_results[0].bboxes, ["ko", "en"])

# 결과:
# [
#   {"bbox": [100, 50, 400, 80], "text": "컴퓨터 구조", "confidence": 0.97},
#   {"bbox": [100, 100, 350, 130], "text": "Chapter 1", "confidence": 0.99},
# ]
```

### 3.3 영역 병합 (Adjacent Merging)

슬라이드에서 한 문장이 여러 줄로 분리된 경우 병합:

```
Before:                          After:
┌──────────────────┐            ┌──────────────────┐
│ "컴퓨터 구조와"   │            │ "컴퓨터 구조와   │
├──────────────────┤     →      │  설계 원리"      │
│ "설계 원리"      │            └──────────────────┘
└──────────────────┘
```

### 3.4 필터링 규칙

| 조건 | 처리 | 이유 |
|------|------|------|
| 영어/숫자만 | 스킵 | 번역 불필요 |
| 코드 패턴 | 스킵 | `cout <<`, `printf(` 등 |
| 1글자 한글 | **번역** | 페이지 맥락과 함께 번역 (예: "장" → "Chapter") |
| 수식 | 스킵 | `<math>` 태그, LaTeX |
| 한자 오인식 | 스킵 | 스타일 글꼴 오인식 |

---

## 4. 번역(MT) 단계 상세

### 4.1 기존 방식 vs 현재 방식

```
┌─────────────────────────────────────────────────────────────────────────┐
│ [기존] 영역마다 이미지+텍스트 전달 (느림)                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   for region in regions:                                                │
│       cropped_image = image.crop(region.bbox)  # 이미지 크롭            │
│       prompt = f"<image>{cropped_image}</image>\n번역: {region.text}"  │
│       result = vlm(prompt)  # 영역마다 VLM 호출 (느림!)                 │
│                                                                         │
│   문제점:                                                                │
│   - 영역 10개 → VLM 10번 호출 → 30초+                                   │
│   - 이미지 인코딩 오버헤드                                               │
│   - 맥락 손실 (영역 간 관계 모름)                                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ [현재] 텍스트만 배치 번역 (빠름)                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   # 모든 텍스트를 번호 붙여 리스트로                                     │
│   text_list = """                                                       │
│   1. 컴퓨터 구조                                                         │
│   2. 운영체제 개요                                                       │
│   3. 알고리즘 분석                                                       │
│   """                                                                   │
│                                                                         │
│   # VLM 1회 호출로 전체 번역                                             │
│   result = vlm(text_list)  # → "1. Computer Architecture\n2. OS..."    │
│                                                                         │
│   # 번호로 매핑                                                          │
│   translations = parse_numbered_response(result)                        │
│                                                                         │
│   장점:                                                                  │
│   - VLM 1회 호출 → 3~5초                                                │
│   - 이미지 처리 없음 → 빠름                                              │
│   - 슬라이드 전체 맥락 유지                                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 페이지 맥락 수집

```python
# 페이지 전체 텍스트를 맥락으로 수집 (다의어 번역 정확도 향상)
page_context_items = [r["ocr_text"] for r in regions]
page_context = ", ".join(page_context_items[:20])  # 최대 20개

# 예시: "컴퓨터 구조, 1장, 개요, 자료구조, 트리, 순회, ..."
```

### 4.3 VLM 프롬프트

```python
PROMPT = f"""Translate Korean to English for a lecture slide.

[PAGE CONTEXT]
{page_context}

[TRANSLATE]
{text_list}

RULES:
1. Output EXACTLY {total_lines} lines, format: "1. translation"
2. Use PAGE CONTEXT to disambiguate ambiguous/short terms
3. Standard academic terminology
4. Never romanize - translate to English
5. KEEP: emails, URLs, filenames, code syntax
6. SHORT labels (1-3 words) → CONCISE translation
7. No extra words, no HTML tags

Translate:"""
```

**페이지 맥락 효과:**
| 텍스트 | 맥락 없이 | 맥락 있으면 |
|--------|-----------|-------------|
| "장" | ??? | "Chapter" (강의 맥락) |
| "셀" | ??? | "Cell" (엑셀 맥락) |
| "트리" | ??? | "Tree" (자료구조 맥락) |

### 4.4 번역 매핑

```python
# VLM 응답 파싱
response = """
1. Computer Architecture
2. Operating System Overview
3. Algorithm Analysis
"""

# 번호로 원본 영역에 매핑
for line in response.split('\n'):
    match = re.match(r'(\d+)\.\s*(.+)', line)
    if match:
        idx = int(match.group(1)) - 1
        translation = match.group(2)
        regions[idx]["english"] = translation
```

---

## 5. 렌더링 단계 상세

### 5.1 배경 복원 (하이브리드 Inpainting)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 문제: 단순 사각형 채우기 → "박스 붙인 느낌"                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   Before (단색 채우기):              After (Inpainting):                │
│   ┌────────────────────┐            ┌────────────────────┐              │
│   │ ████████████████   │            │ ≋≋≋≋≋≋≋≋≋≋≋≋≋≋≋≋   │              │
│   │ █ Computer Arch █  │     →      │   Computer Arch    │              │
│   │ ████████████████   │            │ ≋≋≋≋≋≋≋≋≋≋≋≋≋≋≋≋   │              │
│   └────────────────────┘            └────────────────────┘              │
│       (흰 박스 티남)                     (자연스러움)                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 하이브리드 방식

```python
def is_solid_background(img, bbox, threshold=15):
    """bbox 주변 4점 샘플링 → 표준편차로 단색 판단"""
    samples = [img[y1-5, x_mid], img[y2+5, x_mid], ...]
    std = np.std(samples)
    return std < threshold

# 배경 복원
if is_solid_background(img, bbox):
    # 단색 배경 → 단순 채우기 (잉크 번짐 방지)
    cv2.rectangle(img, (x1, y1), (x2, y2), avg_color, -1)
else:
    # 복잡한 배경 → Inpainting
    mask = np.zeros(img.shape[:2], dtype=np.uint8)
    mask[y1:y2, x1:x2] = 255
    img = cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)
```

### 5.3 텍스트 렌더링

```python
# 폰트 크기 자동 조정 (bbox에 맞춤)
def fit_text_to_bbox(text, bbox, max_font_size=40):
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]

    for font_size in range(max_font_size, 8, -2):
        font = ImageFont.truetype("arial.ttf", font_size)
        text_bbox = draw.textbbox((0, 0), text, font=font)
        if text_bbox[2] <= width and text_bbox[3] <= height:
            return font, text

    # 너무 길면 줄바꿈
    return wrap_text(text, width, font)
```

### 5.4 Prefix 기호 처리 (2026-04-27 추가)

슬라이드의 불렛/체크박스 기호(☑, •, ▶ 등) 처리 정책.

**문제:**
- ☑가 폰트 렌더링 시 ☐나 ▼로 변경됨
- 픽셀 보존 폭이 PDF마다 다름

**해결: config 기반 정책 + 이미지 분석**

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Prefix 기호 처리 흐름                                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   OCR: "☑ 호감의 의미"                                                  │
│         │                                                               │
│         ▼                                                               │
│   get_prefix_policy("☑") → "preserve" (config에서 결정)                │
│         │                                                               │
│         ▼                                                               │
│   ┌─────────────────────────────────────────┐                          │
│   │ 1. 이미지 분석 (estimate_prefix_split)  │                          │
│   │    - column-wise ink 분포 분석          │                          │
│   │    - prefix와 본문 사이 gap 찾기         │                          │
│   │    - 성공 시 실제 경계 위치 반환         │                          │
│   └───────────────┬─────────────────────────┘                          │
│                   │ 실패 시                                             │
│                   ▼                                                     │
│   ┌─────────────────────────────────────────┐                          │
│   │ 2. Fallback (height 기반 추정)          │                          │
│   │    - height * 0.9                        │                          │
│   │    - max: region_width * 0.25            │                          │
│   └───────────────┬─────────────────────────┘                          │
│                   ▼                                                     │
│   symbol_width = 24px                                                   │
│         │                                                               │
│         ▼                                                               │
│   ┌─────────────────────────────────────────┐                          │
│   │ 원본: [☑][호감의 의미    ]               │                          │
│   │       ├──┤ 보존          │ inpaint      │                          │
│   │                                         │                          │
│   │ 번역: [☑][Understanding  ]               │                          │
│   │       원본  새로 렌더링                  │                          │
│   └─────────────────────────────────────────┘                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**config 설정:**

```yaml
prefix_symbols:
  # 픽셀 보존 대상 (폰트 렌더링 불안정)
  pixel_preserve_prefixes:
    - "☑"
    - "☐"
    - "📦"
    - "📌"

  # 강제 폰트 렌더링 대상
  force_render_prefixes:
    - "-"
    - "•"
    - "▶"

  # 이미지 분석 설정
  image_split:
    enabled: true
    ink_threshold: 25
    min_gap_px: 3
    max_prefix_region_ratio: 0.35
```

**정책 우선순위:**
1. `force_render_prefixes` → 폰트로 렌더링 (전체 inpaint)
2. `pixel_preserve_prefixes` → 원본 픽셀 보존
3. `default_policy` → 기본 "render"

---

## 6. 서비스 통합

### 6.1 함수 호출 (Python)

```python
from translate_slide_v3 import translate_slide

# 단일 이미지 번역
result = translate_slide(
    image_path="slide.png",
    output_path="translated.png"
)

# 결과
# {
#   "regions": [...],
#   "translated_image": "translated.png",
#   "json_path": "translated.json"
# }
```

### 6.2 FastAPI 엔드포인트

```python
# backend/app/routers/slides.py

@router.post("/translate")
async def translate_slide_endpoint(file: UploadFile):
    # 1. 파일 저장
    image_path = save_upload(file)

    # 2. 번역 실행
    result = translate_slide(image_path, output_path)

    # 3. 결과 반환
    return {
        "original": image_path,
        "translated": result["translated_image"],
        "regions": result["regions"]
    }
```

### 6.3 프론트엔드 연동

```typescript
// 원본/번역 토글
const [showOriginal, setShowOriginal] = useState(false);

return (
  <div>
    <button onClick={() => setShowOriginal(!showOriginal)}>
      {showOriginal ? "번역본 보기" : "원본 보기"}
    </button>
    <img src={showOriginal ? originalUrl : translatedUrl} />
  </div>
);
```

---

## 7. 설정 및 환경변수

### 7.1 환경변수 (.env)

```bash
# VLM 설정
VLM_BASE_MODEL=Qwen/Qwen3-VL-8B-Instruct
VLM_DEVICE=cuda
VLM_MAX_GPU_MEMORY=7GB
VLM_USE_4BIT=true

# OCR 설정
AUNION_OCR_ENGINE=surya  # surya, easyocr, rapid
```

### 7.2 config.yaml (13개 섹션)

```yaml
# 1. OCR 설정
ocr:
  engine: "surya"
  min_confidence: 0.2
  min_area: 500

# 2. OCR 필터링
ocr_filters:
  enable_hanja_filter: true
  skip_english_number_only: true

# 3. 코드 영역 감지
code_patterns:
  - "#include\\s*<"
  - "\\bcout\\s*<<"

# 4. 레이아웃 분류
layout:
  nearby_threshold: 80
  alignment_threshold: 25

# 5. 세로 텍스트 감지
vertical_text:
  enabled: true
  render_skip: true

# 6. VLM 설정
vlm:
  max_new_tokens: 2048
  temperature: 0.3

# 7. 렌더링 기본 설정
rendering:
  min_font_size: 8
  enable_hyphenation: true

# 8. 하이픈 분리 패턴
hyphenation:
  suffix_patterns: ["tion", "sion", "ness"]

# 9. Prefix 기호 처리 (신규)
prefix_symbols:
  pixel_preserve_prefixes: ["☑", "☐", "📦"]
  force_render_prefixes: ["-", "•", "▶"]
  image_split:
    enabled: true

# 10. 폰트 설정
fonts:
  paths: ["C:/Windows/Fonts/NotoSansKR-Regular.ttf"]

# 11. Inpainting 설정
inpainting:
  enabled: true
  hybrid_mode: true

# 12. 출력 설정
output:
  save_json: true
  save_translated_image: true
```

---

## 8. 트러블슈팅

### 8.1 CUDA 오류

```
RuntimeError: CUDA out of memory
```

**해결:** `.env`에서 `VLM_USE_4BIT=true` 설정 (VRAM 절반 사용)

### 8.2 numpy/pillow 버전 충돌

```
ERROR: unbabel-comet requires numpy<2.0.0
```

**해결:** `npm run setup` 실행 (자동으로 버전 고정)

### 8.3 번역 누락

**증상:** 일부 영역 번역 안 됨

**원인:** VLM 응답에서 번호 매칭 실패

**해결:** 개별 재시도 로직 자동 실행됨 (코드에 포함)

### 8.4 배경 잉크 번짐

**증상:** 흰 배경에 회색 얼룩

**원인:** Inpainting이 단색에서 불필요하게 적용됨

**해결:** 하이브리드 방식 (단색=채우기, 복잡=Inpainting)

---

## 부록: 파일 구조

```
teamRepo/
├── translate_slide_v3.py          # 메인 파이프라인
├── backend/
│   ├── config.yaml                # 설정 파일
│   ├── requirements.txt           # Python 의존성
│   └── app/routers/slides.py      # API 엔드포인트
├── scripts/
│   └── download_models.py         # 모델 다운로드
├── docs/
│   └── planning/
│       └── VLM_SLIDE_TRANSLATION_GUIDE.md  # 이 문서
└── uploads/
    ├── slides/      # 원본 슬라이드
    └── translated/  # 번역된 슬라이드
```

---

*마지막 업데이트: 2026-04-27*
