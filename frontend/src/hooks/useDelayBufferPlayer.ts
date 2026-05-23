/**
 * useDelayBufferPlayer — 적응형 wall-clock delay buffer.
 *
 * 고정 lag 대신 "지금 필요한 만큼만" 지연 — 처리시간(ASR+NMT+네트워크+TTS합성)을
 * 추적해 currentDelay 를 동적으로 조정. silence 구간에서 큐가 비면 자연히 최소값에 수렴.
 *
 *   - currentDelay = recentP90(필요딜레이) + max(300ms, stddev × 1.5)
 *       · 늘릴 땐 즉시 (desync 방지 우선), 줄일 땐 천천히 EWMA (원본 음성 jump 완화)
 *       · 클램프 [2s, 20s]
 *   - 모든 event (시각/음성/자막/lifecycle) 가 같은 currentDelay 사용 → 상호 동기 유지
 *   - monotonic — 직전 event 보다 늦게 스케줄 (순서 보장, currentDelay 줄면 압축 재생)
 *   - 원본 음성 DelayNode 는 Student.tsx 가 getCurrentDelay() 폴링해 동적 조정
 *
 *   late event: target_wall < now 면 setTimeout(0) 즉시 (사라지지 않음)
 *   STALE drop: currentDelay + 10s 초과 시만 (pause 후 옛 frame 같은 진짜 stale 만 — 정상 발화는 절대 안 버려짐)
 *
 * 비유: "적응형 유튜브 라이브" — lag 이 네트워크/처리 상황 따라 출렁이되 모든 트랙이 함께 출렁임.
 */
import { useCallback, useEffect, useRef } from 'react'
import type { AudioLang } from '@/stores/preferencesStore'

/** 학생측 player 인터페이스 — useWebSocket 가 incoming event 를 라우팅하는 표면. */
export interface UnitPlayer {
  /** visual event (그림/커서/페이지) 등록. */
  enqueueVisual: (ts: number, apply: () => void, kind?: string) => void
  /** transcription 도착 시 호출 — sentence audio + commitSubtitle 예약. */
  enqueueSentence: (params: {
    text: string
    commitSubtitle: (ttsMs?: number) => void
    speechStartAt: number
    sentAt: number
  }) => void
  /** lecture_end / pause / resume 같은 lifecycle event. */
  enqueueLifecycle: (apply: () => void | Promise<void>, label: string) => void
  /** 강의 시작 / 종료 boundary 에서 큐 비움. */
  reset: () => void
  /** 진단용 — 현재 audio 큐 길이. */
  getQueueLength: () => number
  /** 진단용 — pending visual 수 (setTimeout 기반이라 항상 0). */
  getPendingVisualCount: () => number
  /** 현재 적용 중인 적응형 딜레이 (ms) — Student.tsx 가 원본 음성 DelayNode 조정에 사용. */
  getCurrentDelay: () => number
}

type PlayFn = (
  text: string,
  lang: AudioLang,
) => Promise<{ audioStartedAt: number; durationMs: number; ended: Promise<void>; ttsMs: number }>

interface Options {
  playSentence: PlayFn
  /** 청크 TTS — 첫 청크 재생 시작 즉시 resolve, 이후 청크는 백그라운드에서 체인. 제공 시 playSentence 대신 사용. */
  playSentenceChunked?: PlayFn
  isAudioUnlocked: () => boolean
  getAudioLang: () => AudioLang
  /** 초기 / 기준 lag (ms). 미설정 시 1000 (= DELAY_MIN_MS). 실제 currentDelay 는 처리시간 따라 가변. */
  delayMs?: number
}

// ── 적응형 딜레이 파라미터 ──────────────────────────────────────────────────────
const PROC_WINDOW_MAX       = 20    // 필요딜레이 슬라이딩 윈도우 크기
const MIN_MARGIN_MS         = 300   // 최소 안전 마진
const MARGIN_STDDEV_MULT    = 1.5   // 마진 = max(MIN_MARGIN, stddev × 이 값) — jitter 크면 자동 ↑
const TTS_SYNTH_INITIAL_MS  = 600   // 청크 TTS 기준 초기 추정 (첫 청크 ≈300ms) — 이후 실측 ttsMs EWMA 로 수렴
const TTS_EWMA_ALPHA        = 0.2   // ttsMs EWMA 갱신 계수
const DELAY_MIN_MS          = 1000  // currentDelay 하한 (스트리밍 모드로 1s까지 수렴 가능)
const DELAY_MAX_MS          = 20000 // currentDelay 상한
const DELAY_DECREASE_EWMA   = 0.25  // 줄일 때 수렴 계수 — silence 구간에서 lag 빨리 회수. 빨리감기는 주로 무음 구간이라 무감
const STALE_EXTRA_MS        = 10000 // STALE 임계 = currentDelay + 이 값 (정상 발화는 절대 drop 안 됨)
const VISUAL_CATCHUP_GAP_MS = 1000  // 시각 event 간격이 이보다 짧으면 같은 stroke 로 보고 강사 간격 보존, 길면 catch-up 허용

export function useDelayBufferPlayer(options: Options): UnitPlayer {
  // 강사 wall → 학생 wall offset 추정 (EWMA). null 이면 첫 event 전.
  const clockOffsetRef = useRef<number | null>(null)
  // Fix 4: 초기 5샘플은 α=0.4 로 빠르게 수렴, 이후 α=0.1 안정 추적
  const clockSampleCountRef = useRef(0)
  const baseDelayMs = options.delayMs ?? 2000

  const optionsRef = useRef(options)
  useEffect(() => { optionsRef.current = options }, [options])

  // 적응형 딜레이 상태
  const currentDelayRef = useRef(baseDelayMs)
  const procWindowRef = useRef<number[]>([])      // 최근 발화들의 "필요딜레이" (ms)
  const ttsLatencyEwmaRef = useRef(TTS_SYNTH_INITIAL_MS)  // 실측 TTS 합성 시간 EWMA — 필요딜레이 산정에 사용
  // monotonic 보장 — 직전 스케줄 시각 (시각 event 와 sentence 는 각자 순서만 유지)
  const lastSentenceWallRef = useRef(0)
  const lastVisualWallRef = useRef(0)
  const lastVisualTsRef = useRef(0)               // 직전 시각 event 의 강사 wall ts — stroke 내부 간격 보존용

  // Audio 직렬 큐 — 영어 TTS 가 한국어보다 길어 schedule 겹치는 케이스 대응.
  const audioQueueRef = useRef<Array<() => Promise<void>>>([])
  const audioPlayingRef = useRef(false)

  const updateClockOffset = useCallback((lecTs: number) => {
    if (typeof lecTs !== 'number' || !isFinite(lecTs)) return
    const observed = Date.now() - lecTs
    if (Math.abs(observed) > 5000) return  // OUTLIER 차단 (네트워크 spike / stale)
    if (clockOffsetRef.current === null) {
      clockOffsetRef.current = observed
    } else {
      const alpha = clockSampleCountRef.current < 5 ? 0.4 : 0.1
      clockOffsetRef.current = clockOffsetRef.current * (1 - alpha) + observed * alpha
    }
    clockSampleCountRef.current++
  }, [])

  /** currentDelay 재계산 — procWindow 기반. recentP90 + jitter 마진.
   *  NaN/Infinity 가드 — 비정상 입력(타임스탬프 오염 등)이 들어와도 currentDelay 가
   *  망가져 DelayNode delayTime 이 NaN → 원본 음성 무음 되는 것 차단. */
  const recomputeDelay = useCallback(() => {
    const w = procWindowRef.current.filter((x) => Number.isFinite(x))
    if (w.length < 3) return  // 데이터 부족 — 초기값 유지
    const sorted = [...w].sort((a, b) => a - b)
    const p90 = sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * 0.9))]
    const mean = w.reduce((a, b) => a + b, 0) / w.length
    const variance = w.reduce((a, b) => a + (b - mean) ** 2, 0) / w.length
    const stddev = Math.sqrt(variance)
    const margin = Math.max(MIN_MARGIN_MS, stddev * MARGIN_STDDEV_MULT)
    let target = p90 + margin
    if (!Number.isFinite(target)) return  // 비정상 — currentDelay 그대로 유지
    target = Math.max(DELAY_MIN_MS, Math.min(DELAY_MAX_MS, target))
    const cur = currentDelayRef.current
    const next = (target >= cur)
      ? target                                       // 늘릴 땐 즉시 (desync 방지)
      : cur + (target - cur) * DELAY_DECREASE_EWMA   // 줄일 땐 천천히
    currentDelayRef.current = Number.isFinite(next)
      ? Math.max(DELAY_MIN_MS, Math.min(DELAY_MAX_MS, next))
      : baseDelayMs                                  // 안전망 — 어떤 이유로든 NaN 이면 기준값
  }, [baseDelayMs])

  const scheduleAt = useCallback((targetWall: number, fn: () => void) => {
    const delay = Math.max(0, targetWall - Date.now())
    setTimeout(() => {
      try { fn() } catch (err) { console.error('[DelayBufferPlayer] apply 오류:', err) }
    }, delay)
  }, [])

  const processAudioQueue = useCallback(async () => {
    if (audioPlayingRef.current) return
    if (audioQueueRef.current.length === 0) return
    audioPlayingRef.current = true
    try {
      const next = audioQueueRef.current.shift()!
      await next()
    } catch (err) {
      console.error('[DelayBufferPlayer] audio queue 오류:', err)
    } finally {
      audioPlayingRef.current = false
      if (audioQueueRef.current.length > 0) {
        Promise.resolve().then(processAudioQueue)
      }
    }
  }, [])

  const enqueueVisual = useCallback((ts: number, apply: () => void, kind?: string) => {
    updateClockOffset(ts)
    const offset = clockOffsetRef.current ?? 0
    const effectiveDelayMs = currentDelayRef.current
    // 같은 stroke 내부(직전 event 와 간격 짧음)면 "강사가 그린 간격" 만큼만 벌려서 재생 —
    //   stroke 사이 긴 gap(VISUAL_CATCHUP_GAP_MS 초과) / 첫 event 에서만 effectiveDelayMs 반영 + monotonic.
    const lastTs = lastVisualTsRef.current
    const gap = lastTs > 0 ? Math.max(0, ts - lastTs) : 0
    const targetWall = (gap > 0 && gap < VISUAL_CATCHUP_GAP_MS)
      ? lastVisualWallRef.current + gap
      : Math.max(ts + offset + effectiveDelayMs, lastVisualWallRef.current)
    lastVisualWallRef.current = targetWall
    lastVisualTsRef.current = ts
    scheduleAt(targetWall, apply)
    if (kind && kind !== 'cursor' && kind !== 'draw_point') {
      const ahead = targetWall - Date.now()
      console.log(`[DelayBuf] visual ${kind} ts=${ts} → +${Math.round(ahead)}ms (delay=${Math.round(effectiveDelayMs)}ms)`)
    }
  }, [updateClockOffset, scheduleAt])

  const enqueueSentence = useCallback((params: {
    text: string
    commitSubtitle: (ttsMs?: number) => void
    speechStartAt: number
    sentAt: number
  }) => {
    // 주의: clockOffset 은 sentence timestamp 로 갱신하지 않음 — speechStartAt 은 lecturer wall
    //   of the speech (broadcast 시점 X). pause 후 옛 audio frame 의 transcribe 가 늦게 오면
    //   offset 오염. visual event (lecturerTimestamp = broadcast 시점) 만 갱신에 사용.
    const offset = clockOffsetRef.current ?? 0
    const speechWall = params.speechStartAt + offset
    const now = Date.now()

    // 필요딜레이 측정 — "강사 발화 시작 후 학생측 TTS 재생 준비될 때까지" 추정.
    //   (지금 도착 시각 = ASR + NMT + 네트워크 완료) - 발화시작wall + 실측 TTS 합성 EWMA.
    //   finite 한 값만 윈도우에 넣음 (타임스탬프 오염 방어).
    const neededDelay = (now - speechWall) + ttsLatencyEwmaRef.current
    if (Number.isFinite(neededDelay)) {
      procWindowRef.current.push(Math.max(0, neededDelay))
      if (procWindowRef.current.length > PROC_WINDOW_MAX) procWindowRef.current.shift()
      recomputeDelay()
    }

    const targetWall = Math.max(speechWall + currentDelayRef.current, lastSentenceWallRef.current)
    const ahead = targetWall - now

    // STALE drop — currentDelay + STALE_EXTRA 보다 늦으면 진짜 stale (pause 후 옛 frame).
    //   정상 발화 (force-split 8s + ASR/NMT 처리 ~5s) 는 이 임계 한참 안쪽이라 절대 안 버려짐.
    const staleThreshold = currentDelayRef.current + STALE_EXTRA_MS
    if (ahead < -staleThreshold) {
      console.warn(`[DelayBuf] STALE drop (${Math.round(-ahead)}ms late): "${params.text.slice(0, 40)}..."`)
      return
    }
    lastSentenceWallRef.current = targetWall

    console.log(
      `[DelayBuf] sentence "${params.text.slice(0, 30)}..." ` +
      `delay=${Math.round(currentDelayRef.current)}ms scheduled=+${Math.round(ahead)}ms`,
    )

    // 자막 commit 타이밍 — 'en' 모드는 TTS audioStartedAt 시점, 그 외는 schedule 시점 즉시.
    // audioLang !== 'en' 이면 TTS 합성/재생 자체를 스킵 — 이전엔 합성은 진행하고 GainNode mute
    // 로만 차단했으나, unlock race / suspended ctx ramp 등으로 첫 발화가 새는 경로가 남아 있어
    // 결정적 차단으로 전환 (gain 0 보장은 방어 2 차).
    scheduleAt(targetWall, () => {
      const opts = optionsRef.current
      if (!opts.isAudioUnlocked()) {
        try { params.commitSubtitle() } catch (err) { console.error('[DelayBufferPlayer] commitSubtitle 오류:', err) }
        return
      }
      const langAtSchedule = opts.getAudioLang()
      if (langAtSchedule !== 'en') {
        try { params.commitSubtitle() } catch (err) { console.error('[DelayBufferPlayer] commitSubtitle 오류:', err) }
        return
      }
      audioQueueRef.current.push(async () => {
        try {
          if (optionsRef.current.getAudioLang() !== 'en') {
            try { params.commitSubtitle() } catch (e) { console.error('[DelayBufferPlayer] commitSubtitle 오류:', e) }
            return
          }
          const playFn = opts.playSentenceChunked ?? opts.playSentence
          const result = await playFn(params.text, 'en')
          if (optionsRef.current.getAudioLang() !== 'en') {
            try { params.commitSubtitle() } catch (e) { console.error('[DelayBufferPlayer] commitSubtitle 오류:', e) }
            return
          }
          // 실측 TTS 합성 시간으로 EWMA 갱신 — 다음 발화들의 필요딜레이 추정이 더 타이트해짐.
          if (Number.isFinite(result.ttsMs) && result.ttsMs >= 0) {
            ttsLatencyEwmaRef.current = ttsLatencyEwmaRef.current * (1 - TTS_EWMA_ALPHA) + result.ttsMs * TTS_EWMA_ALPHA
          }
          const subtitleDelay = Math.max(0, result.audioStartedAt - Date.now())
          setTimeout(() => {
            try { params.commitSubtitle(result.ttsMs) } catch (err) { console.error('[DelayBufferPlayer] commitSubtitle 오류:', err) }
          }, subtitleDelay)
          await result.ended
        } catch (err) {
          console.error('[DelayBufferPlayer] playSentence 실패:', err)
          try { params.commitSubtitle() } catch (e) { console.error('[DelayBufferPlayer] commitSubtitle 오류:', e) }
        }
      })
      processAudioQueue()
    })
  }, [scheduleAt, processAudioQueue, recomputeDelay])

  const enqueueLifecycle = useCallback((apply: () => void | Promise<void>, label: string) => {
    // lifecycle 은 wall ts 가 명시되지 않는 경우가 있음 → 도착 시점 + effectiveDelayMs.
    // monotonic 은 시각 event 기준 (pause/resume/end 가 그림·페이지와 같은 시간선에 적용돼야 함).
    const effectiveDelayMs = currentDelayRef.current
    const targetWall = Math.max(Date.now() + effectiveDelayMs, lastVisualWallRef.current)
    lastVisualWallRef.current = targetWall
    console.log(`[DelayBuf] lifecycle ${label} → +${Math.round(targetWall - Date.now())}ms (delay=${Math.round(effectiveDelayMs)}ms)`)
    scheduleAt(targetWall, apply)
  }, [scheduleAt])

  const reset = useCallback(() => {
    audioQueueRef.current = []
    currentDelayRef.current = baseDelayMs
    procWindowRef.current = []
    ttsLatencyEwmaRef.current = TTS_SYNTH_INITIAL_MS
    lastSentenceWallRef.current = 0
    lastVisualWallRef.current = 0
    lastVisualTsRef.current = 0
    clockOffsetRef.current = null
    clockSampleCountRef.current = 0
    // setTimeout 들은 cancel 하지 않음 — 이미 등록된 visual/audio 는 자기 시간에 fire,
    // 강의 boundary 에서 frontend store 가 isLectureStarted 가드로 무시.
    console.log(`[DelayBufferPlayer] reset (delay → ${baseDelayMs}ms)`)
  }, [baseDelayMs])

  const getQueueLength = useCallback(() => audioQueueRef.current.length, [])
  const getPendingVisualCount = useCallback(() => 0, [])
  // finite 보장 — 어떤 이유로든 currentDelay 가 NaN 이어도 기준값 반환 (DelayNode 무음 방지).
  const getCurrentDelay = useCallback(
    () => (Number.isFinite(currentDelayRef.current) ? currentDelayRef.current : baseDelayMs),
    [baseDelayMs],
  )

  return {
    enqueueVisual,
    enqueueSentence,
    enqueueLifecycle,
    reset,
    getQueueLength,
    getPendingVisualCount,
    getCurrentDelay,
  }
}
