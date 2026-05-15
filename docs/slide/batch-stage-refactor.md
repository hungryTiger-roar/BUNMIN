# Slide Translation - Stage 기반 배치 구조 리팩토링

## 변경 배경

### 기존 문제점
```
Page 1: Surya 로드 → OCR → Surya 해제 → VLM 로드 → 번역 → VLM 해제
Page 2: Surya 로드 → OCR → Surya 해제 → VLM 로드 → 번역 → VLM 해제
...
Page N: (반복)
```

1. **모델 로딩 시간 과다** - 페이지마다 ~18초 오버헤드
2. **GPU 메모리 OOM** - Surya/VLM 전환 시 메모리 fragmentation
3. **재시작 비용** - 중간 실패 시 처음부터 다시 시작

### 새로운 구조
```
[Stage 3] Surya 로드 → Page 1~N OCR → Surya 해제 → 캐시 저장
[Stage 4] VLM 로드 → Page 1~N 번역 → VLM 해제 → 캐시 저장
```

1. **모델 로드 최소화** - Surya 1회, VLM 1회
2. **OOM 방지** - Surya와 VLM 동시 로드 금지
3. **재시작 지원** - 중간 결과 JSON 캐시

---

## 새로운 파이프라인 구조

```
┌──────────────────────────────────────────────────────────┐
│                    process_slide_pdf_layer                │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│  [Stage 1] 페이지 분류                                    │
│  ├─ pdf_layer_pages     텍스트 레이어 O                   │
│  ├─ ocr_pages           텍스트 레이어 X                   │
│  └─ image_region_pages  이미지 비율 ≥10%                  │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│  [Stage 2] PDF Layer 처리                                 │
│  └─ PDFLayerPipeline (텍스트 추출 → VLM 번역 → 교체)      │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│  [Stage 3] OCR 배치                                       │
│  ├─ VLM 언로드 + GPU 캐시 클리어                          │
│  ├─ Surya 모델 로드 (1회)                                 │
│  ├─ 모든 OCR 대상 페이지 처리                             │
│  ├─ 결과 → uploads/cache/{id}/ocr_*.json                 │
│  └─ Surya 언로드 + GPU 캐시 클리어                        │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│  [Stage 4] VLM 번역 배치                                  │
│  ├─ VLM 모델 로드 (1회, Qwen2.5-VL 4bit)                  │
│  ├─ 한글 포함 페이지만 필터링                             │
│  ├─ 용어집 (term_corrections.csv) 프롬프트에 포함         │
│  ├─ 모든 번역 대상 페이지 처리                            │
│  ├─ 결과 → uploads/cache/{id}/translate_*.json           │
│  └─ VLM 언로드                                            │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│  [Stage 5] Overlay 렌더링 (CPU)                           │
│  └─ 번역 결과 → 이미지에 텍스트 렌더링                    │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│  [Stage 6] PDF 합성                                       │
│  └─ 모든 페이지 이미지 → Hybrid PDF 생성                  │
└──────────────────────────────────────────────────────────┘
```

---

## GPU 메모리 흐름

```
시간 →

[Stage 2]     [Stage 3]           [Stage 4]          [Stage 5-6]
   │              │                   │                   │
   ▼              ▼                   ▼                   ▼
┌──────┐      ┌──────┐            ┌──────┐            ┌──────┐
│ VLM  │      │Surya │            │ VLM  │            │ CPU  │
│ ~4GB │  →   │ ~4GB │     →      │ ~4GB │     →      │ only │
│(4bit)│      │      │            │(4bit)│            │      │
└──────┘      └──────┘            └──────┘            └──────┘
    ↓          ↑      ↓            ↑      ↓
 언로드     GPU 캐시  GPU 캐시   GPU 캐시  GPU 캐시
             클리어    클리어     클리어    클리어
```

**핵심: VLM과 Surya가 절대 동시에 GPU에 올라가지 않음**

---

## 중간 결과 캐시 구조

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
- Stage 3 실패 → OCR 캐시 있는 페이지는 스킵
- Stage 4 실패 → 번역 캐시 있는 페이지는 스킵

---

## 배치 함수

### VLM 관리
```python
get_vlm_model()           # 싱글톤 로드 (Qwen2.5-VL 4bit)
is_vlm_loaded()           # 로드 상태 확인
unload_vlm_model()        # 메모리 해제
translate_text_vlm(prompt) # VLM 번역 호출
```

### `batch_ocr_surya()`
```python
batch_ocr_surya(
    image_paths: list[tuple[int, str]],  # [(page_idx, path), ...]
    slide_id: str,                        # 캐시 저장용
    chunk_size: int = 5                   # OCR_CHUNK_SIZE
) -> dict[int, list]                      # {page_idx: regions}
```

### `batch_translate_vlm()`
```python
batch_translate_vlm(
    ocr_results: dict[int, list],         # {page_idx: regions}
    image_paths: dict[int, str],          # {page_idx: path}
    slide_id: str,
    chunk_size: int = 2
) -> dict[int, list]                      # {page_idx: translated_regions}
```

### `batch_overlay()`
```python
batch_overlay(
    translate_results: dict[int, list],
    image_paths: dict[int, str],
    output_dir: str,
    slide_id: str
) -> dict[int, str]                       # {page_idx: output_path}
```

---

## 설정 옵션

| 환경변수 | 기본값 | 설명 |
|---------|--------|------|
| `OCR_CHUNK_SIZE` | 5 | Surya 한 번 로드로 처리할 페이지 수 |
| `CACHE_DIR` | uploads/cache | 중간 결과 캐시 디렉토리 |

---

## 성능 비교

| 항목 | Before (페이지 단위) | After (Stage 배치) |
|------|---------------------|-------------------|
| 10페이지 모델 로드 | Surya 10회 + VLM 10회 | Surya 1회 + VLM 1회 |
| 모델 로딩 오버헤드 | ~180초 | ~18초 |
| OOM 위험 | 높음 (매번 전환) | 낮음 (순차 처리) |
| 메모리 fragmentation | 발생 | 최소화 |
| 중간 실패 시 | 처음부터 재시작 | 캐시된 Stage부터 재개 |

---

## 변경된 파일

| 파일 | 변경 내용 |
|-----|----------|
| `slides.py` | `process_slide_pdf_layer()` Stage 기반 리팩토링 |
| `image_pipeline.py` | VLM 관리 + `batch_ocr_surya()`, `batch_translate_vlm()`, `batch_overlay()` |
| `image_pipeline.py` | 캐시 함수 추가 (`save_ocr_cache`, `load_ocr_cache` 등) |
| `pdf_pipeline.py` | VLM 번역 사용 (`translate_text_vlm()`) |
| `term_corrections.py` | CSV 기반 용어집 |
| `.env.example` | `OCR_CHUNK_SIZE`, `CACHE_DIR` 추가 |

---

## 핵심 정책

1. **VLM과 Surya 동시 로드 금지**
2. **페이지마다 모델 로드/언로드 하지 않음**
3. **Stage 전환 시 GPU 메모리 철저히 정리**
   - `gc.collect()`
   - `torch.cuda.empty_cache()`
   - `torch.cuda.synchronize()`
4. **중간 결과 JSON 캐시로 재시작 지원**
5. **용어집 (term_corrections.csv) 프롬프트에 자동 포함**
