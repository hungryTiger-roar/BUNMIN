# 슬라이드 번역 진행률 / ETA 추정 시스템

> 강의자료 PDF 업로드 후 OCR → VLM 번역 → PDF 묶기 단계의
> 통합 ETA(남은 시간) 표시 동작 설명

관련 파일:
- 백엔드: [backend/app/routers/slides.py](../../backend/app/routers/slides.py) — 상태 추적, ETA 계산, `/slides/status` 응답
- 프론트엔드: [frontend/src/components/lecturer/SlideUpload.tsx](../../frontend/src/components/lecturer/SlideUpload.tsx) — 폴링, 카운트다운 표시

---

## 1. 왜 완벽한 ETA 예측은 불가능한가?

슬라이드 번역 파이프라인은 다음 두 가지가 사전에 알려져 있지 않습니다.

1. **페이지당 처리 시간이 가변적**
   - OCR(Surya): 페이지의 텍스트 양 / 레이아웃 복잡도에 따라 3 ~ 15초 편차
   - VLM 번역(Qwen3-VL-8B-Instruct + LoRA, 4bit): 텍스트 길이 / 토큰 수에 따라 15 ~ 60초 편차
   - 같은 슬라이드 내에서도 페이지마다 다름
2. **첫 페이지가 끝나기 전엔 측정값 자체가 0개**
   - "이 슬라이드의 평균 시간"을 알기 전에 ETA를 추정해야 함
   - → baseline 값으로 가추정하고, 측정치가 들어오는 대로 보정하는 방식

따라서 본 시스템은 **"점차 정확해지는 추정"** 을 목표로 합니다. 첫 페이지가 baseline과 다르면 한 번 점프하고, 이후엔 점차 안정화됩니다.

---

## 2. 전체 동작 흐름

```
[프론트]                              [백엔드]
SlideUpload                           process_slide() 백그라운드 태스크
   │                                     │
   │  /slides/upload (PDF)               │
   │ ────────────────────────────────►  │
   │                                     │ _set_stage("ocr", N)        ← OCR 단계 시작
   │  slide_id 응답                      │   eta_anchor = baseline 합계
   │ ◄────────────────────────────────  │
   │                                     │
   │  /slides/status (2초마다 폴링)      │ ┌─ for page in N:
   │ ────────────────────────────────►  │ │   stage_ocr_surya(page)
   │                                     │ │   _page_completed(page)   ← anchor 갱신
   │  { stage, eta_seconds, ... }        │ │
   │ ◄────────────────────────────────  │ └─
   │                                     │
   │  setEtaAnchor({ value, at })        │ _set_stage("translate", N)  ← 번역 단계
   │  → 1초마다 displayEta -= 1          │   eta_anchor 재계산
   │                                     │
   │  ...                                │ ┌─ for page in N:
   │                                     │ │   stage_translate(page)
   │                                     │ │   _page_completed(page)
   │                                     │ └─
   │                                     │
   │                                     │ _set_stage("bundling", 0)   ← PDF 묶기
   │  ...                                │ Image.save(format="PDF")
   │                                     │
   │  status === 'completed'             │ status = "completed"
   │ ◄────────────────────────────────  │
   │                                     │
   │  setSlideStatus('ready')            │
   │  → "준비 완료" UI                   │
```

---

## 3. 백엔드 — 통합 ETA 계산

### 3.1 데이터 모델 — `slide_status[slide_id]`

업로드 시점에 다음 필드로 초기화됨:

| 필드 | 타입 | 의미 |
|------|------|------|
| `status` | str | `pending` / `processing` / `completed` / `failed` |
| `total_pages` | int | PDF 전체 페이지 수 |
| `processed_pages` | int | 번역까지 끝난 페이지 수 (legacy 카운터) |
| `stage` | str | `pending` / `ocr` / `translate` / `bundling` / `completed` / `failed` |
| `stage_current` | int | 현재 단계에서 끝난 페이지 수 |
| `stage_total` | int | 현재 단계에서 처리할 전체 페이지 수 |
| `stage_started_at` | float | 단계 시작 시각 (epoch) |
| `last_page_at` | float | 마지막 페이지 완료 시각 — duration 측정 기준점 |
| `avg_page_duration` | float | 현재 단계의 페이지당 평균 시간 (EMA) |
| `eta_anchor_seconds` | float \| None | 마지막 갱신 시점의 ETA 값 |
| `eta_anchor_at` | float | 그 anchor를 찍은 시각 (epoch) |

### 3.2 통합 잔여 시간 계산 — `_unified_remaining()`

핵심 아이디어: **현재 단계만 보지 말고 후속 단계까지 합산해서 ETA 한 줄로 통합**.

```python
_BASELINE_SECONDS_PER_PAGE = {
    "ocr": 10.0,        # Surya OCR 한 장 추정치
    "translate": 30.0,  # Qwen3-VL 4bit GPU 한 장 추정치
}
_BUNDLING_BASELINE = 3.0  # PDF 묶기 짧은 고정값

def _unified_remaining(stage, total, current, avg) -> Optional[float]:
    remaining_in_stage = max(0, total - current)

    if stage == "ocr":
        ocr_per_page = avg if avg > 0 else _BASELINE_SECONDS_PER_PAGE["ocr"]
        ocr_remaining = ocr_per_page * remaining_in_stage
        translate_remaining = _BASELINE_SECONDS_PER_PAGE["translate"] * total
        return ocr_remaining + translate_remaining + _BUNDLING_BASELINE

    if stage == "translate":
        translate_per_page = avg if avg > 0 else _BASELINE_SECONDS_PER_PAGE["translate"]
        return translate_per_page * remaining_in_stage + _BUNDLING_BASELINE

    if stage == "bundling":
        return _BUNDLING_BASELINE

    return None
```

OCR 단계에서는 OCR 잔여 + 번역 전체 baseline 모두 포함하므로,
**OCR이 끝나도 ETA가 0으로 떨어지지 않고 매끄럽게 번역 단계로 이어집니다.**

### 3.3 단계 전환 — `_set_stage()`

```python
def _set_stage(slide_id, stage, total):
    s["stage"] = stage
    s["stage_current"] = 0
    s["stage_total"] = total
    s["stage_started_at"] = now
    s["last_page_at"] = now
    s["avg_page_duration"] = 0.0   # 이전 단계 평균 폐기
    s["eta_anchor_at"] = now
    s["eta_anchor_seconds"] = _unified_remaining(stage, total, 0, 0.0)
```

`avg_page_duration`을 리셋하는 이유: OCR과 번역은 다른 작업이라 평균값을 공유하면 안 됨.

`eta_anchor_seconds`는 baseline 기반으로 시드되므로,
**첫 페이지가 끝나기 전에도 ETA가 보입니다.**

### 3.4 페이지 완료 시 — `_page_completed()`

```python
def _page_completed(slide_id, current):
    duration = now - last_page_at  # 이번 페이지 실측 소요시간
    s["last_page_at"] = now
    s["stage_current"] = current

    prev = s["avg_page_duration"]
    if prev == 0.0:
        # 첫 페이지: baseline과 실측치를 5:5 블렌딩
        baseline = _BASELINE_SECONDS_PER_PAGE.get(stage, duration)
        s["avg_page_duration"] = 0.5 * baseline + 0.5 * duration
    else:
        # 두 번째부터: 느린 EMA (alpha=0.25)
        s["avg_page_duration"] = 0.75 * prev + 0.25 * duration

    s["eta_anchor_seconds"] = _unified_remaining(stage, total, current, avg)
    s["eta_anchor_at"] = now
```

두 가지 점프 완화 장치:

1. **첫 페이지 블렌딩**: baseline이 30초인데 실측이 60초여도 평균은 45초로 시작 → 후속 추정 점프 절반
2. **느린 EMA(α=0.25)**: 페이지마다 변동이 커도 평균은 천천히 따라감 → 페이지 간 점프 작음

### 3.5 `/slides/status` 응답에서 ETA 계산

폴링 응답 시점에 anchor에서 흐른 시간만큼 감산:

```python
@router.get("/status/{slide_id}")
async def get_status(slide_id):
    status = slide_status[slide_id]
    anchor = status.get("eta_anchor_seconds")
    eta_seconds = None
    if anchor is not None:
        elapsed = max(0.0, time.time() - status.get("eta_anchor_at"))
        eta_seconds = max(0.0, anchor - elapsed)
    return SlideStatus(..., eta_seconds=eta_seconds)
```

이 한 줄 덕분에 **폴링 간격(2초) 사이에 ETA가 절대 늘어나지 않음** — 백엔드에서 시간이 흐른 만큼 알아서 빼고 응답.

---

## 4. 프론트엔드 — 부드러운 카운트다운

### 4.1 폴링 + 앵커 저장 — [SlideUpload.tsx](../../frontend/src/components/lecturer/SlideUpload.tsx)

```typescript
const [etaAnchor, setEtaAnchor] = useState<{ value: number; at: number } | null>(null)
const [displayEta, setDisplayEta] = useState<number | null>(null)

// /slides/status 폴링 결과
const eta = data.eta_seconds
if (typeof eta === 'number') {
  setEtaAnchor({ value: eta, at: Date.now() })
} else {
  setEtaAnchor(null)
}
```

### 4.2 클라이언트 타이머 — 1초마다 카운트다운

```typescript
useEffect(() => {
  if (etaAnchor === null) {
    setDisplayEta(null)
    return
  }
  const tick = () => {
    const elapsed = (Date.now() - etaAnchor.at) / 1000
    setDisplayEta(Math.max(0, etaAnchor.value - elapsed))
  }
  tick()
  const id = setInterval(tick, 1000)
  return () => clearInterval(id)
}, [etaAnchor])
```

**동작 원리**:
- 폴링으로 받은 `eta_seconds` 를 anchor로 저장
- 1초마다 `(현재시각 - anchor 시각)` 만큼 빼서 표시
- 다음 폴링 시 새 anchor가 오면 자연스럽게 스냅

폴링이 2초 간격이지만 화면은 1초마다 갱신되므로 시계처럼 보임.

### 4.3 표시 포맷 — `formatEta()`

```typescript
function formatEta(seconds: number): string {
  if (seconds < 1) return '거의 다 됨'
  if (seconds < 60) return `약 ${Math.ceil(seconds)}초 남음`
  const min = Math.floor(seconds / 60)
  const sec = Math.ceil(seconds % 60)
  if (sec === 0 || sec === 60) return `약 ${sec === 60 ? min + 1 : min}분 남음`
  return `약 ${min}분 ${sec}초 남음`
}
```

---

## 5. 12장짜리 시뮬레이션

baseline 기준값과 실측치 차이가 클 때를 가정:
- 실측 OCR: 5초/장 (baseline 10초의 절반)
- 실측 번역: 25초/장 (baseline 30초보다 약간 빠름)

| 시점 | stage_current/total | avg | ETA 계산 | ETA |
|------|---------------------|-----|----------|-----|
| OCR 시작 | `ocr` 0/12 | 0 | 10×12 + 30×12 + 3 | **8분 3초** |
| OCR 1장 끝 | `ocr` 1/12 | 0.5×10 + 0.5×5 = **7.5** | 7.5×11 + 360 + 3 | 7분 26초 (-37) |
| OCR 2장 끝 | `ocr` 2/12 | 0.75×7.5 + 0.25×5 = **6.9** | 6.9×10 + 360 + 3 | 7분 12초 (-14) |
| OCR 3장 끝 | `ocr` 3/12 | **6.4** | 6.4×9 + 360 + 3 | 7분 1초 (-11) |
| OCR 6장 끝 | `ocr` 6/12 | ≈5.5 | 5.5×6 + 360 + 3 | 6분 36초 |
| OCR 12장 끝 | `ocr` 12/12 | ≈5.1 | 5.1×0 + 360 + 3 | **6분 3초** |
| 번역 시작 | `translate` 0/12 | 0 | 30×12 + 3 | **6분 3초** ← 점프 없음 |
| 번역 1장 끝 | `translate` 1/12 | 0.5×30 + 0.5×25 = **27.5** | 27.5×11 + 3 | 5분 5초 (-58) |
| 번역 2장 끝 | `translate` 2/12 | 0.75×27.5 + 0.25×25 = **26.9** | 26.9×10 + 3 | 4분 32초 |
| ... | 점차 25로 수렴 | ... | ... | ... |
| 번역 12장 끝 | `translate` 12/12 | ≈25.4 | 25.4×0 + 3 | 약 3초 |
| PDF 생성 | `bundling` | - | _BUNDLING_BASELINE | 약 3초 |
| 완료 | - | - | - | - |

전체 약 8분짜리 작업이고, 점프는 **첫 페이지 두 번** (OCR 첫장, 번역 첫장) 이 가장 크고, 이후엔 페이지마다 ±5~15초 정도로 안정화됨.

---

## 6. 알려진 한계

1. **첫 페이지에서 한 번 큰 점프 불가피**
   - 정의상 첫 페이지가 끝나기 전엔 실측치가 없음
   - baseline 5:5 블렌딩으로 점프 크기를 절반으로 줄였지만 0은 아님
2. **페이지간 편차가 매우 크면 점프 잦음**
   - 어떤 슬라이드는 텍스트가 거의 없고 어떤 슬라이드는 빽빽한 경우
   - EMA가 천천히 따라가지만 매번 새 측정치가 변동을 만듦
3. **PDF 묶기 단계는 추정 안 함**
   - `_BUNDLING_BASELINE = 3.0` 으로 짧게 고정
   - 페이지 수가 많거나 이미지가 큰 PDF는 실제로 더 걸릴 수 있음
4. **Baseline은 하드웨어 / 모델에 따라 다름**
   - 4bit GPU 환경 기준이라 다른 환경(8bit, CPU)에선 부정확

---

## 7. 튜닝 가이드

### 7.1 Baseline 값 조정

[backend/app/routers/slides.py](../../backend/app/routers/slides.py) 상단의 상수:

```python
_BASELINE_SECONDS_PER_PAGE = {
    "ocr": 10.0,
    "translate": 30.0,
}
_BUNDLING_BASELINE = 3.0
```

데모 환경에서 평균 측정치가 다르면 이 값만 조정하면 됨. 가능하면 **실측 평균보다 살짝 크게** 잡는 게 점프가 늘어나는 것보다 줄어드는 게 자연스러움.

### 7.2 EMA alpha 조정

`_page_completed()` 안:

```python
s["avg_page_duration"] = 0.75 * prev + 0.25 * duration  # alpha=0.25
```

- alpha 키우면 (예: 0.5): 평균이 빠르게 따라가지만 페이지 변동에 민감 → 점프 ↑
- alpha 줄이면 (예: 0.1): 부드럽지만 실제 추세에 늦게 반응 → 끝까지 어긋난 ETA

### 7.3 첫 페이지 블렌딩 비율

```python
s["avg_page_duration"] = 0.5 * baseline + 0.5 * duration
```

- baseline 비중 크게 (예: 0.7): 첫 페이지 점프 더 줄어듦, 단 baseline이 부정확하면 끝까지 어긋남
- 실측 비중 크게 (예: 0.3): 빠르게 실제값 따라가지만 첫 페이지 점프 커짐

---

## 8. 참고

- 폴링 간격은 [SlideUpload.tsx](../../frontend/src/components/lecturer/SlideUpload.tsx) 의 `setTimeout(checkStatus, 2000)` — 2초 고정
- 클라이언트 카운트다운 간격은 `setInterval(tick, 1000)` — 1초 고정
- `slide_status` 는 in-memory 딕셔너리 — 백엔드 재시작 시 초기화됨 (PDF는 `uploads/` 에 남아있음)
