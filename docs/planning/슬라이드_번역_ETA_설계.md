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
   - VLM 번역(Qwen2.5-VL-7B-Instruct, 4bit): 텍스트 길이 / 토큰 수에 따라 15 ~ 60초 편차
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
| `stage_started_at` | float | 단계 시작 시각 (epoch) — bundling ETA 계산 기준점 |
| `last_page_at` | float | 마지막 페이지 완료 시각 — ocr/translate elapsed 계산 기준점 |
| `avg_page_duration` | float | 현재 단계의 페이지당 평균 시간 (EMA) |

> ETA 값은 anchor로 저장하지 않습니다. `/status` 응답 시점마다 `_compute_eta_seconds()`가 즉시 계산합니다.

### 3.2 통합 잔여 시간 계산 — `_unified_remaining()`

핵심 아이디어 2가지:
1. **현재 단계만 보지 말고 후속 단계까지 합산해서 ETA 한 줄로 통합**
2. **현재 페이지 elapsed 가 baseline 을 초과해도 (overrun) ETA 가 음수로 진입해 wall-clock 흐름이 그대로 반영됨** → 매초 1초씩 자연 감소, 페이지 완료 시 다음 페이지로 자연 이어짐

```python
_BASELINE_SECONDS_PER_PAGE = {
    "ocr": 15.0,       # Surya OCR 한 장 처리 추정치 — 첫 실행 시 fallback
    "translate": 50.0, # Qwen2.5-VL 4bit GPU 한 장 번역 추정치 — 첫 실행 시 fallback
}
_BUNDLING_BASELINE = 3.0  # PDF 묶기 짧은 고정값


def _unified_remaining(stage: str, total: int, current: int, avg: float, elapsed_on_current: float) -> Optional[float]:
    """현재 단계 + 후속 단계의 남은 작업 시간 합산.

    현재 페이지의 elapsed 를 음수까지 허용해 wall-clock 흐름이 ETA 에 그대로 반영되게 함.
    → 매초 ETA 가 약 1초씩 감소 (시간 흐름이 카운트다운으로 시각화됨).
    → 페이지가 baseline 을 초과해도 ETA 가 계속 줄어 0 까지 수렴 (stuck 인지 UX 로 감지 가능).
    → max(0, ...) 로 음수 출력 방지."""
    pages_remaining = max(0, total - current)

    def _in_progress_overrun(per_page: float) -> float:
        """현재 페이지 남은 시간 — overrun 허용 (음수 가능). 새 페이지 시작 시 reset."""
        return per_page - elapsed_on_current

    if stage == "ocr":
        per_page = avg if avg > 0 else _baseline_for("ocr")
        ocr_remaining = (_in_progress_overrun(per_page) + per_page * (pages_remaining - 1)) if pages_remaining > 0 else 0.0
        translate_remaining = _baseline_for("translate") * total  # 아직 시작 안 한 단계
        return max(0.0, ocr_remaining + translate_remaining + _BUNDLING_BASELINE)

    if stage == "translate":
        per_page = avg if avg > 0 else _baseline_for("translate")
        if pages_remaining > 0:
            translate_remaining = _in_progress_overrun(per_page) + per_page * (pages_remaining - 1)
        else:
            translate_remaining = 0.0
        # bundling baseline은 더하지 않음 — 번역 완료 직전 ETA가 3초로 점프하는 혼란 방지
        return max(0.0, translate_remaining)

    if stage == "bundling":
        return max(0.0, _BUNDLING_BASELINE - elapsed_on_current)

    return None
```

OCR 단계에서는 OCR 잔여 + 번역 전체 baseline 모두 포함하므로,
**OCR이 끝나도 ETA가 0으로 떨어지지 않고 매끄럽게 번역 단계로 이어집니다.**

페이지가 baseline 50초인데 실측 200초가 되면 `_in_progress_overrun` 이 `-150` 을 반환 → 남은 페이지들 baseline 합과 더해져서 전체 ETA 가 자연스럽게 줄어들고 0 으로 수렴. 페이지가 실제 끝나면 stage_current 가 +1 되어 ETA 재계산 (다음 페이지 기준).

### 3.2.1 학습 baseline 영속화 — `_baseline_for()` / `_save_learned_baseline()`

이전 강의 세션의 페이지 평균을 디스크에 저장 → 다음 세션 첫 페이지 추정에 활용.

```python
# 캐시 파일 경로 (운영 vs dev 자동 분기)
if getattr(sys, "frozen", False):
    # 운영 (Electron 패키지된 PyInstaller 백엔드)
    _ETA_CACHE_PATH = Path(_LOCALAPPDATA or str(Path.home())) / "Aunion AI" / "cache" / "eta_learned.json"
else:
    # dev
    _ETA_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "cache" / "eta_learned.json"

# 합리적 범위 — 이상치 (GPU 일시 stuck 등) 저장 차단
_SANITY_RANGE = {"ocr": (2.0, 60.0), "translate": (5.0, 300.0)}

_LEARNED_BASELINES = _load_learned_baselines()  # 모듈 import 시점 1회 로드


def _baseline_for(stage: str) -> float:
    """학습된 값 우선, 없으면 하드코딩 baseline 폴백."""
    if stage in _LEARNED_BASELINES:
        return _LEARNED_BASELINES[stage]
    return _BASELINE_SECONDS_PER_PAGE.get(stage, 30.0)


def _save_learned_baseline(stage: str, avg: float) -> None:
    """페이지 완료 시 호출. 합리적 범위만 저장 (이상치 필터)."""
    if avg <= 0:
        return
    lo, hi = _SANITY_RANGE.get(stage, (0.0, 600.0))
    if not (lo <= avg <= hi):
        return  # 이상치 — 저장 안 함
    _LEARNED_BASELINES[stage] = avg
    _ETA_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_ETA_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(_LEARNED_BASELINES, f, indent=2)
```

| 시나리오 | 동작 |
|---------|------|
| 첫 강의 (캐시 파일 없음) | 하드코딩 baseline 50초 사용 |
| 첫 강의 끝 | 실측 평균 (예: 35초) 가 `eta_learned.json` 에 저장 |
| 두 번째 강의 첫 페이지 | 35초 추정 (실측 기반, 첫 페이지부터 정확) |
| GPU 일시 stuck 등 이상치 (>300초) | 저장 안 함 → 이전 정상값 유지 |

### 3.3 단계 전환 — `_set_stage()`

```python
def _set_stage(slide_id, stage, total):
    s["stage"] = stage
    s["stage_current"] = 0
    s["stage_total"] = total
    s["stage_started_at"] = now
    s["last_page_at"] = now
    s["avg_page_duration"] = 0.0   # 이전 단계 평균 폐기 (OCR과 번역은 다른 작업)
```

`avg_page_duration`을 리셋하는 이유: OCR과 번역은 다른 작업이라 평균값을 공유하면 안 됨.

ETA는 anchor로 저장하지 않고 `/status` 응답 시점마다 즉시 계산합니다 (`_compute_eta_seconds()` 참조).

### 3.4 페이지 완료 시 — `_page_completed()`

```python
def _page_completed(slide_id, current):
    duration = now - last_page_at  # 이번 페이지 실측 소요시간
    s["last_page_at"] = now
    s["stage_current"] = current

    prev = s["avg_page_duration"]
    if prev == 0.0:
        # 첫 페이지: 학습된 baseline (이전 세션) 또는 하드코딩 baseline 과 실측치 5:5 블렌딩
        baseline = _baseline_for(stage) if stage in ("ocr", "translate") else duration
        s["avg_page_duration"] = 0.5 * baseline + 0.5 * duration
    else:
        # 두 번째부터: 느린 EMA (alpha=0.25)
        s["avg_page_duration"] = 0.75 * prev + 0.25 * duration

    # 페이지 완료 시점에 학습 평균을 디스크에 저장 → 다음 세션 첫 페이지 추정 정확도 ↑.
    _save_learned_baseline(stage, s["avg_page_duration"])
```

세 가지 점프 완화 장치:

1. **첫 페이지 블렌딩**: baseline이 50초인데 실측이 100초여도 평균은 75초로 시작 → 후속 추정 점프 절반
2. **느린 EMA(α=0.25)**: 페이지마다 변동이 커도 평균은 천천히 따라감 → 페이지 간 점프 작음
3. **학습 baseline 영속화**: 이전 세션 평균이 baseline 으로 들어와 다음 세션 첫 페이지부터 더 정확

### 3.5 `/slides/status` 응답에서 ETA 계산 — `_compute_eta_seconds()`

폴링 응답 시점에 현재 페이지의 경과 시간을 반영해 즉시 계산:

```python
def _compute_eta_seconds(s: dict, now: float) -> Optional[float]:
    """anchor 캐싱 없이 매 /status 응답 시 즉시 계산.
    현재 페이지의 elapsed 시간도 반영하므로 페이지 완료 전에도 ETA가 자연스럽게 줄어듦."""
    stage = s.get("stage", "pending")
    if stage in ("pending", "completed", "failed"):
        return None
    total    = s.get("stage_total", 0)
    current  = s.get("stage_current", 0)
    avg      = s.get("avg_page_duration", 0.0)
    # bundling은 stage_started_at 기준, 나머지는 마지막 페이지 완료 시점 기준
    if stage == "bundling":
        elapsed = max(0.0, now - s.get("stage_started_at", now))
    else:
        elapsed = max(0.0, now - s.get("last_page_at", now))
    return _unified_remaining(stage, total, current, avg, elapsed)

@router.get("/status/{slide_id}")
async def get_status(slide_id):
    now = time.time()
    status = slide_status[slide_id]
    eta_seconds = _compute_eta_seconds(status, now)
    return SlideStatus(..., eta_seconds=eta_seconds)
```

anchor를 캐싱하지 않고 `_in_progress_overrun` 이 음수까지 허용하므로 **현재 페이지가 baseline을 초과해도 ETA가 매초 자연스럽게 1초씩 감소하다가 0까지 수렴합니다.** stuck 상태에서도 사용자가 "곧 끝남" 메시지를 보고 비정상 인지 가능.

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
  if (seconds < 1) return ''                                      // ETA=0 → 텍스트 숨김 (UI 상 '잠시만 기다려주세요' 대체 표시)
  if (seconds < 60) return `약 ${Math.ceil(seconds)}초 남음`     // 1분 미만: 초 카운트다운
  return `약 ${Math.ceil(seconds / 60)}분 남음`                  // 1분 이상: 분 단위만 (깜빡임 최소화)
}
```

`seconds < 1`일 때 빈 문자열을 반환하면, UI에서는 별도 로직으로 "AI 번역중..." 스피너를 대신 표시합니다 (`etaReachedZero` 플래그로 전환).

---

## 5. 12장짜리 시뮬레이션

baseline 기준값과 실측치 차이가 클 때를 가정:
- 실측 OCR: 8초/장 (baseline 15초보다 빠름)
- 실측 번역: 35초/장 (baseline 50초보다 빠름)

| 시점 | stage_current/total | avg | ETA 계산 | ETA |
|------|---------------------|-----|----------|-----|
| OCR 시작 | `ocr` 0/12 | 0 | 15×12 + 50×12 + 3 | **15분 3초** |
| OCR 1장 끝 | `ocr` 1/12 | 0.5×15 + 0.5×8 = **11.5** | 11.5×11 + 600 + 3 | **12분 9초** (-2분54초) |
| OCR 2장 끝 | `ocr` 2/12 | 0.75×11.5 + 0.25×8 = **10.6** | 10.6×10 + 600 + 3 | 11분 49초 (-20) |
| OCR 3장 끝 | `ocr` 3/12 | ≈10.0 | 10.0×9 + 600 + 3 | 11분 33초 (-16) |
| OCR 6장 끝 | `ocr` 6/12 | ≈9.0 | 9.0×6 + 600 + 3 | 11분 3초 |
| OCR 12장 끝 | `ocr` 12/12 | ≈8.5 | 8.5×0 + 600 + 3 | **10분 3초** |
| 번역 시작 | `translate` 0/12 | 0 | 50×12 | **10분** ← 점프 없음 (bundling 미합산) |
| 번역 1장 끝 | `translate` 1/12 | 0.5×50 + 0.5×35 = **42.5** | 42.5×11 | 7분 47초 (-2분13초) |
| 번역 2장 끝 | `translate` 2/12 | 0.75×42.5 + 0.25×35 = **40.6** | 40.6×10 | 6분 46초 |
| ... | 점차 35로 수렴 | ... | ... | ... |
| 번역 12장 끝 | `translate` 12/12 | ≈36.0 | 36.0×0 | **0초** → 잠시만 표시 |
| PDF 생성 | `bundling` | - | _BUNDLING_BASELINE | 약 3초 |
| 완료 | - | - | - | - |

전체 약 15분짜리 작업이고, 점프는 **OCR 첫 장** (-2분54초)과 **번역 첫 장** (-2분13초)이 가장 크고, 이후엔 페이지마다 ±20~40초 정도로 안정화됨.

> 번역 단계에서 bundling baseline(3초)을 합산하지 않는 이유: 마지막 번역 페이지 완료 직후 ETA=0이 되어 "잠시만 기다려주세요"로 전환되는 게 자연스럽기 때문.

---

## 6. 알려진 한계

1. **첫 페이지에서 한 번 점프 가능 (완화됨)**
   - 정의상 첫 페이지가 끝나기 전엔 실측치가 없음
   - baseline 5:5 블렌딩 + 학습 baseline 영속화 (`eta_learned.json`) 로 완화
   - 첫 강의 시에만 점프 발생, 두 번째 강의부턴 머신 실측 기반 → 점프 거의 없음
2. **페이지간 편차가 매우 크면 점프 잦음**
   - 어떤 슬라이드는 텍스트가 거의 없고 어떤 슬라이드는 빽빽한 경우
   - EMA가 천천히 따라가지만 매번 새 측정치가 변동을 만듦
3. **PDF 묶기 단계는 추정 안 함**
   - `_BUNDLING_BASELINE = 3.0` 으로 짧게 고정
   - 페이지 수가 많거나 이미지가 큰 PDF는 실제로 더 걸릴 수 있음
4. ~~Baseline은 하드웨어 / 모델에 따라 다름~~ → **해결됨**
   - 학습 baseline 영속화로 머신마다 자체 학습 → 4bit/8bit/CPU 환경 무관하게 적응
   - 단 첫 세션은 하드코딩 baseline (50/15) 사용

---

## 7. 튜닝 가이드

### 7.1 Baseline 값 조정

[backend/app/routers/slides.py](../../backend/app/routers/slides.py) 상단의 상수:

```python
_BASELINE_SECONDS_PER_PAGE = {
    "ocr": 15.0,       # Surya OCR 한 장 처리 추정치
    "translate": 50.0, # Qwen2.5-VL 4bit GPU 한 장 번역 추정치
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
