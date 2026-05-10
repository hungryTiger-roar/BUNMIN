/**
 * useDelayBufferPlayer — Wall-clock delay buffer (Sync Mode B).
 *
 * 모델 — 모든 events 를 강사 시계 + DELAY 에 그대로 재현.
 *
 *   강사가 wall=T 에 한 행동을 학생 wall=T+offset+DELAY 에 같은 속도로 재현.
 *   visual stretch / audio compress 없음 — 강사 박자 그대로.
 *
 *   비유: "유튜브 라이브" — 모든 콘텐츠 (영상+음성) 가 N초 lag 으로 동시 송출.
 *
 *   동작:
 *     - 시각 (그림/커서/페이지): setTimeout(apply, lec_ts + offset + DELAY - now)
 *     - 음성 (sentence audio): setTimeout(playSentence, speechStartAt + offset + DELAY - now)
 *     - 생명주기 (pause/resume/end): setTimeout(apply, sentAt 추정 + offset + DELAY - now)
 *
 *   강사↔학생 시계 offset:
 *     - 매 incoming event 의 lecturerTimestamp 와 도착시각 차로 추정.
 *     - EWMA 스무딩 (jitter 흡수).
 *     - 네트워크 latency 가 작아 (~50ms) offset 정확도 충분.
 *
 *   audio 서열화:
 *     - 영어 TTS 가 한국어 발화보다 길어 schedule 시각이 겹칠 수 있음.
 *     - 직전 audio 의 ended Promise 가 끝나야 다음 audio 시작 — sequential queue.
 *     - audio 가 visual 보다 뒤로 drift 할 수 있으나 visual 자체는 강사 박자 보존.
 *
 *   late event:
 *     - target_wall < now 면 setTimeout(0) 으로 즉시 apply (사라지지 않음).
 *
 * Trade-off vs option-f (useUnitPlayer):
 *   + 시각이 강사 속도 그대로 — stretch 0.05x ~ 5746x 같은 비정상 케이스 없음
 *   + audio 안 와도 시각은 자기 속도로 흘러감 (anchor 의존 X)
 *   + 모든 모달리티가 같은 시간선에 — 자연스러움
 *   - 항상 DELAY (예: 15초) lag — 라이브 감 ↓
 *   - audio 길이 > 강사 발화 길이일 때 audio 가 visual 보다 뒤로 drift
 *
 * 권장 설정:
 *   VITE_SYNC_MODE=delay-buffer  (default)
 *   VITE_SYNC_DELAY_MS=15000     (95%ile ASR+NMT+TTS latency 커버)
 */
import { useCallback, useEffect, useRef } from 'react'
import type { TranslationLang } from '@/stores/preferencesStore'
import type { UnitPlayer } from './useUnitPlayer'

interface Options {
  playSentence: (
    text: string,
    lang: TranslationLang,
    subtitleId?: string,
  ) => Promise<{ audioStartedAt: number; durationMs: number; ended: Promise<void>; ttsMs: number }>
  isAudioUnlocked: () => boolean
  getAudioLang: () => TranslationLang
  /** 학생 wall - 강사 wall offset (ms). 미설정 시 0 으로 가정 (네트워크 latency 무시).
   *  자동 추정도 내부에서 함 — 외부 주입은 옵션. */
  delayMs?: number
}

export function useDelayBufferPlayer(options: Options): UnitPlayer {
  // 강사 wall → 학생 wall offset 추정 (EWMA). null 이면 첫 event 가 들어오기 전.
  const clockOffsetRef = useRef<number | null>(null)
  // delay budget — env 로 주입 가능, 없으면 15초.
  const delayMs = options.delayMs ?? 15000

  const optionsRef = useRef(options)
  useEffect(() => { optionsRef.current = options }, [options])

  // Audio 직렬 큐 — 영어 TTS 가 한국어보다 길어 schedule 겹치는 케이스 대응.
  // 이전 audio 의 ended 가 끝나야 다음 audio 시작.
  const audioQueueRef = useRef<Array<() => Promise<void>>>([])
  const audioPlayingRef = useRef(false)

  const updateClockOffset = useCallback((lecTs: number) => {
    if (typeof lecTs !== 'number' || !isFinite(lecTs)) return
    const observed = Date.now() - lecTs
    // OUTLIER 차단 — 네트워크 spike / 서버 backlog 등으로 정상 범위 (수십~수백ms) 벗어난
    //   관측은 무시. 5초 이상 차이는 시계 동기화 문제거나 stale event 로 간주.
    if (Math.abs(observed) > 5000) return
    if (clockOffsetRef.current === null) {
      clockOffsetRef.current = observed
    } else {
      // EWMA: alpha=0.1 — jitter 흡수 + 시계 drift 따라감.
      clockOffsetRef.current = clockOffsetRef.current * 0.9 + observed * 0.1
    }
  }, [])

  const studentWallFor = useCallback((lecTs: number): number => {
    const offset = clockOffsetRef.current ?? 0
    return lecTs + offset + delayMs
  }, [delayMs])

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
    const targetWall = studentWallFor(ts)
    scheduleAt(targetWall, apply)
    if (kind && kind !== 'cursor' && kind !== 'draw_point') {
      const ahead = targetWall - Date.now()
      console.log(`[DelayBuf] visual ${kind} ts=${ts} → +${Math.round(ahead)}ms`)
    }
  }, [updateClockOffset, studentWallFor, scheduleAt])

  /** transcript 가 schedule 보다 이만큼 (ms) 늦으면 stale 로 판단해 drop.
   *  pause 후 ASR pipeline 이 옛 audio frame 을 뒤늦게 transcribe 하는 케이스 catch.
   *  10초 = 정상 ASR 변동폭 (~5초) 의 2배 — 정상 발화는 안 잡고 stale 만 잡는 임계. */
  const STALE_THRESHOLD_MS = 10000

  const enqueueSentence = useCallback((params: {
    text: string
    commitSubtitle: (ttsMs?: number) => void
    speechStartAt: number
    sentAt: number
  }) => {
    // 주의: clockOffset 은 sentence timestamp 로 갱신하지 않음.
    //   sentAt / speechStartAt 은 lecturer wall time of the speech (인식 결과 도착 시점 X).
    //   pause 후 ASR pipeline 에 누적된 옛 audio frame 이 60초 후 transcribe 되면
    //   sentAt 이 60초 전 시각이라 (now - sentAt) 가 +60000ms 로 보임 → offset 오염.
    //   visual events 만 갱신에 사용 (lecturerTimestamp 가 broadcast 시점이라 fresh).

    const targetWall = studentWallFor(params.speechStartAt)
    const ahead = targetWall - Date.now()

    // STALE drop — 너무 늦은 transcript (pause 직후 옛 audio frame 의 transcribe 결과).
    //   재생해도 visual 은 이미 다 흘러간 후라 sync 깨진 채 들림 → drop 이 더 나음.
    if (ahead < -STALE_THRESHOLD_MS) {
      console.warn(
        `[DelayBuf] STALE drop (${Math.round(-ahead)}ms late): "${params.text.slice(0, 40)}..."`,
      )
      return
    }

    console.log(
      `[DelayBuf] sentence "${params.text.slice(0, 30)}..." ` +
      `lecSpan=${params.sentAt - params.speechStartAt}ms scheduled=+${Math.round(ahead)}ms`,
    )

    // 예약 시간에 audio 큐에 push — sequential 재생 보장.
    // 자막은 audio 가 실제 시작될 때 표시 → 자막↔TTS 동기화. audio off 면 schedule
    // 시점에 즉시 표시 (audio 가 anchor 가 없으니 wall-clock 시점에 맞춰 등장).
    scheduleAt(targetWall, () => {
      const opts = optionsRef.current
      if (opts.getAudioLang() === 'off' || !opts.isAudioUnlocked()) {
        try { params.commitSubtitle() } catch (err) { console.error('[DelayBufferPlayer] commitSubtitle 오류:', err) }
        return
      }
      audioQueueRef.current.push(async () => {
        try {
          const result = await opts.playSentence(params.text, opts.getAudioLang())
          // audio 시작 시점에 자막 표시 — 이전 audio 가 큐에서 대기 중이었더라도
          // 실제 재생 시작 시각 (audioStartedAt) 에 맞춰 등장.
          const subtitleDelay = Math.max(0, result.audioStartedAt - Date.now())
          setTimeout(() => {
            try { params.commitSubtitle(result.ttsMs) } catch (err) { console.error('[DelayBufferPlayer] commitSubtitle 오류:', err) }
          }, subtitleDelay)
          await result.ended
        } catch (err) {
          console.error('[DelayBufferPlayer] playSentence 실패:', err)
          // 합성 실패해도 자막은 보여줘야 — 즉시 표시.
          try { params.commitSubtitle() } catch (e) { console.error('[DelayBufferPlayer] commitSubtitle 오류:', e) }
        }
      })
      processAudioQueue()
    })
  }, [studentWallFor, scheduleAt, processAudioQueue])

  const enqueueLifecycle = useCallback((apply: () => void | Promise<void>, label: string) => {
    // lifecycle 은 wall-clock timestamp 가 명시적으로 안 오는 경우가 있음 (sentAt 없음).
    // → 도착 시점 기준 +delayMs 로 적용. 강사가 lecture_pause 누른 시점은 학생측에선
    //   delayMs 후에 일시정지되는 게 맞음.
    const targetWall = Date.now() + delayMs
    console.log(`[DelayBuf] lifecycle ${label} → +${delayMs}ms`)
    scheduleAt(targetWall, apply)
  }, [delayMs, scheduleAt])

  const reset = useCallback(() => {
    audioQueueRef.current = []
    // setTimeout 들은 cancel 하지 않음 — 이미 등록된 visual/audio 는 자기 시간에 fire.
    // 강의 boundary 에서 frontend store 가 isLectureStarted 가드로 무시할 것.
    // (option-f reset 도 setTimeout 은 안 건드림 — 동일 정책)
    console.log('[DelayBufferPlayer] reset')
  }, [])

  const getQueueLength = useCallback(() => audioQueueRef.current.length, [])
  const getPendingVisualCount = useCallback(() => 0, []) // setTimeout 기반이라 pending 개념 없음

  // Branch B: speech_start / speech_end 신호는 unit-stretch 모드 (silent watchdog)
  // 만 사용. delay-buffer 모드는 wall-clock + 고정 lag 라서 watchdog 자체가 없음.
  // 인터페이스 호환을 위해 no-op 으로 제공.
  const markSpeechActive = useCallback(() => {}, [])
  const markSpeechEnded = useCallback(() => {}, [])

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
