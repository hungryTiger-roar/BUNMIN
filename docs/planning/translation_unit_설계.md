# 레이아웃 기반 번역 블록 설계

> **구현 상태: 설계 완료 / 코드 미적용**
>
> `build_translation_blocks()` 및 `translate_blocks()` 함수가 `translate_slide_v3.py`에 정의되어 있으나,
> 현재 `stage_translate()` 함수는 **줄 단위(region별) 번역**을 사용합니다.
> Translation Block 시스템은 설계대로 구현되어 있지만 활성화되지 않은 상태입니다.
> 활성화하려면 `stage_translate()` 내부에서 `build_translation_blocks()` → `translate_blocks()` 호출로 교체해야 합니다.

## 개요

OCR 줄 단위 번역의 문제점을 해결하기 위해 **Translation Block** 개념을 도입한다.

**핵심 원칙:**
> 한국어 문법 규칙으로 문장을 맞추는 게 아니라, PPT 레이아웃상 같은 의미 블록으로 보이는 OCR 영역들을 묶고, 번역 모델에게 그 블록을 자연스러운 영어로 재구성하게 하는 것.

### 현재 문제

```
OCR 영역 1: "다양한 신체활동에 따른 적합한 식이의 질과 양,"
OCR 영역 2: "운동수행 시 인체의 대사과정과"
OCR 영역 3: "건강 및 수행력 향상에 가장 부합하는 방법을 모색하는 학문"

→ 각각 개별 번역 → 영어 문장 조각남
```

### 목표

```
Translation Block 1:
  - region_indices: [1, 2, 3]
  - source_lines: ["다양한...", "운동수행...", "건강 및..."]
  - source_text: "다양한 신체활동에 따른..."
  - english: "Exercise Nutrition is the study of..."

→ 레이아웃 기반 블록 → 자연스러운 영어로 재구성
```

---

## 핵심 개념

### Region vs Translation Block

| 개념 | 역할 | 단위 |
|------|------|------|
| **OCR Region** | 렌더링 참조 | 원본 bbox 유지, 개별 텍스트 영역 |
| **Translation Block** | 번역 단위 | 여러 region을 레이아웃 기반으로 묶은 블록 |

**중요:** Region은 삭제하지 않고 보존. Block이 region들을 참조.

```json
{
  "regions": [...],
  "translation_blocks": [
    {
      "block_id": 1,
      "region_indices": [2, 3, 4],
      "bbox": [x1, y1, x2, y2],
      "source_lines": ["줄1", "줄2", "줄3"],
      "source_text": "줄1 줄2 줄3",
      "english": "..."
    }
  ]
}
```

### 렌더링 전략

Translation Block 번역 결과를 렌더링할 때:

```
옵션 A: 첫 region bbox에 전체 번역 (위험: 넘침)
옵션 B: 묶인 region들의 union bbox에 렌더링 (추천)
옵션 C: 번역을 다시 줄 단위로 나눠 각 region에 배치 (복잡)
```

**옵션 B 추천:** block bbox 전체를 지우고 block 영어를 렌더링.

---

## 병합 기준 우선순위

```
1순위: 레이아웃
- 같은 컬럼인가? (x 시작점 유사)
- y 간격이 가까운가?
- 글자 크기/높이가 비슷한가?
- 중간에 다른 블록이 끼어 있지 않은가?

2순위: 구조
- bullet이 같은 그룹인가?
- 표 셀인가?
- 제목인가?
- footer/copyright인가?

3순위: 문법 (보조)
- 확실한 종결이면 끊음
- 확실한 이어짐이면 가중치 추가
- 애매하면 문법으로 결정하지 않음
```

**핵심:** 문법으로 병합하는 게 아니라, 레이아웃으로 블록을 만들고 모델에게 재구성 위임.

---

## Hard Blocker (병합 금지 조건)

**중요:** 점수 계산 전에 먼저 체크. 이 조건에 해당하면 무조건 병합 금지.

```python
def cannot_merge(prev_region, curr_region, current_block=None, image_size=None):
    """병합 금지 조건 (hard blocker)

    Args:
        prev_region: 현재 블록의 마지막 region
        curr_region: 병합 후보 region
        current_block: 현재 블록의 모든 region 리스트 (union bbox 계산용)
        image_size: (width, height) 이미지 크기 (union bbox 제한용)
    """

    # 1. 번역 스킵 대상은 병합 X
    if prev_region.get("skip_translate") or curr_region.get("skip_translate"):
        return True

    # 2. 특수 타입은 병합 X (1차: paragraph만 병합 허용)
    blocked_types = ["title", "footer", "table_cell", "bullet"]
    if prev_region.get("_type") in blocked_types:
        return True
    if curr_region.get("_type") in blocked_types:
        return True

    # 3. bullet 시작은 새 블록 (타입 분류 전 텍스트 기반 체크)
    # Note: _type이 bullet이면 위에서 이미 차단되지만, 타입 분류 전에도 체크
    if starts_with_bullet(curr_region.get("ocr_text", "")):
        return True

    # 4. y 간격이 너무 멀면 X
    if is_far_apart(prev_region["bbox"], curr_region["bbox"]):
        return True

    # 5. 명확히 다른 컬럼
    if is_different_column(prev_region["bbox"], curr_region["bbox"]):
        return True

    # 6. 병합 시 union bbox가 너무 커지면 X (위험한 병합 방지)
    if current_block and image_size:
        if would_exceed_bbox_limit(current_block, curr_region, image_size):
            return True

    return False

def is_far_apart(prev_bbox, curr_bbox):
    """y 간격이 2줄 이상 떨어져 있는지"""
    prev_height = prev_bbox[3] - prev_bbox[1]
    gap = curr_bbox[1] - prev_bbox[3]
    return gap > prev_height * 2.0

def is_different_column(prev_bbox, curr_bbox, threshold=100):
    """x 범위가 전혀 겹치지 않는지 (함수명 통일: is_different_column)"""
    return curr_bbox[0] > prev_bbox[2] + threshold or prev_bbox[0] > curr_bbox[2] + threshold

def would_exceed_bbox_limit(current_block, new_region, image_size):
    """병합 시 union bbox가 너무 커지는지 체크 (병합 단계에서 차단)"""
    page_width, page_height = image_size
    image_area = page_width * page_height

    # 현재 블록 + 새 region의 union bbox 계산
    all_regions = current_block + [new_region]
    x1 = min(r["bbox"][0] for r in all_regions)
    y1 = min(r["bbox"][1] for r in all_regions)
    x2 = max(r["bbox"][2] for r in all_regions)
    y2 = max(r["bbox"][3] for r in all_regions)

    union_area = (x2 - x1) * (y2 - y1)
    union_width_ratio = (x2 - x1) / page_width

    # 이미지의 20% 초과 또는 가로 80% 초과 시 병합 금지
    return union_area / image_area > 0.20 or union_width_ratio > 0.8
```

**함수명 통일:**
- `is_different_column()` 사용 (모든 곳에서 동일)
- `is_far_apart()` 사용
- `is_same_column()` 사용

**병합 결정 흐름:**
```
1. cannot_merge() 체크 → True면 무조건 새 블록
2. calculate_merge_score() 계산 → 임계값 이상이면 병합
```

---

## 점수 기반 병합 로직

Hard blocker를 통과한 후보에 대해서만 점수 계산.

```python
def calculate_merge_score(prev_region, curr_region):
    """두 region의 병합 점수 계산 (높을수록 병합)"""
    score = 0
    prev_bbox = prev_region["bbox"]
    curr_bbox = curr_region["bbox"]
    prev_text = prev_region.get("ocr_text", "")
    curr_text = curr_region.get("ocr_text", "")

    # ========== 1순위: 레이아웃 ==========

    # 같은 컬럼 (+3)
    if same_column(prev_bbox, curr_bbox):
        score += 3

    # 가까운 y 간격 (+3)
    if close_y_gap(prev_bbox, curr_bbox):
        score += 3

    # 비슷한 텍스트 높이 (+2)
    if similar_height(prev_bbox, curr_bbox):
        score += 2

    # x 시작점 유사 (+2)
    if similar_x_start(prev_bbox, curr_bbox):
        score += 2

    # 다른 컬럼이면 (-5)
    if is_different_column(prev_bbox, curr_bbox):
        score -= 5

    # ========== 2순위: 구조 (이미 분류된 _type 사용) ==========

    # bullet으로 시작하면 새 항목 (-5)
    # 주의: hard blocker에서 이미 처리되지만 score에서도 감점
    if starts_with_bullet(curr_text):
        score -= 5

    # 제목이면 (-4) - _type 사용 (함수 호출 X)
    if curr_region.get("_type") == "title":
        score -= 4

    # ========== 3순위: 문법 (보조) ==========

    # 이어짐 마커로 끝나면 (+1)
    if has_continuation_marker(prev_text):
        score += 1

    # 확실한 문장 종결 (-3)
    if ends_with_terminal(prev_text):
        score -= 3

    return score

# 병합 임계값
MERGE_THRESHOLD = 5

def should_merge(prev_region, curr_region, current_block=None, image_size=None):
    """병합 여부 최종 결정

    Args:
        prev_region: 현재 블록의 마지막 region
        curr_region: 병합 후보 region
        current_block: 현재 블록의 모든 region 리스트 (union bbox 계산용)
        image_size: (width, height) 이미지 크기 (union bbox 제한용)
    """
    # 1. Hard blocker 먼저 체크
    if cannot_merge(prev_region, curr_region, current_block, image_size):
        return False

    # 2. 점수 기반 판단
    return calculate_merge_score(prev_region, curr_region) >= MERGE_THRESHOLD
```

---

## 레이아웃 판단 함수

### 1. 같은 컬럼

```python
def same_column(prev_bbox, curr_bbox, threshold=40):
    """x좌표 기준 같은 컬럼인지 판단"""
    prev_x1, _, prev_x2, _ = prev_bbox
    curr_x1, _, curr_x2, _ = curr_bbox

    # 좌측 정렬 기준
    x_start_close = abs(prev_x1 - curr_x1) < threshold

    # 또는 x 범위 겹침
    overlap = min(prev_x2, curr_x2) - max(prev_x1, curr_x1)
    min_width = min(prev_x2 - prev_x1, curr_x2 - curr_x1)
    significant_overlap = overlap / max(1, min_width) > 0.5

    return x_start_close or significant_overlap

# 참고: is_different_column()은 Hard Blocker 섹션에 정의됨
```

### 2. 가까운 y 간격

```python
def close_y_gap(prev_bbox, curr_bbox):
    """y 간격이 충분히 가까운지 (글자 높이 기반)"""
    _, _, _, prev_y2 = prev_bbox
    _, curr_y1, _, _ = curr_bbox

    gap = curr_y1 - prev_y2
    prev_height = prev_bbox[3] - prev_bbox[1]

    # 글자 높이의 1.2배 이내면 가까움
    return 0 <= gap <= prev_height * 1.2
```

### 3. 비슷한 텍스트 높이

```python
def similar_height(prev_bbox, curr_bbox):
    """텍스트 높이가 비슷한지 (폰트 크기 추정)"""
    h1 = prev_bbox[3] - prev_bbox[1]
    h2 = curr_bbox[3] - curr_bbox[1]

    # 0.6 ~ 1.6 배 범위면 비슷
    return 0.6 <= h2 / max(1, h1) <= 1.6
```

### 4. x 시작점 유사

```python
def similar_x_start(prev_bbox, curr_bbox, threshold=20):
    """x 시작점이 거의 같은지 (같은 들여쓰기)"""
    return abs(prev_bbox[0] - curr_bbox[0]) < threshold
```

---

## 구조 판단 함수

### bullet 시작 감지

```python
def starts_with_bullet(text):
    """bullet/번호로 시작하는지"""
    text = text.strip()
    bullets = ['•', '●', '○', '◦', '▶', '►', '■', '□', '·', '-', '>', '※', '★']

    # bullet 문자로 시작
    if any(text.startswith(b) for b in bullets):
        return True

    # 숫자 + 마침표/괄호로 시작 (1. 2) 3> 등)
    if re.match(r'^\d+[\.\)\>]\s+', text):
        return True

    return False
```

**주의:** 같은 bullet이 여러 줄로 쪼개진 경우 예외 처리 필요

```
• 신체활동을 위한 연료로       ← bullet 시작
  유기체의 생존을 유지하고     ← 들여쓰기 (병합해야 함)
  구조적 기능적 통합을 유지
```

→ 두 번째 줄은 bullet 없지만 들여쓰기 → 첫 줄과 병합

### 제목 감지

```python
def looks_like_title(region, page_height):
    """제목처럼 보이는지 (top + short + large 조합)

    주의: 상단 15%에 있다고 무조건 제목이 아님.
    날짜, 로고, 페이지 번호 등을 제외하기 위해 세 조건 모두 충족해야 함.
    """
    bbox = region["bbox"]
    text = region.get("ocr_text", "").strip()
    height = bbox[3] - bbox[1]

    is_top = bbox[1] < page_height * 0.15    # 상단 15%에 위치
    is_short = len(text) < 40                 # 텍스트가 짧음
    is_large = height > 30                    # 폰트가 큼 (높이로 추정)

    # 세 조건 모두 충족해야 제목
    return is_top and is_short and is_large
```

---

## 문법 판단 함수 (보조)

```python
def has_continuation_marker(text):
    """이어짐 마커로 끝나는지 (보조 신호)"""
    text = text.strip()
    markers = [',', '과', '와', '및', '또는', '하고', '하며', '하여',
               '위한', '따른', '통해', '등', '의', '로', '으로', '에서', '에게']

    for marker in markers:
        if text.endswith(marker):
            return True
    return False

def ends_with_terminal(text):
    """확실한 문장 종결로 끝나는지"""
    text = text.strip()
    # 마침표, 물음표, 느낌표
    return text.endswith(('.', '?', '!', '。'))
```

---

## Region Type 분류

```python
class RegionType(Enum):
    TITLE = "title"           # 제목 (큰 폰트, 상단)
    SUBTITLE = "subtitle"     # 소제목
    BULLET = "bullet"         # bullet 항목
    PARAGRAPH = "paragraph"   # 본문 문단
    TABLE_CELL = "table_cell" # 표 셀 (병합 금지)
    FOOTER = "footer"         # 하단 (저작권, 페이지 번호)
    CAPTION = "caption"       # 이미지 캡션

def classify_region_type(region, image_size, all_regions):
    """region 타입 분류"""
    page_width, page_height = image_size
    bbox = region["bbox"]
    text = region.get("ocr_text", "").strip()

    # 1. 제목 감지 (looks_like_title 함수 사용)
    if looks_like_title(region, page_height):
        return "title"

    # 2. 위치 기반: 푸터
    if bbox[3] > page_height * 0.9:
        if looks_like_footer(text):
            return "footer"

    # 3. 표 셀 감지 (중요!)
    if looks_like_table_cell(region, all_regions):
        return "table_cell"

    # 4. 텍스트 패턴 기반: bullet
    if starts_with_bullet(text):
        return "bullet"

    # 5. 기본값
    return "paragraph"

def looks_like_footer(text):
    """footer 패턴 (저작권, 페이지 번호 등)"""
    patterns = [
        r'©|copyright|all rights?',
        r'page\s*\d+|\d+\s*/\s*\d+',
        r'\d{4}\.\d{2}\.\d{2}',
    ]
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)

def looks_like_table_cell(region, all_regions):
    """표/차트 셀처럼 보이는지

    주의: 과탐지 시 병합 효과가 줄어듦 (table_cell은 병합 금지).
    PPT 목차나 여러 라벨이 같은 줄에 있는 경우를 제외해야 함.
    """
    bbox = region["bbox"]
    text = region.get("ocr_text", "").strip()

    is_short = len(text) <= 20
    has_numeric_or_unit = bool(re.search(r'\d|%|kg|cm|년|위|순위', text))

    # 1. 숫자/단위 + 짧은 텍스트 → 표 셀 가능성 높음
    if len(text) <= 10 and has_numeric_or_unit:
        return True

    # 2. 같은 y 라인에 여러 region + (짧은 텍스트 또는 숫자/단위)
    same_row_count = count_regions_same_row(region, all_regions)
    if same_row_count >= 3 and (is_short or has_numeric_or_unit):
        return True

    return False

def count_regions_same_row(region, all_regions, y_tolerance=15):
    """같은 y 라인에 있는 region 개수"""
    bbox = region["bbox"]
    center_y = (bbox[1] + bbox[3]) / 2

    count = 0
    for r in all_regions:
        r_bbox = r["bbox"]
        r_center_y = (r_bbox[1] + r_bbox[3]) / 2
        if abs(center_y - r_center_y) < y_tolerance:
            count += 1

    return count
```

---

## 블록 생성 알고리즘

```python
# 디버그 모드 (개발 중 True로 설정)
DEBUG_MERGE = False

def build_translation_blocks(regions: list, image_size: tuple) -> list:
    """OCR regions를 Translation Blocks로 그룹화

    Args:
        regions: OCR region 리스트 (원본)
        image_size: (width, height) 이미지 크기

    Returns:
        Translation Block 리스트
    """
    if not regions:
        return []

    # 0. 원본 인덱스 부여 (필터링/정렬 전에)
    for i, region in enumerate(regions):
        region["_orig_index"] = i

    # 1. 번역 대상만 필터링 (skip_translate 제외)
    translatable = [r for r in regions if not r.get("skip_translate", False)]

    if not translatable:
        return []

    # 2. y좌표로 정렬 (위에서 아래로, 같은 y면 x로)
    sorted_regions = sorted(translatable, key=lambda r: (r["bbox"][1], r["bbox"][0]))

    # 3. 타입 분류 (정렬 후)
    for region in sorted_regions:
        region["_type"] = classify_region_type(region, image_size, sorted_regions)

    # 4. should_merge() 기반 그룹화 (hard blocker + 점수 판단)
    blocks = []
    current_block = [sorted_regions[0]]

    for i in range(1, len(sorted_regions)):
        prev = current_block[-1]  # 현재 블록의 마지막 region
        curr = sorted_regions[i]

        # should_merge()는 cannot_merge() 체크 + 점수 판단을 모두 수행
        # current_block과 image_size 전달 → union bbox 크기 제한 적용
        merge = should_merge(prev, curr, current_block, image_size)

        # 디버그 로그 (개발 중 활성화)
        if DEBUG_MERGE:
            score = calculate_merge_score(prev, curr)
            blocked = cannot_merge(prev, curr, current_block, image_size)
            prev_text = prev.get("ocr_text", "")[:20]
            curr_text = curr.get("ocr_text", "")[:20]
            print(f"[Merge] '{prev_text}...' + '{curr_text}...' → "
                  f"blocked={blocked}, score={score}, merge={merge}")

        if merge:
            current_block.append(curr)
        else:
            # 현재 블록 저장하고 새 블록 시작
            blocks.append(create_translation_block(current_block))
            current_block = [curr]

    # 마지막 블록 저장
    if current_block:
        blocks.append(create_translation_block(current_block))

    # 5. 블록 ID 부여
    for i, block in enumerate(blocks):
        block["block_id"] = i

    return blocks

def create_translation_block(regions: list) -> dict:
    """region 리스트로 Translation Block 생성

    Args:
        regions: 병합된 region 리스트

    Note:
        위험한 union bbox가 될 병합은 build_translation_blocks() 단계에서 이미 차단됨.
        따라서 여기서는 다중 region이면 union bbox를 그대로 사용함.
    """
    # 원본 줄들 보존
    source_lines = [r.get("ocr_text", "").strip() for r in regions]

    # 텍스트 합치기 (두 가지 버전)
    source_text = " ".join(line for line in source_lines if line)  # 공백 연결
    prompt_text = "\n".join(line for line in source_lines if line)  # 줄바꿈 유지 (프롬프트용)

    # union bbox 계산
    x1 = min(r["bbox"][0] for r in regions)
    y1 = min(r["bbox"][1] for r in regions)
    x2 = max(r["bbox"][2] for r in regions)
    y2 = max(r["bbox"][3] for r in regions)
    union_bbox = [x1, y1, x2, y2]

    return {
        "block_id": None,  # 나중에 할당
        "region_indices": [r["_orig_index"] for r in regions],  # 원본 인덱스 사용
        "source_lines": source_lines,
        "source_text": source_text,      # 공백 연결 버전
        "prompt_text": prompt_text,      # 줄바꿈 유지 버전 (프롬프트 입력용)
        "bbox": union_bbox,              # 렌더링에 사용할 bbox (= union bbox)
        "use_union_bbox": len(regions) > 1,  # 다중 region이면 union bbox 사용
        "type": regions[0].get("_type", "paragraph"),
        "english": None,  # 번역 후 채움
    }
```

---

## 번역 프롬프트 개선

### 현재 프롬프트 (줄 단위)

```
[TRANSLATE]
1. 다양한 신체활동에 따른 적합한 식이의 질과 양,
2. 운동수행 시 인체의 대사과정과
3. 건강 및 수행력 향상에 가장 부합하는 방법을 모색하는 학문
```

### 개선 프롬프트 (블록 단위)

```
Translate Korean lecture slide text into natural English.

The input items are layout-based text blocks.
Some Korean lines may be fragmented due to slide line breaks.
Reconstruct each block into natural, complete English suitable for lecture slides.

[GLOSSARY]
"운동영양학": "Exercise Nutrition"
"운동수행력": "athletic performance"
...

[TERM HINTS]
운동수행력 = athletic performance (not "physical fitness")
운동능력 = athletic performance
신체활동 = physical activity
식사요법 = dietary therapy

[TRANSLATE]
1. 다양한 신체활동에 따른 적합한 식이의 질과 양
운동수행 시 인체의 대사과정과
건강 및 수행력 향상에 가장 부합하는 방법을 모색하는 학문

2. 음식을 통한 적절한 영양의 섭취는
건강 유지와 질병 예방을 위한
가장 기본적인 전제조건

RULES:
1. Output exactly N lines in the format "1. translation"
2. Preserve meaning. Do not add new information.
3. Use GLOSSARY translations for technical terms.
4. Use TERM HINTS for nuanced word choices.
5. Use concise academic English suitable for lecture slides.
6. If a block contains multiple Korean lines, translate as one coherent sentence or bullet.
7. Preserve numbers, units, model names, proper nouns, and symbols.
8. Never romanize - translate to English.
9. Do not translate footer/copyright text unless explicitly included.
```

### 예상 출력

```
1. Exercise Nutrition is the study of the appropriate quality and quantity of diet for various physical activities, the body's metabolic processes during exercise, and the most effective methods for improving health and performance.

2. Adequate nutrition through food intake is the most fundamental prerequisite for maintaining health and preventing disease.
```

**핵심 변경:**
- 입력이 줄 단위 → 블록 단위
- "layout-based text blocks" 명시
- "Reconstruct each block into natural, complete English" 명시

---

## 렌더링 전략

### Translation Block 구조

`create_translation_block()`이 반환하는 블록:

```python
{
    "block_id": 0,
    "region_indices": [5, 6, 7],       # 원본 region 인덱스
    "source_lines": ["줄1", "줄2"],    # 원본 줄들
    "source_text": "줄1 줄2",          # 공백 연결 버전
    "prompt_text": "줄1\n줄2",         # 줄바꿈 유지 (프롬프트용)
    "bbox": [x1, y1, x2, y2],          # union bbox (렌더링용)
    "use_union_bbox": True,            # 다중 region 여부
    "type": "paragraph",
    "english": None,                   # 번역 후 채움
}
```

**핵심:** 위험한 병합은 `cannot_merge()` 단계에서 이미 차단됨.
- `would_exceed_bbox_limit()` → 면적 20% 초과 또는 가로 80% 초과 시 병합 금지
- 따라서 렌더링 단계에서는 block["bbox"]를 안전하게 사용 가능
- fallback 로직이 create 단계에 없음 → 병합 단계에서 차단하는 것이 원칙

### Translation Block → 이미지 렌더링

```python
def render_translation_block(block, image):
    """Translation Block을 이미지에 렌더링

    block["bbox"]는 이미 안전한 크기로 결정됨:
    - 단일 region: 해당 region bbox
    - 다중 region (안전): union bbox
    - 다중 region (위험): 애초에 병합되지 않음
    """
    # bbox 영역 지우기
    inpaint_region(image, block["bbox"])

    # 번역 텍스트 렌더링
    render_text_in_bbox(
        image,
        text=block["english"],
        bbox=block["bbox"],
        font_size=auto_fit,
    )

    # 디버그 로그
    if DEBUG_MERGE:
        region_count = len(block["region_indices"])
        use_union = block.get("use_union_bbox", True)
        print(f"[Render] block {block['block_id']}: "
              f"{region_count} regions, union_bbox={use_union}")
```

**핵심:**
- 번역 단위와 렌더링 단위는 반드시 같을 필요 없음
- 위험한 병합은 `cannot_merge()` 단계에서 이미 차단됨
- 렌더링은 block["bbox"]만 사용하면 됨

---

## 구현 단계

### 1단계: Translation Block Builder

```
translate_slide_v3.py에 추가:
- build_translation_blocks(regions, page_height) 함수
- calculate_merge_score(prev, curr) 함수
- same_column(), close_y_gap(), similar_height() 등 레이아웃 함수
- starts_with_bullet(), looks_like_title() 등 구조 함수
- classify_region_type() 함수
```

### 2단계: stage_translate 수정

```
현재:
  regions → 줄 단위 번역 → regions에 english 추가

개선:
  regions → build_translation_blocks() → blocks
  blocks → 블록 단위 번역 → blocks에 english 추가
  blocks → 렌더링 (block bbox 사용)
```

### 3단계: 프롬프트 개선

```
- "layout-based text blocks" 설명 추가
- "Reconstruct each block into natural English" 룰 추가
- TERM HINTS 섹션 추가
- 블록 단위 입력 형식 변경
```

### 4단계: 렌더링 수정

```
현재:
  각 region bbox에 개별 렌더링

개선:
  단일 region block: 기존 방식
  다중 region block: union bbox에 렌더링
```

---

## 테스트 계획

### 테스트 대상 페이지

| 페이지 | 특징 | 예상 개선점 |
|--------|------|-------------|
| page 3 | 운동영양학 정의 (여러 줄 → 하나의 정의문) | 문장 재구성 |
| page 8 | 긴 설명 (줄 단위 번역 → 어색함) | 자연스러운 영어 |
| page 10 | 운동영양학 목표 (의미 연결 필요) | 맥락 유지 |
| page 11 | 가장 문제 큼 (문장 끊김) | 전체 개선 |

### 비교 지표

```
전: OCR 줄 단위 번역
후: Translation Block 단위 번역

비교 항목:
- 영어 문장 자연스러움 (주관 평가)
- 의미 전달 정확도
- 렌더링 품질 (bbox 넘침 여부)
```

---

## 1차 구현 범위 (권장)

**핵심:** 병합은 "많이 하는 것"보다 "위험한 병합을 막는 것"이 더 중요.

```
1차 구현 (보수적):
✓ 표/푸터/제목/bullet은 병합 제외 (hard blocker)
✓ 같은 컬럼 + 가까운 y + 비슷한 height인 paragraph만 병합
✓ 면적 과대 병합은 사전 차단 (would_exceed_bbox_limit)
✓ block 단위 번역
✓ union bbox 렌더링 (위험한 병합은 이미 차단됨)
✓ polishing 없음

1.5차 추가:
- bullet continuation 지원 (들여쓰기된 후속 줄 병합)

2차 추가:
- 병합 실패/번역 미완성 감지 → 선택적 polishing
- page type별 전략 (제목/목차/표/설명형)
```

---

## 제외 사항 (2차 구현)

### Bullet Continuation (1.5차)

```
같은 bullet이 여러 줄로 쪼개진 경우:

• 신체활동을 위한 연료로       ← bullet 시작
  유기체의 생존을 유지하고     ← 들여쓰기 (병합해야 함)
  구조적 기능적 통합을 유지

→ 1차에서는 bullet 시작마다 새 블록
→ 1.5차에서 is_bullet_continuation() 추가
```

### Polishing 단계 (2차)

```
위험 요소:
- 의미가 예쁘게 바뀔 수 있음
- 번역이 길어져 bbox 넘침
- 슬라이드 bullet 구조 손실

→ 1차에서는 제외
→ 2차에서 "불완전 문장 감지 기반 선택 적용"으로
```

### Polishing 적용 조건 (2차)

```
Polishing 대상:
- 번역문이 전치사/접속사로 끝남
- 영어에 한국어가 남아 있음
- 문장이 명백히 미완성

Polishing 제외:
- 제목
- 표
- 짧은 bullet
```

---

## 요약

| 항목 | 설명 |
|------|------|
| **핵심 변경** | OCR region → Translation Block (레이아웃 기반 그룹화) |
| **병합 방식** | Hard blocker 먼저 → 점수 기반 판단 |
| **병합 기준** | 같은 컬럼 + 가까운 y + 비슷한 높이 (paragraph만) |
| **분리 기준** | title/footer/table_cell/bullet, 다른 컬럼, bbox 과대, 문장 종결 |
| **프롬프트** | 블록 단위 입력 (줄바꿈 유지) + "Reconstruct into natural English" |
| **렌더링** | union bbox (위험한 병합은 사전 차단됨) |
| **보류** | bullet continuation (1.5차), polishing (2차) |

### 핵심 원칙

> **한국어 문법 규칙으로 문장을 맞추는 게 아니라, PPT 레이아웃상 같은 의미 블록으로 보이는 OCR 영역들을 묶고, 번역 모델에게 그 블록을 자연스러운 영어로 재구성하게 하는 것.**

> **병합은 "많이 하는 것"보다 "위험한 병합을 막는 것"이 더 중요하다.**

### 진행 순서

```
1차: 레이아웃 기반 번역 블록 생성 + 프롬프트 개선 (보수적 병합)
1.5차: bullet continuation 지원
2차: 불완전 문장 감지 → 선택적 polishing
3차: page type별 전략 (제목/목차/표/설명형 슬라이드)
```

---

*AunionAI Team - 2025.04.29*
