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
      /** 자막 표시 콜백 — TTS audio 가 실제 시작되는 시점에 player 가 호출.
       *  ttsMs 가 있으면 subtitle 의 단계별 latency 표시에 사용. 호출 시 store 에
       *  subtitle 이 추가되며, 그 전까지는 자막이 화면에 안 보임 → audio 와 자막 동시 등장. */
      commitSubtitle: (ttsMs?: number) => void
      speechStartAt: number  // lecturer 시계 발화 시작
      sentAt: number         // lecturer 시계 발화 끝
      visuals: PendingVisual[]
    }
  | { kind: 'visual_batch'; visuals: PendingVisual[]; label?: string }
  | { kind: 'lifecycle'; apply: () => void | Promise<void>; label: string }

export interface UnitPlayer {
  /** visual event 등록 — 다음 sentence 의 unit 으로 묶임. */
  enqueueVisual: (ts: number, apply: () => void, kind?: string) => void
  /** transcription 도착 시 호출 — pending visual 중 sentAt 까지의 events 를 묶어
   *  sentence unit 으로 큐에 push. commitSubtitle 은 TTS 시작 시점에 호출돼
   *  자막이 화면에 표시됨 (자막↔TTS 동기화). */
  enqueueSentence: (params: {
    text: string
    commitSubtitle: (ttsMs?: number) => void
    speechStartAt: number
    sentAt: number
  }) => void
  /** lecture_end / pause / resume 같은 lifecycle event — 잔여 visual 먼저 flush
   *  후 lifecycle unit push.
   *  apply 가 Promise 를 반환하면 await — pause 시간 동등 반영용 sleep 등에 사용. */
  enqueueLifecycle: (apply: () => void | Promise<void>, label: string) => void
  /** 강사가 발화 시작 — silent watchdog 가 발화 진행 중임을 알도록.
   *  발화 중에는 절대 silent flush 하지 않음 (그림 → 음성 분리 방지). */
  markSpeechActive: () => void
  /** 강사가 발화 끝 — ASR 결과 도착 대기 모드로 전환.
   *  transcription 이 올 때까지 watchdog 가 더 길게 (POST_SPEECH_ASR_TIMEOUT_MS) 기다림. */
  markSpeechEnded: () => void
  /** 강의 시작 / 종료 boundary 에서 큐와 pending 모두 비움. */
  reset: () => void
  /** 진단용 — 현재 큐 길이. */
  getQueueLength: () => number
  /** 진단용 — pending visual 수. */
  getPendingVisualCount: () => number
}

interface Options {
  /** sentence audio 합성 + 재생. resolve 시 audio 시작 정보 반환.
   *  ttsMs 는 자막 표시 시 단계별 latency 표시에 사용. */
  playSentence: (
    text: string,
    lang: TranslationLang,
    subtitleId?: string,
  ) => Promise<{ audioStartedAt: number; durationMs: number; ended: Promise<void>; ttsMs: number }>
  /** TTS audio 가 사용 가능한지 (unlock 됐는지). false 면 audio skip + visual 만. */
  isAudioUnlocked: () => boolean
  /** 현재 audioLang (TTS 음성 합성 언어). */
  getAudioLang: () => TranslationLang
}

/** Silent watchdog — sentence 없이 시각만 들어올 때 일정 시간 후 flush.
 *  발화 없이 그리기/커서만 움직이는 상황에서 visual 이 pending 에만 갇히지 않도록.
 *  마지막 visual 이 들어온 후 이 시간 동안 새 visual / sentence 안 오면 flush.
 *
 *  Branch B (speech_end signal):
 *    - 발화 중 (markSpeechActive ~ markSpeechEnded 사이) 에는 절대 flush 안 함.
 *    - 발화 끝난 후엔 transcription 도착까지 POST_SPEECH_ASR_TIMEOUT_MS 까지 기다림
 *      (ASR 가 5~15s 걸려도 sentence 와 visual 이 함께 묶임 → "그림 먼저 음성 나중" 차단).
 *    - 처음부터 무발화 (강사가 그리기만) 인 경우엔 SILENT_FLUSH_AFTER_MS 만에 flush —
 *      sentence 가 영영 안 오는 케이스에 visual 이 영구히 갇히지 않도록.
 *
 *  단, 페이지 전환 (page_change / slide_select / presentation_mode) 은 제외 —
 *  이런 boundary 이벤트가 단독으로 학생 화면에 적용되면 TTS·자막 없이 페이지만
 *  바뀌는 어색한 구간이 생김. 반드시 다음 sentence 와 묶여야 자연스러우므로
 *  silent flush / asr-timeout flush 모두에서 holding (다음 transcription 이 올 때
 *  비로소 unit 으로 묶여 적용). 그림은 페이지별 buffer 에 알아서 안착하므로
 *  flush 돼도 무해. */
const SILENT_FLUSH_AFTER_MS = 5000
/** 발화 종료 후 ASR transcription 도착까지 기다리는 최대 시간.
 *  이 시간 안에 transcription 이 오면 그 sentence 와 함께 묶임. 안 오면 visual_batch 로 flush. */
const POST_SPEECH_ASR_TIMEOUT_MS = 30000
/** Watchdog tick 주기. */
const WATCHDOG_TICK_MS = 500
/** Silent / lifecycle flush 에서 제외할 page boundary 이벤트 종류.
 *  단독 적용 시 학생 화면에 "TTS 없이 페이지만 휙" 어색함 발생 → 반드시 다음
 *  sentence 와 묶여야 함. */
const PAGE_BOUNDARY_KINDS = new Set(['page_change', 'slide_select', 'presentation_mode'])
/** lifecycle (lecture_end / pause / resume) 처리 정책 — 적응적 대기.
 *  강사가 종료/일시정지를 누른 직후 마지막 발화의 ASR/MT 결과가 아직 도착 안
 *  했을 가능성. 고정 시간 대기 대신 speech_active / speech_end / lastTranscription
 *  신호로 ASR pipeline 처리 상태를 판단:
 *    - 발화 중 또는 ASR 대기 중 → POLL 간격으로 재시도.
 *    - 처리 완료 → 즉시 lifecycle 을 큐에 push (큐의 잔여 sentence 다 끝난 후 적용).
 *  MAX_WAIT 는 ASR 가 진짜 멈춘 케이스의 안전망 — 그 시간 지나면 강제 적용. */
const LIFECYCLE_MAX_WAIT_MS = 30000
const LIFECYCLE_POLL_MS = 200
/** speech_end 직후 grace — 곧바로 다음 utterance 가 올 가능성 검사 윈도우.
 *  강사가 호흡 직후 일시정지 누른 케이스에서, in-flight chunk 의 speech_start 가
 *  곧 도착할 수 있어 잠깐 더 기다려 봄. */
const LIFECYCLE_SPEECH_END_GRACE_MS = 500

export function useUnitPlayer(options: Options): UnitPlayer {
  const queueRef = useRef<Unit[]>([])
  const pendingVisualRef = useRef<PendingVisual[]>([])
  const isPlayingRef = useRef(false)
  /** 마지막 visual 이 pending 에 들어온 wall time. silent watchdog 안정 판단용. */
  const lastVisualAddedAtRef = useRef<number>(0)
  /** 강사 발화 진행 중 여부 — backend speech_start / speech_end 신호로 토글.
   *  true 인 동안 silent watchdog 는 절대 flush 하지 않음. */
  const speechActiveRef = useRef<boolean>(false)
  /** 마지막 speech_end 도착 시각. transcription 도착 대기 판단에 사용. */
  const lastSpeechEndAtRef = useRef<number>(0)
  /** 마지막 transcription 이 enqueueSentence 로 들어온 시각.
   *  speech_end 이후 transcription 이 도착하면 watchdog 다시 짧은 모드로. */
  const lastTranscriptionAtRef = useRef<number>(0)
  /** lifecycle drain timer 들 — reset 시 모두 cancel 해야 새 강의에 leftover 영향 없음. */
  const lifecycleTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set())

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
          // apply 가 Promise 반환하면 await — resume 의 pause 시간 동등 sleep 등에서 큐 정지.
          await unit.apply()
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
      // 자막은 visual 시작 시점과 같이 표시 (audio 가 없으니 visual 이 anchor).
      try { unit.commitSubtitle() } catch (e) { console.error('[UnitPlayer] commitSubtitle 오류:', e) }
      scheduleVisuals(duringSpeech, unit.speechStartAt, lecturerSpan, Date.now(), lecturerSpan)
      await new Promise((resolve) => setTimeout(resolve, lecturerSpan))
      return
    }

    let result: { audioStartedAt: number; durationMs: number; ended: Promise<void>; ttsMs: number }
    try {
      result = await opts.playSentence(unit.text, lang)
    } catch (err) {
      console.error('[UnitPlayer] playSentence 실패 — visual 만 적용:', err)
      // 합성 실패해도 자막은 보여줘야 — visual 과 함께 즉시 표시.
      try { unit.commitSubtitle() } catch (e) { console.error('[UnitPlayer] commitSubtitle 오류:', e) }
      for (const v of duringSpeech) {
        try { v.apply() } catch (e) { console.error(e) }
      }
      return
    }

    // 2) 자막을 audio 실제 시작 시점에 맞춰 표시 — 이전엔 transcription 도착 즉시
    //    addSubtitle 했지만 큐 대기 + TTS 합성으로 audio 와 수 초 차이 났음. 이제
    //    audioStartedAt (≈ now + 50ms) 에 setTimeout 으로 commitSubtitle → 자막↔TTS 동시.
    const subtitleDelay = Math.max(0, result.audioStartedAt - Date.now())
    setTimeout(() => {
      try { unit.commitSubtitle(result.ttsMs) } catch (e) { console.error('[UnitPlayer] commitSubtitle 오류:', e) }
    }, subtitleDelay)

    // 3) during-speech visual stretch — audio 실제 길이에 맞춰 늘어남.
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
    commitSubtitle: (ttsMs?: number) => void
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
      commitSubtitle: params.commitSubtitle,
      speechStartAt: params.speechStartAt,
      sentAt: params.sentAt,
      visuals: matched,
    })
    // transcription 도착 시각 기록 — watchdog 가 ASR 대기 모드에서 정상 모드로 돌아감.
    lastTranscriptionAtRef.current = Date.now()
    // [Diag] transcription 도착 시 — 어떤 visual 이 이 sentence 에 묶였는지.
    console.log(
      `[Diag] enqueueSentence text="${params.text.slice(0, 30)}..." ` +
      `lecturerSpan=${params.sentAt - params.speechStartAt}ms ` +
      `matchedVisuals=${matched.length} remainingPending=${remaining.length} queueDepth=${queueRef.current.length}`,
    )
    processNext()
  }, [processNext])

  const markSpeechActive = useCallback(() => {
    speechActiveRef.current = true
    console.log('[UnitPlayer] speech_start — silent watchdog 정지')
  }, [])

  const markSpeechEnded = useCallback(() => {
    speechActiveRef.current = false
    lastSpeechEndAtRef.current = Date.now()
    console.log('[UnitPlayer] speech_end — ASR transcription 대기 모드')
  }, [])

  const enqueueLifecycle = useCallback((apply: () => void | Promise<void>, label: string) => {
    // 적응적 대기 — ASR pipeline 이 마지막 발화 처리 중이면 그 결과 도착까지 폴링.
    // 처리 끝나면 즉시 lifecycle 을 큐에 push (큐의 잔여 sentence 다 끝나고 lifecycle 적용).
    const arrivedAt = Date.now()
    const deadline = arrivedAt + LIFECYCLE_MAX_WAIT_MS
    console.log(`[UnitPlayer] lifecycle ${label} 도착 — ASR 처리 상태 확인 중`)
    let activeTimer: ReturnType<typeof setTimeout> | null = null

    const tryPush = () => {
      // 이전 fire 된 timer 를 set 에서 정리 (한 chain 당 1개만 추적).
      if (activeTimer !== null) {
        lifecycleTimersRef.current.delete(activeTimer)
        activeTimer = null
      }
      // ASR 처리 중인지 — speech_start 후 speech_end 전 구간에서 true.
      // 백엔드 broadcast 순서가 항상 speech_start → transcription → speech_end 라서
      // speechActive=false 인 시점은 이번 utterance 의 transcription 이 학생에 이미
      // 도착해 큐에 들어간 후. 안전하게 lifecycle 을 큐에 push 가능.
      // speech_end 직후 race 방지용 짧은 grace (500ms) 도 부여 — 다음 utterance 의
      // speech_start 가 곧 올 가능성 검사 윈도우.
      const sinceSpeechEnd = lastSpeechEndAtRef.current > 0
        ? Date.now() - lastSpeechEndAtRef.current
        : Infinity
      const stillProcessing = speechActiveRef.current || sinceSpeechEnd < LIFECYCLE_SPEECH_END_GRACE_MS
      const timedOut = Date.now() >= deadline

      if (stillProcessing && !timedOut) {
        activeTimer = setTimeout(tryPush, LIFECYCLE_POLL_MS)
        lifecycleTimersRef.current.add(activeTimer)
        return
      }
      if (timedOut) {
        console.warn(`[UnitPlayer] lifecycle ${label} ${LIFECYCLE_MAX_WAIT_MS}ms 초과 — 강제 적용`)
      }

      // 잔여 pending visual flush — page boundary 는 hold (단독 적용 방지).
      // lecture_end 면 reset 으로 비워지고, pause/resume 이면 resume 후 다음 sentence
      // 와 묶임. 어느 경우든 단독 페이지 전환은 발생하지 않음.
      const pending = pendingVisualRef.current
      if (pending.length > 0) {
        const flushable: PendingVisual[] = []
        const heldBack: PendingVisual[] = []
        for (const v of pending) {
          if (PAGE_BOUNDARY_KINDS.has(v.kind ?? '')) heldBack.push(v)
          else flushable.push(v)
        }
        pendingVisualRef.current = heldBack
        if (flushable.length > 0) {
          flushable.sort((a, b) => a.ts - b.ts)
          queueRef.current.push({ kind: 'visual_batch', visuals: flushable, label: `${label} 직전 visual flush` })
        }
      }
      queueRef.current.push({ kind: 'lifecycle', apply, label })
      console.log(
        `[UnitPlayer] lifecycle 큐 적재: ${label} ` +
        `(큐 깊이=${queueRef.current.length}, ASR 대기=${Date.now() - arrivedAt}ms)`,
      )
      processNext()
    }

    tryPush()
  }, [processNext])

  const reset = useCallback(() => {
    queueRef.current = []
    pendingVisualRef.current = []
    speechActiveRef.current = false
    lastSpeechEndAtRef.current = 0
    lastTranscriptionAtRef.current = 0
    // 미발화 lifecycle drain timer 들 cancel — 이전 강의의 lecture_end 가 새 강의에서
    // 늦게 fire 되어 강의가 다시 종료되는 race 차단.
    for (const t of lifecycleTimersRef.current) clearTimeout(t)
    lifecycleTimersRef.current.clear()
    console.log('[UnitPlayer] reset — 큐 + pending 모두 비움')
  }, [])

  const getQueueLength = useCallback(() => queueRef.current.length, [])
  const getPendingVisualCount = useCallback(() => pendingVisualRef.current.length, [])

  // Silent watchdog — 발화 없이 시각만 들어오는 경우 (강사가 그림만 그림 / 커서만
  // 움직임) sentence 가 안 와서 pending 에 visual 이 갇히는 걸 방지.
  // Branch B: 발화 중 (speechActiveRef=true) 에는 절대 flush 안 함.
  // 발화 직후엔 transcription 도착까지 POST_SPEECH_ASR_TIMEOUT_MS 까지 대기.
  useEffect(() => {
    const id = setInterval(() => {
      const pending = pendingVisualRef.current
      if (pending.length === 0) return
      if (queueRef.current.length > 0) return
      if (isPlayingRef.current) return
      // 발화 중 — 어떤 idle 도 무시. 곧 sentence 가 와서 묶일 것.
      if (speechActiveRef.current) return

      // 발화 종료 후 ASR transcription 도착 대기 중인지 판단.
      // lastSpeechEndAtRef > lastTranscriptionAtRef: speech_end 후 아직 그 발화의
      //   transcription 이 안 왔음 → ASR 처리 중. 더 길게 기다림.
      const awaitingTranscription =
        lastSpeechEndAtRef.current > 0 &&
        lastSpeechEndAtRef.current > lastTranscriptionAtRef.current
      const threshold = awaitingTranscription
        ? POST_SPEECH_ASR_TIMEOUT_MS
        : SILENT_FLUSH_AFTER_MS

      const idleMs = Date.now() - lastVisualAddedAtRef.current
      // 발화 종료 후 대기 중이면 speech_end 시점부터 계산 (visual 은 발화 전에 들어왔을 수 있음).
      const elapsedSinceSpeechEnd = awaitingTranscription
        ? Date.now() - lastSpeechEndAtRef.current
        : Infinity
      const referenceMs = awaitingTranscription
        ? Math.min(idleMs, elapsedSinceSpeechEnd)
        : idleMs

      if (referenceMs < threshold) return

      // 페이지 boundary 이벤트는 hold — 다음 sentence 와 묶일 때까지 pending 유지.
      // 그림/커서만 visual_batch 로 flush. 페이지 전환만 단독 적용되는 어색함 차단.
      const flushable: PendingVisual[] = []
      const heldBack: PendingVisual[] = []
      for (const v of pending) {
        if (PAGE_BOUNDARY_KINDS.has(v.kind ?? '')) heldBack.push(v)
        else flushable.push(v)
      }
      if (flushable.length === 0) {
        // 전부 페이지 boundary — flush 안 함. 다음 sentence 도착 시까지 계속 대기.
        return
      }
      pendingVisualRef.current = heldBack
      flushable.sort((a, b) => a.ts - b.ts)
      queueRef.current.push({
        kind: 'visual_batch',
        visuals: flushable,
        label: awaitingTranscription ? 'asr-timeout flush' : 'silent flush',
      })
      console.log(
        `[UnitPlayer] ${awaitingTranscription ? 'asr-timeout' : 'silent'} flush — ` +
        `${flushable.length}건 visual_batch (idle=${idleMs}ms, threshold=${threshold}ms` +
        `${heldBack.length > 0 ? `, held=${heldBack.length}건 page boundary` : ''})`,
      )
      processNext()
    }, WATCHDOG_TICK_MS)
    return () => clearInterval(id)
  }, [processNext])

  return {
    enqueueVisual,
    enqueueSentence,
    enqueueLifecycle,
    markSpeechActive,
    markSpeechEnded,
    reset,
    getQueueLength,
    getPendingVisualCount,
  }
}
