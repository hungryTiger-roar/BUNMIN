import { useRef, useCallback } from 'react'
import type { CursorMessage } from '@/hooks/useWebSocket'

/**
 * StudentCursorOverlay - 수강자 화면 강의자 커서 오버레이
 *
 * React 상태를 사용하지 않고 ref로 DOM을 직접 조작하여
 * 고빈도 커서 업데이트 시에도 리렌더링이 발생하지 않음
 *
 * 사용법:
 * const { spotlightRef, onCursor } = useCursorOverlay(containerRef)
 * useWebSocket(url, 'student', { onCursor })
 * <StudentCursorOverlay spotlightRef={spotlightRef} />
 */

const SPOTLIGHT_SIZE = 40

export function useCursorOverlay(containerRef: React.RefObject<HTMLDivElement | null>) {
  const spotlightRef = useRef<HTMLDivElement>(null)

  const onCursor = useCallback((cursor: CursorMessage) => {
    const el = spotlightRef.current
    const container = containerRef.current
    if (!el || !container) return

    // 컨테이너 내 이미지 요소 찾기
    const img = container.querySelector('img') as HTMLImageElement | null
    const containerRect = container.getBoundingClientRect()

    if (containerRect.width === 0 || containerRect.height === 0) return

    // 이미지의 실제 렌더링 영역 계산 (object-fit: contain 고려)
    let imgOffsetX = 0
    let imgOffsetY = 0
    let imgWidth = containerRect.width
    let imgHeight = containerRect.height

    if (img && img.naturalWidth && img.naturalHeight) {
      const imgRatio = img.naturalWidth / img.naturalHeight
      const containerRatio = containerRect.width / containerRect.height

      if (imgRatio > containerRatio) {
        // 이미지가 더 넓음 → 좌우 맞춤, 위아래 여백
        imgWidth = containerRect.width
        imgHeight = containerRect.width / imgRatio
      } else {
        // 이미지가 더 좁음 → 위아래 맞춤, 좌우 여백
        imgHeight = containerRect.height
        imgWidth = containerRect.height * imgRatio
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

      // GPU 가속 transform (px 단위)
      el.style.transform = `translate3d(${px}px, ${py}px, 0) translate(-50%, -50%)`
      el.style.opacity = '1'
      // 색상 업데이트
      el.style.borderColor = cursor.color
      el.style.background = `radial-gradient(circle, ${cursor.color}66 0%, ${cursor.color}22 50%, ${cursor.color}00 70%)`
      el.style.boxShadow = `0 0 ${SPOTLIGHT_SIZE / 2}px ${cursor.color}88, inset 0 0 ${SPOTLIGHT_SIZE / 3}px ${cursor.color}44`
    } else {
      el.style.opacity = '0'
    }
  }, [containerRef])

  return { spotlightRef, onCursor }
}

interface StudentCursorOverlayProps {
  spotlightRef: React.RefObject<HTMLDivElement>
}

export function StudentCursorOverlay({ spotlightRef }: StudentCursorOverlayProps) {
  return (
    <div
      ref={spotlightRef}
      className="pointer-events-none absolute z-[9999]"
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
        transition: 'opacity 0.1s ease-out',
      }}
    />
  )
}
