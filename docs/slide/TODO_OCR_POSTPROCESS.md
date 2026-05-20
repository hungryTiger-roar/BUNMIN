# OCR 후처리 개선 (향후 과제)

## 현황

현재 OCR 파이프라인에서 Surya OCR 인식률이 낮을 때 후처리 로직이 미흡함.

### 기존 정책 (폐기됨)
- 저신뢰도(confidence < 0.5) 블록은 원문 유지
- 문제: 한글이 번역 없이 남아 사용자 혼란

### 현재 정책
- 모든 한글 블록 번역 (저신뢰도 포함)
- 문제: OCR 오인식 → 오인식된 텍스트가 번역됨 → 의미 없는 번역 결과

## 문제 시나리오

```
원본 텍스트: "기계학습의 원리"
Surya OCR 인식: "기게학습의 원리" (오타)
VLM 번역: "Principles of Gigye Learning" (오역)
결과: 원본 위에 오역이 덮임
```

## 현재 구현된 안전장치

### 1. ocr_corrections.csv (수동 등록)
- 경로: `config/ocr_corrections.csv`
- 형식: `typo,correct` (예: `기게학습,기계학습`)
- 한계: 발견된 오타만 수동 등록 가능, 사전 예측 불가

### 2. confidence 필드 유지 (진단용)
- OCR 블록에 신뢰도 저장
- 로그에 저신뢰도 블록 경고 출력
- 번역 품질 이슈 추적 시 활용

## 향후 개선 방안

### 방안 1: glossary.csv 기반 Fuzzy Matching
기존 용어집의 한글 키를 기준으로 유사도 매칭.

```python
# 예시: edit distance 기반
from difflib import get_close_matches

def fuzzy_correct(ocr_text: str, known_terms: list[str], cutoff: float = 0.8) -> str:
    words = ocr_text.split()
    corrected = []
    for word in words:
        matches = get_close_matches(word, known_terms, n=1, cutoff=cutoff)
        corrected.append(matches[0] if matches else word)
    return " ".join(corrected)
```

장점: 기존 용어집 재활용
단점: 용어집에 없는 단어는 보정 불가

### 방안 2: 한글 맞춤법 검사기 통합
- py-hanspell (네이버 맞춤법 검사기 API)
- KoNLPy + 사전 기반 교정

장점: 범용적 오타 교정
단점: 외부 API 의존, 도메인 용어 미지원

### 방안 3: 저신뢰도 블록 별도 표시
번역은 하되, 결과물에 저신뢰도 영역 시각적 표시.

```python
# 예: 저신뢰도 영역 테두리 표시
if confidence < 0.5:
    draw.rectangle(bbox, outline="red", width=2)
```

장점: 사용자가 검토 필요 영역 인지
단점: 오역 자체는 해결 안 됨

### 방안 4: LLM 기반 OCR 후보정
VLM에 OCR 결과 + 이미지를 함께 전달하여 교정.

```
프롬프트: "다음 OCR 결과에 오타가 있으면 교정해주세요: {ocr_text}"
```

장점: 맥락 기반 교정 가능
단점: 추가 VLM 호출 비용, 지연 시간

## 우선순위

1. **단기**: ocr_corrections.csv에 자주 발생하는 오타 수동 등록
2. **중기**: glossary.csv 기반 fuzzy matching 구현
3. **장기**: LLM 기반 후보정 또는 맞춤법 검사기 통합

## 관련 파일

- `backend/app/services/slide_translation/term_corrections.py` - OCR 보정 함수
- `backend/app/services/slide_translation/image_pipeline.py` - OCRPipeline 클래스
- `config/ocr_corrections.csv` - OCR 오타 보정 매핑
