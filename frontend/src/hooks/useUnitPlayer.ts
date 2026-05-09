/**
 * useUnitPlayer — Queue + TTS-end 기반 sequential 재생 (Option C).
 *
 * 모델:
 *   강사가 한 모든 행동 (그림 / 커서 / 페이지 / 음성) 을 sentence 단위 unit 으로
 *   묶어 학생 PC 큐에 적재. 학생은 큐에서 한 unit 씩 꺼내 재생. 한 unit 의 TTS
 *   audio 가 끝나야 다음 unit 시작.
 *
 *   한 unit 안:
 *     - TTS audio (그 sentence 의 영어 음성)
 *     - 그 sentence 발화 동안 강사가 한 visual events (drawings/cursor/page change)
 *     - lecturer 시간선상 [speechStartAt, sentAt] 에 매핑되는 events
 *
 *   재생:
 *     - audio 시작 시점에 visual events 를 lecturer 시간 비례로 schedule
 *     - audio 끝 (ended Promise) → 다음 unit 시작
 *
 * 결과:
 *   - 음성 끊김 없이 sentence 단위로 깔끔하게 이어짐
 *   - 페이지 정합성 자연 보장 (한 sentence 의 visual 이 그 sentence audio 안에서 재생)
 *   - 강사 침묵 시간은 사라짐 (TTS-end 즉시 다음 unit), silent 그림은 watchdog 700ms 후
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

  /** sentence unit 재생 — visuals 는 lecturerSpan 1:1 매핑 (압축 X) → 강사 박자 보존. */
  const playSentenceUnit = async (unit: Extract<Unit, { kind: 'sentence' }>) => {
    const opts = optionsRef.current
    const audioOk = opts.isAudioUnlocked()
    const lang = opts.getAudioLang()
    const lecturerSpan = Math.max(1, unit.sentAt - unit.speechStartAt)

    if (lang === 'off' || !audioOk) {
      scheduleVisuals(unit.visuals, unit.speechStartAt, lecturerSpan, Date.now(), lecturerSpan)
      await new Promise((resolve) => setTimeout(resolve, lecturerSpan))
      return
    }

    let result: { audioStartedAt: number; durationMs: number; ended: Promise<void> }
    try {
      result = await opts.playSentence(unit.text, lang, unit.subtitleId)
    } catch (err) {
      console.error('[UnitPlayer] playSentence 실패 — visual 만 적용:', err)
      for (const v of unit.visuals) {
        try { v.apply() } catch (e) { console.error(e) }
      }
      return
    }

    // visuals 는 lecturerSpan 1:1 매핑 (audioDuration = lecturerSpan 으로 두면 압축 없음).
    scheduleVisuals(unit.visuals, unit.speechStartAt, lecturerSpan, result.audioStartedAt, lecturerSpan)

    // unit 길이 = max(audio, visual). 둘 중 늦게 끝나는 쪽까지 대기 후 다음 unit.
    const visualEndPromise = new Promise<void>((resolve) => {
      const remainingMs = Math.max(0, result.audioStartedAt + lecturerSpan + 50 - Date.now())
      setTimeout(resolve, remainingMs)
    })
    await Promise.all([result.ended, visualEndPromise])
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
    console.log(
      `[UnitPlayer] sentence unit 큐 (visual=${matched.length}, queue depth=${queueRef.current.length})`,
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
