# Slide Translation Module Dependency Report

## 개요: 두 가지 파이프라인 병행 사용

| 파이프라인 | 메인 파일 | 용도 | 입력 |
|-----------|----------|------|------|
| **PDF Layer** | `pdf_pipeline.py` | PDF 텍스트 레이어 직접 수정 | PDF (텍스트 레이어 있음) |
| **Image OCR** | `image_pipeline.py` | 이미지 OCR + 오버레이 | 이미지, PDF (텍스트 레이어 없음) |

---

## Image OCR 파이프라인 (image_pipeline)

### 위치
`backend/app/services/slide_translation/image_pipeline.py`

### 호출 흐름
```
slides.py (router)
└── image_pipeline.py
    ├── stage_ocr_surya(): Surya OCR 실행
    ├── stage_translate(): VLM 번역
    ├── stage_overlay(): 이미지에 텍스트 오버레이
    ├── get_vlm_model(): VLM 모델 싱글톤
    ├── is_vlm_loaded(): VLM 로드 상태 확인
    └── unload_vlm_model(): VLM 모델 메모리 해제
```

### 사용처
- `backend/app/routers/slides.py`: 이미지 번역 시 사용
- `backend/app/routers/mode.py`: VLM 모델 로드/언로드
- `bbox_analyzer.py`: VLM 모델 공유

---

## PDF Layer 파이프라인 (pdf_pipeline)

### 호출 흐름
```
slides.py (router)
└── pdf_pipeline.py (메인 오케스트레이터)
    ├── pdf_text_extractor.py (PDF 텍스트 추출)
    ├── pdf_text_replacer.py (PDF 텍스트 교체)
    │   └── pdf_font_handler.py (폰트 매핑)
    ├── llm_client.py (LLM 클라이언트)
    └── bbox_analyzer.py (VLM 레이아웃 분석)
```

### A. 현재 사용 중인 파일 (7개)

| 파일 | 역할 | 상태 |
|------|------|------|
| `image_pipeline.py` | 이미지 OCR + VLM 번역 파이프라인 | ✅ Active |
| `pdf_pipeline.py` | PDF 텍스트 레이어 번역 파이프라인 | ✅ Active |
| `pdf_text_extractor.py` | PDF에서 한글 텍스트 블록 추출 | ✅ Active |
| `pdf_text_replacer.py` | PDF 텍스트 교체, multi-color 렌더링 | ✅ Active |
| `pdf_font_handler.py` | 한글→영어 폰트 매핑, 색상 변환 | ✅ Active |
| `llm_client.py` | OpenAI/Gemini LLM 클라이언트 | ✅ Active |
| `bbox_analyzer.py` | VLM 기반 레이아웃 분석 | ✅ Active |

---

## 미사용 경로 (구 pipeline.py)

### B. 미사용이지만 보존 가치 있음

| 파일 | 라인수 | 역할 | 보존 이유 |
|------|--------|------|-----------|
| `translation.py` | 1421 | 배치 번역, 재시도, 무효 번역 감지 | `_is_invalid_translation` 등 유틸 참고용 |
| `validation.py` | 1256 | 번역 품질 검증 | 품질 검증 로직 참고용 |
| `residual_audit.py` | 1667 | 최종 한글 잔존 검사 | 잔존 한글 감지 로직 참고용 |
| `pipeline.py` | 1798 | 전체 OCR 파이프라인 | OCR fallback 시 필요 |
| `image_rendering.py` | 913 | 이미지 기반 렌더링 | OCR fallback 참고용 |
| `block_building.py` | 1079 | 블록 그룹화/병합 | 병합 아이디어 참고용 |
| `token_protection.py` | 471 | 고유명사/토큰 보호 | 토큰 보호 로직 참고용 |

### C. 미사용이고 정리 후보

| 파일 | 라인수 | 역할 | 정리 이유 |
|------|--------|------|-----------|
| `config.py` | 123 | 구 파이프라인 설정 | pdf_layer_pipeline에서 미사용 |
| `ocr_normalization.py` | 225 | OCR 정규화 | pdf_layer에서 미사용 |
| `deduplication.py` | 248 | 중복 제거 | pdf_layer에서 미사용 |
| `noise_classification.py` | 730 | 노이즈 분류 | pdf_layer에서 미사용 |
| `candidate_extraction.py` | 603 | 후보 추출 | pdf_layer에서 미사용 |
| `glossary_classification.py` | 357 | 용어집 분류 | pdf_layer에서 미사용 |
| `region_classification.py` | 624 | 영역 분류 | pdf_layer에서 미사용 |
| `reading_order.py` | 399 | 읽기 순서 | pdf_layer에서 미사용 |
| `render_role.py` | 718 | 렌더 역할 결정 | pdf_layer에서 미사용 |
| `domain_glossary.py` | 240 | 도메인 용어집 | pdf_layer에서 미사용 |
| `image_text_extraction.py` | 574 | 이미지 텍스트 추출 | pdf_layer에서 미사용 |
| `image_text_translation.py` | 231 | 이미지 텍스트 번역 | pdf_layer에서 미사용 |

---

## 권장 작업

### 즉시 수행
1. ✅ 현재 사용 중인 6개 파일에 역할 주석 추가
2. ✅ `translation.py`에서 `_is_invalid_translation` 유틸 복사
3. ⏳ 테스트로 결과 확인

### 추후 수행
4. 미사용 파일 `legacy/` 폴더로 이동 (테스트 후)
5. `__init__.py` 정리

---

## 주의사항

- **삭제 금지**: OCR fallback, hybrid mode에서 필요할 수 있음
- **translation.py 교체 금지**: 전체 교체 시 multi-color 렌더링 깨질 수 있음
- **테스트 필수**: 경제학 1~4페이지, 운영체제 2~4페이지 확인
