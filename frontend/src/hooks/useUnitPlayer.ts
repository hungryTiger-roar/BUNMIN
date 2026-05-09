/**
 * useUnitPlayer — Queue + visual stretch (Option F).
 *
 * 모델 — 음성은 1배속 자연 그대로, 그림/커서를 음성 길이에 맞춰 늘려 sync 보장.
 *
 *   영어 TTS audio 가 한국어 발화보다 평균 1.2~1.5배 길다는 사실에서 출발.
 *   option-c 와 달리 audio 를 압축하지 않음 — 학생이 듣는 영어는 처음부터 끝까지
 *   1배속 (자연 합성 결과 그대로). 대신 그림/커서 visual events 를 그 sentence 의
 *   audio 길이에 맞춰 stretch.
 *
 *   비유: "더빙된 영화" — 화면 속 동작이 영어 발음 길이에 맞춰 진행. 영어는 자연,
 *         화면은 약간 늘어진 느낌. 시간이 흘러도 한 sentence 의 visual + audio 는
 *         항상 한 쌍으로 흘러감.
 *
 *   한 unit 안:
 *     - TTS audio (그 sentence 의 영어 음성, 1배속)
 *     - 그 sentence 발화 동안 강사가 한 visual events
 *     - lecturer span [speechStartAt, sentAt] → audio span [audioStart, audioStart+audioDuration]
 *       으로 시간 비례 stretch
 *
 *   재생:
 *     - audio 시작 시점에 visual events 를 audio span 에 비례 schedule (visual stretch)
 *     - audio 끝 (ended Promise) → 다음 unit 시작
 *
 * 결과:
 *   - 음성 끊김 없이 sentence 단위로 깔끔하게 이어짐 (option-c 동일)
 *   - 영어 음성 100% 자연 1배속 (option-c 와 차별화 — option-c 는 visual 이 Korean span
 *     에 끝나고 audio 만 남는 mismatch)
 *   - 그림/커서가 그 영어 설명과 정확히 같은 시간에 흘러감 (per-sentence sync)
 *   - 시간이 흘러도 학생이 듣는 영어 품질 일관 — 빠르기 변화 없음
 *
 * Trade-off:
 *   강사가 1초에 한 그림을 학생은 1.3초에 봄 (영어가 1.3배라면). visual 박자가
 *   살짝 느려짐. 하지만 영어 음성과 정확히 paired 되어 자연스러움.
 *   강사-학생 누적 lag 은 시간 흐를수록 증가하지만 visual+audio 가 함께 늦으므로
 *   "라이브 방송 시청" 처럼 자연스럽게 느껴짐.
 *
 * pendingVisualRef: 아직 sentence 와 결합되지 않은 visual events 임시 보관.
 *   transcription 도착 시 그 sentence 의 sentAt 까지의 events 를 unit 으로 묶음.
 *   lifecycle event 도착 시 잔여 events 를 visual_batch unit 으로 flush.
 */
import { useCallback, useEffect, useRef } from 'react'
import type { TranslationLang } from '@/stores/preferencesStore'

interface PendingVisual {
  ts: number              // lecturerTimestamp
  apply: () => void
  kind?: string
}

type Unit =
  | {
      kind: 'sentence'
      text: string
      subtitleId: string
      speechStartAt: number  // lecturer 시계 발화 시작
      sentAt: number         // lecturer 시계 발화 끝
      visuals: PendingVisual[]
    }
  | { kind: 'visual_batch'; visuals: PendingVisual[]; label?: string }
  | { kind: 'lifecycle'; apply: () => void; label: string }

export interface UnitPlayer {
  /** visual event 등록 — 다음 sentence 의 unit 으로 묶임. */
  enqueueVisual: (ts: number, apply: () => void, kind?: string) => void
  /** transcription 도착 시 호출 — pending visual 중 sentAt 까지의 events 를 묶어
   *  sentence unit 으로 큐에 push. */
  enqueueSentence: (params: {
    text: string
    subtitleId: string
    speechStartAt: number
    sentAt: number
  }) => void
  /** lecture_end / pause / resume 같은 lifecycle event — 잔여 visual 먼저 flush
   *  후 lifecycle unit push. */
  enqueueLifecycle: (apply: () => void, label: string) => void
  /** 강의 시작 / 종료 boundary 에서 큐와 pending 모두 비움. */
  reset: () => void
  /** 진단용 — 현재 큐 길이. */
  getQueueLength: () => number
  /** 진단용 — pending visual 수. */
  getPendingVisualCount: () => number
}

interface Options {
  /** sentence audio 합성 + 재생. resolve 시 audio 시작 정보 반환. */
  playSentence: (
    text: string,
    lang: TranslationLang,
    subtitleId?: string,
  ) => Promise<{ audioStartedAt: number; durationMs: number; ended: Promise<void> }>
  /** TTS audio 가 사용 가능한지 (unlock 됐는지). false 면 audio skip + visual 만. */
  isAudioUnlocked: () => boolean
  /** 현재 audioLang (TTS 음성 합성 언어). */
  getAudioLang: () => TranslationLang
}

/** Silent watchdog — sentence 없이 시각만 들어올 때 일정 시간 후 flush.
 *  발화 없이 그리기/커서만 움직이는 상황에서 visual 이 pending 에만 갇히지 않도록.
 *  마지막 visual 이 들어온 후 이 시간 동안 새 visual / sentence 안 오면 flush. */
const SILENT_FLUSH_AFTER_MS = 700
/** Watchdog tick 주기. */
const WATCHDOG_TICK_MS = 500

export function useUnitPlayer(options: Options): UnitPlayer {
  const queueRef = useRef<Unit[]>([])
  const pendingVisualRef = useRef<PendingVisual[]>([])
  const isPlayingRef = useRef(false)
  /** 마지막 visual 이 pending 에 들어온 wall time. silent watchdog 안정 판단용. */
  const lastVisualAddedAtRef = useRef<number>(0)

  const optionsRef = useRef(options)
  useEffect(() => { optionsRef.current = options }, [options])

  /** 큐 한 step 진행 — 재진입 방지 + 재귀로 다음 unit. */
  const processNext = useCallback(async () => {
    if (isPlayingRef.current) return
    if (queueRef.current.length === 0) return
    isPlayingRef.current = true

    const unit = queueRef.current.shift()!
    try {
      if (unit.kind === 'sentence') {
        await playSentenceUnit(unit)
      } else if (unit.kind === 'visual_batch') {
        // 잔여 visual 적용 — audio 없으니 lecturer 시간 간격 그대로 보존해 motion 살림.
        if (unit.visuals.length > 0) {
          const firstTs = unit.visuals[0].ts
          const lastTs = unit.visuals[unit.visuals.length - 1].ts
          const span = Math.max(1, lastTs - firstTs)
          scheduleVisuals(unit.visuals, firstTs, span, Date.now(), span)
          await new Promise<void>((resolve) => setTimeout(resolve, span + 50))
        }
      } else if (unit.kind === 'lifecycle') {
        try {
          unit.apply()
          console.log(`[UnitPlayer] lifecycle 적용: ${unit.label}`)
        } catch (err) {
          console.error('[UnitPlayer] lifecycle apply 오류:', err)
        }
      }
    } catch (err) {
      console.error('[UnitPlayer] unit 처리 오류:', err)
    }

    isPlayingRef.current = false
    if (queueRef.current.length > 0) {
      Promise.resolve().then(processNext)
    }
  }, [])

  /** sentence unit 재생 — Option F: visuals 를 audio 실제 길이에 맞춰 stretch.
   *  영어 audio 는 합성 결과 그대로 1배속, visual 만 audio span 에 늘어남.
   *  발화 전 visual (ts < speechStartAt) 은 별도로 강사 박자 그대로 먼저 replay
   *  (audio 시작 전) — burst 방지 + 강사가 침묵 중에 그린 그림 자연스럽게 보임. */
  const playSentenceUnit = async (unit: Extract<Unit, { kind: 'sentence' }>) => {
    const opts = optionsRef.current
    const audioOk = opts.isAudioUnlocked()
    const lang = opts.getAudioLang()
    const lecturerSpan = Math.max(1, unit.sentAt - unit.speechStartAt)
    const unitStartWall = Date.now()

    // 발화 전 visual 과 발화 중 visual 분리.
    //   pre-speech (ts < speechStartAt): 강사가 발화 시작 전에 그린/움직인 것 →
    //     강사 박자 그대로 먼저 replay (mirror).
    //   during-speech (ts >= speechStartAt): 발화 중 그림/커서 → audio 길이에 stretch.
    const preSpeech: PendingVisual[] = []
    const duringSpeech: PendingVisual[] = []
    for (const v of unit.visuals) {
      if (v.ts < unit.speechStartAt) preSpeech.push(v)
      else duringSpeech.push(v)
    }

    // [DIAGNOSTIC] sentence unit 시작 — speechStartAt / sentAt / 분리 통계.
    console.log(
      `[Diag] unit START text="${unit.text.slice(0, 30)}..." ` +
      `lecturerSpan=${Math.round(lecturerSpan)}ms ` +
      `pre=${preSpeech.length} during=${duringSpeech.length} ` +
      `text_len=${unit.text.length} audioReady=${audioOk}`,
    )

    // 1) pre-speech replay — 강사 박자 그대로. 시작은 now, 마지막 event 까지 preSpan
    //    걸려서 발사. await 으로 끝까지 기다린 후 audio 시작.
    if (preSpeech.length > 0) {
      preSpeech.sort((a, b) => a.ts - b.ts)
      const earliestTs = preSpeech[0].ts
      const latestTs = preSpeech[preSpeech.length - 1].ts
      const preSpan = Math.max(1, latestTs - earliestTs)
      console.log(
        `[UnitPlayer] pre-speech replay (${preSpeech.length}건, span ${Math.round(preSpan)}ms)`,
      )
      // 1:1 매핑 — earliestTs 가 now 에 fire, latestTs 가 now+preSpan 에 fire.
      scheduleVisuals(preSpeech, earliestTs, preSpan, Date.now(), preSpan)
      await new Promise((resolve) => setTimeout(resolve, preSpan + 50))
    }

    if (lang === 'off' || !audioOk) {
      // audio 미사용 — during-speech visual 은 lecturerSpan 그대로 (stretch 기준 audio 가 없음).
      scheduleVisuals(duringSpeech, unit.speechStartAt, lecturerSpan, Date.now(), lecturerSpan)
      await new Promise((resolve) => setTimeout(resolve, lecturerSpan))
      return
    }

    let result: { audioStartedAt: number; durationMs: number; ended: Promise<void> }
    try {
      result = await opts.playSentence(unit.text, lang, unit.subtitleId)
    } catch (err) {
      console.error('[UnitPlayer] playSentence 실패 — visual 만 적용:', err)
      for (const v of duringSpeech) {
        try { v.apply() } catch (e) { console.error(e) }
      }
      return
    }

    // 2) during-speech visual stretch — audio 실제 길이에 맞춰 늘어남.
    //    한국어 lecturerSpan 1초 + 영어 audio 1.5초면 visual 이 1.5초에 걸쳐 0.67배속.
    const stretchRatio = result.durationMs / lecturerSpan
    console.log(
      `[Diag] AUDIO ready: audioDuration=${Math.round(result.durationMs)}ms ` +
      `stretchRatio=${stretchRatio.toFixed(2)}x ` +
      `audioStartsIn=${Math.round(result.audioStartedAt - Date.now())}ms`,
    )
    scheduleVisuals(duringSpeech, unit.speechStartAt, lecturerSpan, result.audioStartedAt, result.durationMs)

    // unit 길이 = audio.ended 시점. visual 도 audio span 안에 들어감.
    await result.ended
    console.log(
      `[Diag] unit END total=${Date.now() - unitStartWall}ms text="${unit.text.slice(0, 30)}..."`,
    )
  }

  /** visual events 를 lecturer 시간 비례로 학생 wall time 에 schedule.
   *  연속 event 간 최소 16ms (60fps) 간격 보장 — burst 방지. */
  const MIN_EVENT_GAP_MS = 16
  const scheduleVisuals = (
    visuals: PendingVisual[],
    speechStartAt: number,
    lecturerSpan: number,
    audioStartWall: number,
    audioDurationMs: number,
  ) => {
    const sorted = [...visuals].sort((a, b) => a.ts - b.ts)
    let minTargetWall = 0
    for (const v of sorted) {
      const ratio = Math.max(0, Math.min(1, (v.ts - speechStartAt) / lecturerSpan))
      let targetWall = audioStartWall + ratio * audioDurationMs
      if (targetWall < minTargetWall) targetWall = minTargetWall
      minTargetWall = targetWall + MIN_EVENT_GAP_MS
      const delay = Math.max(0, targetWall - Date.now())
      setTimeout(() => {
        try { v.apply() } catch (err) { console.error('[UnitPlayer] visual apply 오류:', err) }
      }, delay)
    }
  }

  const enqueueVisual = useCallback((ts: number, apply: () => void, kind?: string) => {
    pendingVisualRef.current.push({ ts, apply, kind })
    lastVisualAddedAtRef.current = Date.now()
    if (kind && kind !== 'cursor' && kind !== 'draw_point') {
      console.log(
        `[UnitPlayer] visual buffer ${kind} ts=${ts} (pending=${pendingVisualRef.current.length})`,
      )
    }
  }, [])

  const enqueueSentence = useCallback((params: {
    text: string
    subtitleId: string
    speechStartAt: number
    sentAt: number
  }) => {
    // pending visual 중 sentAt 까지의 events 를 unit 으로 묶음.
    const matched: PendingVisual[] = []
    const remaining: PendingVisual[] = []
    for (const v of pendingVisualRef.current) {
      if (v.ts <= params.sentAt) matched.push(v)
      else remaining.push(v)
    }
    matched.sort((a, b) => a.ts - b.ts)
    pendingVisualRef.current = remaining

    queueRef.current.push({
      kind: 'sentence',
      text: params.text,
      subtitleId: params.subtitleId,
      speechStartAt: params.speechStartAt,
      sentAt: params.sentAt,
      visuals: matched,
    })
    // [Diag] transcription 도착 시 — 어떤 visual 이 이 sentence 에 묶였는지.
    console.log(
      `[Diag] enqueueSentence text="${params.text.slice(0, 30)}..." ` +
      `lecturerSpan=${params.sentAt - params.speechStartAt}ms ` +
      `matchedVisuals=${matched.length} remainingPending=${remaining.length} queueDepth=${queueRef.current.length}`,
    )
    processNext()
  }, [processNext])

  const enqueueLifecycle = useCallback((apply: () => void, label: string) => {
    // 잔여 pending visual 먼저 flush — lifecycle 전 자연 마무리.
    if (pendingVisualRef.current.length > 0) {
      const flushed = pendingVisualRef.current
      pendingVisualRef.current = []
      flushed.sort((a, b) => a.ts - b.ts)
      queueRef.current.push({ kind: 'visual_batch', visuals: flushed, label: `${label} 직전 visual flush` })
    }
    queueRef.current.push({ kind: 'lifecycle', apply, label })
    console.log(`[UnitPlayer] lifecycle 큐: ${label}`)
    processNext()
  }, [processNext])

  const reset = useCallback(() => {
    queueRef.current = []
    pendingVisualRef.current = []
    console.log('[UnitPlayer] reset — 큐 + pending 모두 비움')
  }, [])

  const getQueueLength = useCallback(() => queueRef.current.length, [])
  const getPendingVisualCount = useCallback(() => pendingVisualRef.current.length, [])

  // Silent watchdog — 발화 없이 시각만 들어오는 경우 (강사가 그림만 그림 / 커서만
  // 움직임) sentence 가 안 와서 pending 에 visual 이 갇히는 걸 방지.
  useEffect(() => {
    const id = setInterval(() => {
      const pending = pendingVisualRef.current
      if (pending.length === 0) return
      if (queueRef.current.length > 0) return
      if (isPlayingRef.current) return
      const idleMs = Date.now() - lastVisualAddedAtRef.current
      if (idleMs < SILENT_FLUSH_AFTER_MS) return

      const flushed = pending.slice()
      pendingVisualRef.current = []
      flushed.sort((a, b) => a.ts - b.ts)
      queueRef.current.push({
        kind: 'visual_batch',
        visuals: flushed,
        label: 'silent flush',
      })
      console.log(
        `[UnitPlayer] silent flush — ${flushed.length}건 visual_batch 로 큐 (idle=${idleMs}ms)`,
      )
      processNext()
    }, WATCHDOG_TICK_MS)
    return () => clearInterval(id)
  }, [processNext])

  return { enqueueVisual, enqueueSentence, enqueueLifecycle, reset, getQueueLength, getPendingVisualCount }
}
