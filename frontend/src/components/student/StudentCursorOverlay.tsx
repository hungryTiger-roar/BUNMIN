import { useRef, useCallback, useEffect } from 'react'
import type { CursorMessage } from '@/hooks/useWebSocket'

/**
 * StudentCursorOverlay - 수강자 화면 강의자 커서 오버레이
 *
 * React 상태 없이 ref + requestAnimationFrame 으로 DOM 직접 조작 →
 * 고빈도 커서 업데이트 + 매끄러운 보간 (점 → 점 사이를 영상처럼).
 *
 * 보간 방식:
 *   - 마지막 도착 좌표를 target 으로 저장
 *   - rAF 루프에서 current 좌표를 target 쪽으로 일정 비율 (LERP_FACTOR) 이동
 *   - 도착 빈도 (60Hz) 보다 학생 PC refresh rate (60~120Hz) 가 빠르거나 같으면
 *     cursor 가 영상처럼 자연스럽게 흐름. 빈도가 낮은 경우 (네트워크 지연 등) 도
 *     점프 없이 lerp 으로 부드럽게 따라감.
 *
 * 사용법:
 * const { spotlightRef, onCursor } = useCursorOverlay(containerRef)
 * useWebSocket(url, 'student', { onCursor })
 * <StudentCursorOverlay spotlightRef={spotlightRef} />
 */

const SPOTLIGHT_SIZE = 40
/** 매 프레임 target 쪽으로 이동하는 비율 — 0.3 ≈ 3프레임 (~50ms) 안에 도달.
 *  너무 크면 jump 같고 (1.0 = 즉시), 너무 작으면 항상 lag (0.05 = 매우 느림). */
const LERP_FACTOR = 0.3
/** 보간 오차 임계 — 이 이하면 정확히 target 위치로 snap + rAF 정지. */
const SNAP_THRESHOLD_PX = 0.5

export function useCursorOverlay(containerRef: React.RefObject<HTMLDivElement | null>) {
  const spotlightRef = useRef<HTMLDivElement>(null)
  // rAF 보간 상태
  const targetRef = useRef<{ x: number; y: number; visible: boolean; color: string } | null>(null)
  const currentRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 })
  const rafIdRef = useRef<number | null>(null)

  /** rAF 루프 — 매 프레임 current 를 target 으로 lerp. target 도달하면 정지. */
  const animate = useCallback(() => {
    const el = spotlightRef.current
    const target = targetRef.current
    if (!el || !target) {
      rafIdRef.current = null
      return
    }
    if (!target.visible) {
      el.style.opacity = '0'
      rafIdRef.current = null
      return
    }
    const dx = target.x - currentRef.current.x
    const dy = target.y - currentRef.current.y
    if (Math.abs(dx) < SNAP_THRESHOLD_PX && Math.abs(dy) < SNAP_THRESHOLD_PX) {
      // snap to target — rAF 정지.
      currentRef.current.x = target.x
      currentRef.current.y = target.y
      el.style.transform = `translate3d(${target.x}px, ${target.y}px, 0) translate(-50%, -50%)`
      rafIdRef.current = null
      return
    }
    currentRef.current.x += dx * LERP_FACTOR
    currentRef.current.y += dy * LERP_FACTOR
    el.style.transform = `translate3d(${currentRef.current.x}px, ${currentRef.current.y}px, 0) translate(-50%, -50%)`
    rafIdRef.current = requestAnimationFrame(animate)
  }, [])

  const onCursor = useCallback((cursor: CursorMessage) => {
    const el = spotlightRef.current
    const container = containerRef.current
    if (!el || !container) return

    // 컨테이너 내 미디어 요소 찾기 (슬라이드 모드 = img, 화면공유 모드 = video)
    const media = container.querySelector('img, video') as HTMLImageElement | HTMLVideoElement | null
    const containerRect = container.getBoundingClientRect()

    if (containerRect.width === 0 || containerRect.height === 0) return

    // 이미지/비디오의 실제 렌더링 영역 계산 (object-fit: contain 고려)
    let imgOffsetX = 0
    let imgOffsetY = 0
    let imgWidth = containerRect.width
    let imgHeight = containerRect.height

    const naturalW = media instanceof HTMLImageElement ? media.naturalWidth
                   : media instanceof HTMLVideoElement ? media.videoWidth
                   : 0
    const naturalH = media instanceof HTMLImageElement ? media.naturalHeight
                   : media instanceof HTMLVideoElement ? media.videoHeight
                   : 0

    if (naturalW && naturalH) {
      const ratio = naturalW / naturalH
      const containerRatio = containerRect.width / containerRect.height

      if (ratio > containerRatio) {
        imgWidth = containerRect.width
        imgHeight = containerRect.width / ratio
      } else {
        imgHeight = containerRect.height
        imgWidth = containerRect.height * ratio
      }
      imgOffsetX = (containerRect.width - imgWidth) / 2
      imgOffsetY = (containerRect.height - imgHeight) / 2
    }

    if (cursor.visible) {
      // 0~1 상대좌표 → 이미지 영역 기준 px 변환
      const clampedX = Math.max(0, Math.min(1, cursor.x))
      const clampedY = Math.max(0, Math.min(1, cursor.y))
      const px = imgOffsetX + clampedX * imgWidth
      const py = imgOffsetY + clampedY * imgHeight

      // 이전 target 이 없으면 (첫 표시 / 숨김 → 표시 전환) snap. 아니면 lerp.
      const prevTarget = targetRef.current
      if (!prevTarget || !prevTarget.visible) {
        currentRef.current.x = px
        currentRef.current.y = py
        el.style.transform = `translate3d(${px}px, ${py}px, 0) translate(-50%, -50%)`
      }
      targetRef.current = { x: px, y: py, visible: true, color: cursor.color }
      el.style.opacity = '1'
      // 색상 업데이트 (보간 안 함 — 즉시 반영)
      el.style.borderColor = cursor.color
      el.style.background = `radial-gradient(circle, ${cursor.color}66 0%, ${cursor.color}22 50%, ${cursor.color}00 70%)`
      el.style.boxShadow = `0 0 ${SPOTLIGHT_SIZE / 2}px ${cursor.color}88, inset 0 0 ${SPOTLIGHT_SIZE / 3}px ${cursor.color}44`
      // rAF 루프 시작 (이미 돌고 있으면 그대로).
      if (rafIdRef.current === null) {
        rafIdRef.current = requestAnimationFrame(animate)
      }
    } else {
      targetRef.current = targetRef.current
        ? { ...targetRef.current, visible: false }
        : { x: 0, y: 0, visible: false, color: '#60A5FA' }
      el.style.opacity = '0'
      // 숨김 — rAF 자연 정지 (animate 내부에서 visible=false 감지 후 멈춤).
      if (rafIdRef.current === null) {
        rafIdRef.current = requestAnimationFrame(animate)
      }
    }
  }, [containerRef, animate])

  // unmount 시 rAF 정리.
  useEffect(() => () => {
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current)
      rafIdRef.current = null
    }
  }, [])

  return { spotlightRef, onCursor }
}

interface StudentCursorOverlayProps {
  spotlightRef: React.RefObject<HTMLDivElement>
}

export function StudentCursorOverlay({ spotlightRef }: StudentCursorOverlayProps) {
  return (
    <div
      ref={spotlightRef}
      className="pointer-events-none absolute z-10"
      style={{
        width: SPOTLIGHT_SIZE,
        height: SPOTLIGHT_SIZE,
        left: 0,
        top: 0,
        transform: 'translate3d(0, 0, 0) translate(-50%, -50%)',
        opacity: 0,
        borderRadius: '50%',
        border: '2px solid #60A5FA',
        background: 'radial-gradient(circle, #60A5FA66 0%, #60A5FA22 50%, #60A5FA00 70%)',
        boxShadow: `0 0 ${SPOTLIGHT_SIZE / 2}px #60A5FA88, inset 0 0 ${SPOTLIGHT_SIZE / 3}px #60A5FA44`,
        willChange: 'transform, opacity',
        // rAF 보간이 transform 매끄럽게 처리 — CSS transition 제거 (이중 보간 방지).
        // opacity 만 fade.
        transition: 'opacity 0.1s ease-out',
      }}
    />
  )
}
