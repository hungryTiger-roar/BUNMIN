/**
 * useUnitPlayer — Fixed-delay mirror player + page-anchor.
 *
 * 모델 (영화/라디오/유튜브 라이브 시청 같이):
 *   강사가 한 모든 행동 (그림 / 커서 / 페이지 / 음성 / 자막 / 강의 종료 등) 을 학생
 *   화면이 N초 늦게 "그대로" 재생. 강사 행동들 사이 시간 간격 그대로 보존 → 영상처럼
 *   자연스러운 흐름.
 *
 *   각 이벤트는 lecturerTimestamp 를 가짐. 첫 이벤트 도착 시 offset (네트워크 지연 +
 *   클럭 스큐) 를 측정 → 이후 모든 이벤트는 (lecturerTs + offset + BASE_DELAY) 시점에
 *   setTimeout 으로 적용. offset 은 강의 동안 고정 — 강의자 페이스 1:1 보존.
 *
 *   Page-anchor:
 *     이벤트 메시지 (transcription / draw_* / cursor) 가 page 필드를 들고 옴 →
 *     caller (useWebSocket / Student.tsx) 가 apply 콜백 안에서 setCurrentPage(page)
 *     를 먼저 호출 후 본 액션 실행. 시계 미스매치 / out-of-order 도착이 있어도
 *     이벤트가 강사 발생 페이지 위에서 재생되는 강한 보장.
 *
 *   결과:
 *     - 그림 / 커서 / 페이지 / 자막 / 오디오 모두 같은 offset 위에서 재생
 *     - 발화-그림-커서 모두 동일 페이지에서 (page-anchor)
 *     - 압축 / 가속 / 묶음 큐잉 없음 — 강사 행동의 자연스러운 흐름 보존
 *
 *   BASE_DELAY (3초):
 *     - TTS 합성 시간 (piper ~200~500ms) + 네트워크 jitter 흡수.
 *     - 너무 작으면 첫 음성이 합성 지연으로 visual 과 어긋남.
 *     - 너무 크면 학생 응답성 ↓.
 *     - 3초가 라이브성과 sync 안정성 사이 균형점.
 *
 *   reset:
 *     - 강의 시작/종료 boundary 에서 호출. 진행 중인 schedule 된 setTimeout 일괄 취소
 *       + offset 초기화 → 새 강의의 첫 이벤트가 새 offset 측정.
 */
import { useCallback, useEffect, useRef } from 'react'

export interface UnitPlayer {
  /** lecturer 시각 ts 에 발생한 이벤트를 학생 wall clock (ts + offset + BASE_DELAY)
   *  시점에 apply. 그림/커서/페이지/자막/오디오 모든 시각·오디오 이벤트가 이 메서드
   *  하나로 schedule. apply 콜백에서 setCurrentPage(page) 같은 page-anchor 를
   *  caller 가 직접 묶어 보내야 함. */
  enqueueVisual: (ts: number, apply: () => void, kind?: string) => void
  /** lecture_end / pause / resume 등 lifecycle. ts 있으면 enqueueVisual 과 동일 offset
   *  으로 schedule, 없으면 즉시 apply. */
  enqueueLifecycle: (ts: number | undefined, apply: () => void, label: string) => void
  /** 강의 boundary — schedule 된 모든 timer 취소 + offset 초기화. */
  reset: () => void
}

/** 강사 시계 → 학생 적용 시계 사이 추가 지연. TTS 합성 시간 + jitter 흡수용. */
const BASE_DELAY_MS = 3000

export function useUnitPlayer(): UnitPlayer {
  /** offset = 첫 이벤트의 (학생 wall clock - lecturerTs). 네트워크 지연 + 클럭 스큐
   *  포함. 강의 동안 고정. reset 시 null 로 돌려 다음 첫 이벤트가 다시 측정. */
  const offsetRef = useRef<number | null>(null)
  /** schedule 된 timer id — reset 시 일괄 cancel 용. */
  const timerIdsRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set())

  const ensureOffset = (lecturerTs: number): number => {
    if (offsetRef.current === null) {
      offsetRef.current = Date.now() - lecturerTs
      console.log(`[UnitPlayer] offset 초기화: ${offsetRef.current}ms`)
    }
    return offsetRef.current
  }

  const schedule = (ts: number, apply: () => void, label?: string) => {
    const offset = ensureOffset(ts)
    const applyAt = ts + offset + BASE_DELAY_MS
    const delay = Math.max(0, applyAt - Date.now())
    const id = setTimeout(() => {
      timerIdsRef.current.delete(id)
      try { apply() } catch (err) {
        console.error(`[UnitPlayer] apply 오류 (${label ?? 'unknown'}):`, err)
      }
    }, delay)
    timerIdsRef.current.add(id)
  }

  const enqueueVisual = useCallback((ts: number, apply: () => void, kind?: string) => {
    schedule(ts, apply, kind)
    // cursor / draw_point 는 고빈도 — 로그 noise 방지로 제외.
    if (kind && kind !== 'cursor' && kind !== 'draw_point') {
      const offset = offsetRef.current ?? 0
      const delay = Math.max(0, ts + offset + BASE_DELAY_MS - Date.now())
      console.log(`[UnitPlayer] schedule ${kind} ts=${ts} delay=${delay}ms`)
    }
  }, [])

  const enqueueLifecycle = useCallback((ts: number | undefined, apply: () => void, label: string) => {
    if (typeof ts === 'number') {
      schedule(ts, apply, label)
      console.log(`[UnitPlayer] lifecycle schedule: ${label} ts=${ts}`)
    } else {
      // ts 미제공 — 즉시 apply (방어적 fallback).
      try { apply() } catch (err) {
        console.error(`[UnitPlayer] lifecycle apply 오류 (${label}):`, err)
      }
      console.log(`[UnitPlayer] lifecycle 즉시: ${label} (ts 없음)`)
    }
  }, [])

  const reset = useCallback(() => {
    for (const id of timerIdsRef.current) clearTimeout(id)
    timerIdsRef.current.clear()
    offsetRef.current = null
    console.log('[UnitPlayer] reset — 모든 timer 취소 + offset 초기화')
  }, [])

  // unmount 시 timer cleanup.
  useEffect(() => () => {
    for (const id of timerIdsRef.current) clearTimeout(id)
    timerIdsRef.current.clear()
  }, [])

  return { enqueueVisual, enqueueLifecycle, reset }
}
