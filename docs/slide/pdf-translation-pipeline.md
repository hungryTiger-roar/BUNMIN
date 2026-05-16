# PDF 번역 파이프라인 아키텍처

## 개요

PDF 텍스트 레이어 기반 한국어 → 영어 번역 시스템입니다.
이미지 기반 방식보다 품질이 높고 벡터 텍스트를 유지합니다.

**번역 모델**: Qwen3-VL-4B-Instruct (4bit 양자화)
**용어집**: config/term_corrections.csv (537개 용어)

## 파이프라인 흐름도

```
┌─────────────────────────────────────────────────────────────────┐
│                        PDF 입력                                  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: PDF 텍스트 레이어 확인                                   │
│  - check_pdf_has_text_layer()                                   │
│  - 텍스트 레이어 존재 여부, 한글 블록 수 확인                        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: 한글 텍스트 추출 (개별 라인)                              │
│  - extract_korean_texts_for_translation(group_lines=False)       │
│  - 각 라인별 bbox, font, size, color, role 추출                  │
│  - 출력: raw_lines (30개 라인)                                   │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2.5: 휴리스틱 레이아웃 분석                                  │
│  - analyze_page_layout() (bbox_analyzer.py)                      │
│  - 휴리스틱 규칙 사용                                             │
│                                                                  │
│  휴리스틱 판단 항목:                                               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 1. merge_with: 어떤 라인들을 병합해야 하는가?              │   │
│  │    - 한국어 문법상 미완성 문장 감지                         │   │
│  │    - 쉼표, 열린 괄호, 연결 조사 등                          │   │
│  │                                                           │   │
│  │ 2. on_image: 이미지/다이어그램 위 텍스트인가?              │   │
│  │    - true: 확장 금지, 특수 처리 필요                        │   │
│  │                                                           │   │
│  │ 3. keep_prefix: 불렛/기호 유지해야 하는가?                 │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  출력: layout_analysis { blocks, merge_groups }                  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2.6: 휴리스틱 병합 그룹 적용                                 │
│  - _apply_merge_groups()                                         │
│                                                                  │
│  merge_groups 있으면:                                            │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ raw_lines (30개) → merged_blocks (13개)                   │   │
│  │                                                           │   │
│  │ 예시:                                                      │   │
│  │ ["p3_l2", "p3_l3"] → 하나의 블록으로 병합                  │   │
│  │ text: "한 사회가 가지고 있는" + "자원은 제한되어 있음"       │   │
│  │ bbox: 두 라인을 포함하는 영역                              │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  merge_groups 없으면:                                            │
│  → 기존 휴리스틱 그룹화 사용 (group_lines=True)                   │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: VLM 번역 (Qwen3-VL-4B)                                  │
│  - _translate_texts() → _translate_batch()                       │
│  - image_pipeline.py: translate_text_vlm(prompt)                 │
│  - 페이지별 배치 처리                                             │
│  - Role 기반 번역 스타일 적용                                      │
│                                                                  │
│  용어집 적용:                                                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ term_corrections.py: get_terms_in_text(korean_text)       │   │
│  │ → 텍스트에서 해당 용어 추출                                │   │
│  │ → VLM 프롬프트에 용어집 포함                               │   │
│  │ → 번역 품질 및 일관성 향상                                  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Role 종류:                                                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ title, heading     → 제목 스타일 (짧게, Title Case)        │   │
│  │ body, bullet       → 본문 스타일                           │   │
│  │ term_definition    → "Term: Definition" 형식 유지          │   │
│  │ question           → 의문문 유지                           │   │
│  │ option             → 선택지 (a, b, c, d) 유지              │   │
│  │ diagram_label      → 짧은 라벨 스타일                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Recovery 로직:                                                   │
│  - fragment 감지 → 인접 블록과 병합 재번역                        │
│  - invalid 번역 (???) → context retry                            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 4: PDF 텍스트 교체                                          │
│  - replace_texts_in_pdf() (pdf_text_replacer.py)                 │
│                                                                  │
│  교체 방식:                                                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 1. 원본 텍스트 영역 흰색으로 덮기                          │   │
│  │ 2. 번역된 텍스트 삽입                                      │   │
│  │    - 폰트 크기 자동 조절 (bbox에 맞게)                     │   │
│  │    - 색상 유지                                             │   │
│  │    - multi-color 렌더링 (term:definition 등)               │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Invalid 렌더링 방지:                                             │
│  - "???" 패턴 → 렌더링 스킵                                       │
│  - 영어 번역에 한글 잔존 → 렌더링 스킵                            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      번역된 PDF 출력                              │
└─────────────────────────────────────────────────────────────────┘
```

## 핵심 파일 구조

```
backend/app/services/slide_translation/
├── pdf_pipeline.py          # 메인 파이프라인 조율
│   ├── run()                # 전체 파이프라인 실행
│   ├── _translate_texts()   # 번역 처리
│   └── _apply_merge_groups()# 휴리스틱 병합 적용
│
├── pdf_text_extractor.py    # PDF 텍스트 추출
│   ├── check_pdf_has_text_layer()
│   ├── extract_korean_texts_for_translation()
│   ├── _group_adjacent_lines()  # 휴리스틱 그룹화
│   └── _infer_line_role()       # Role 추론
│
├── bbox_analyzer.py         # 휴리스틱 레이아웃 분석
│   ├── analyze_page_layout()    # 레이아웃 분석
│   └── _build_merge_groups()    # 병합 그룹 생성
│
├── pdf_text_replacer.py     # PDF 텍스트 교체
│   ├── replace_texts_in_pdf()
│   ├── _render_text_block()     # 텍스트 렌더링
│   └── _is_invalid_for_rendering()
│
├── image_pipeline.py        # VLM 모델 관리
│   ├── get_vlm_model()          # 모델 로드 (싱글톤)
│   ├── translate_text_vlm()     # VLM 번역 호출
│   └── unload_vlm_model()       # 메모리 해제
│
├── term_corrections.py      # CSV 용어집
│   ├── load_term_corrections()  # CSV 로드
│   ├── get_terms_in_text()      # 텍스트에서 용어 추출
│   └── build_term_replacer()    # 용어 교정기
│
└── pdf_font_handler.py      # 폰트 처리
    └── map_korean_to_english_font()
```

## VLM 번역 상세

### 모델 정보

- **모델**: Qwen3-VL-4B-Instruct
- **양자화**: 4bit (bitsandbytes)
- **VRAM**: ~4GB

### 프롬프트 구조

```
[시스템 프롬프트]
You are a Korean to English translator for educational slides.
Translate accurately while maintaining the original meaning.

[용어집 (텍스트에 해당 용어가 있을 때만)]
Use these term mappings:
- 미시경제학 → Microeconomics
- 거시경제학 → Macroeconomics
...

[번역 요청]
Translate the following Korean text to English:
"{korean_text}"
```

### 용어집 적용 흐름

```
1. get_terms_in_text(korean_text)
   → 텍스트에서 해당 용어 추출

2. 프롬프트에 관련 용어만 포함
   → 불필요한 토큰 낭비 방지

3. translate_text_vlm(prompt)
   → VLM 번역 실행

4. (선택) replace_terms_in_text(result)
   → 번역 결과 후처리 교정
```

## 휴리스틱 병합 판단 기준

### 병합 O (MERGE)
```
- 연결 조사로 끝남: 있는, 없는, 되는, 하는, 어떻게, 얼마나
- 쉼표(,)로 끝나고 다음 블록이 나열 계속
- 열린 괄호가 닫히지 않음: "경제주체들(개인, 기업,"
```

### 병합 X (DO NOT MERGE)
```
- 완전한 문장: 다, 요, 음, 함, 니다
- 종결 부호: ., ?, !
- 제목, 헤딩, 라벨 (독립적)
- 시각적으로 분리된 텍스트
```

## 데이터 흐름 예시

### 입력 (raw_lines)
```json
[
  {"block_id": "p4_l0", "text": "희소성(Scarcity):  한 사회가 가지고 있는"},
  {"block_id": "p4_l1", "text": "자원(resource)은 제한되어 있음"},
  {"block_id": "p4_l2", "text": "경제학(Economics):  사회가 희소한 자원을 어떻게"},
  {"block_id": "p4_l3", "text": "관리하는지를 연구하는 학문"}
]
```

### 휴리스틱 분석 결과
```json
{
  "blocks": [
    {"idx": 0, "merge_with": [1], "on_image": false},
    {"idx": 1, "merge_with": [], "on_image": false},
    {"idx": 2, "merge_with": [3], "on_image": false},
    {"idx": 3, "merge_with": [], "on_image": false}
  ],
  "merge_groups": [
    ["p4_l0", "p4_l1"],
    ["p4_l2", "p4_l3"]
  ]
}
```

### 병합 후 (korean_texts)
```json
[
  {
    "block_id": "p4_b0",
    "text": "희소성(Scarcity):  한 사회가 가지고 있는 자원(resource)은 제한되어 있음",
    "merged_block_ids": ["p4_l0", "p4_l1"]
  },
  {
    "block_id": "p4_b1",
    "text": "경제학(Economics):  사회가 희소한 자원을 어떻게 관리하는지를 연구하는 학문",
    "merged_block_ids": ["p4_l2", "p4_l3"]
  }
]
```

### VLM 번역 결과
```json
[
  {
    "block_id": "p4_b0",
    "translated": "Scarcity: A society's resources are limited"
  },
  {
    "block_id": "p4_b1",
    "translated": "Economics: The study of how society manages scarce resources"
  }
]
```

## 에러 처리 및 복구

### Fragment Recovery
```
1. 번역 결과가 fragment로 판단되면
2. 인접 블록과 병합하여 재번역 시도
3. 성공 시 원본 블록은 skip 처리 (_merged_into 마킹)
```

### Invalid Translation 방지
```
1. "???" 패턴 감지 → 렌더링 스킵
2. 한글 잔존 감지 → 렌더링 스킵
3. block_id 패턴 감지 → 렌더링 스킵
```

## 성능 고려사항

| 단계 | 소요 시간 | 비고 |
|------|----------|------|
| VLM 로드 | ~10초 | 최초 1회 (4bit) |
| 휴리스틱 분석 (페이지당) | ~5초 | 규칙 기반 |
| VLM 번역 (블록당) | ~2-3초 | Qwen3-VL-4B |
| PDF 교체 | <1초 | PyMuPDF |

## 향후 개선 방향

1. **용어집 확장**: 더 많은 도메인 용어 추가
2. **캐싱**: 동일 텍스트 번역 결과 캐싱
3. **병렬 처리**: 페이지별 병렬 번역
4. **폰트 임베딩**: 다양한 영문 폰트 지원
