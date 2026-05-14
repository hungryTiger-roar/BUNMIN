/**
 * CursorSpotlight - 마우스 포인터 강조 오버레이
 *
 * Props 기반 presentational component:
 * - x, y: 0~1 상대 좌표 (컨테이너 기준)
 * - visible: 표시 여부
 * - color: 스팟라이트 색상
 * - size: 스팟라이트 크기 (px)
 *
 * 사용처:
 * 1. Lecturer.tsx: 로컬 마우스 추적용 (window 이벤트 직접 처리)
 * 2. Student.tsx: 수신된 커서 좌표를 슬라이드 컨테이너 위에 오버레이
 */

interface CursorSpotlightProps {
  /** 0~1 범위 상대 좌표 (컨테이너 기준) */
  x: number
  y: number
  /** 표시 여부 */
  visible: boolean
  /** 스팟라이트 색상 (hex) */
  color: string
  /** 스팟라이트 크기 (px) */
  size?: number
  /**
   * 렌더링 모드:
   * - 'fixed': 브라우저 전체 기준 fixed positioning (강의자 로컬용)
   * - 'absolute': 부모 컨테이너 기준 absolute positioning (수강자 오버레이용)
   */
  mode?: 'fixed' | 'absolute'
}

function CursorSpotlight({
  x,
  y,
  visible,
  color,
  size = 40,
  mode = 'fixed',
}: CursorSpotlightProps) {
  if (!visible) return null

  // 좌표 범위 clamp (0~1)
  const clampedX = Math.max(0, Math.min(1, x))
  const clampedY = Math.max(0, Math.min(1, y))

  const positionStyle =
    mode === 'fixed'
      ? {
          position: 'fixed' as const,
          left: `${clampedX * 100}vw`,
          top: `${clampedY * 100}vh`,
        }
      : {
          position: 'absolute' as const,
          left: `${clampedX * 100}%`,
          top: `${clampedY * 100}%`,
        }

  return (
    <div
      className="pointer-events-none z-20"
      style={{
        ...positionStyle,
        width: size,
        height: size,
        transform: 'translate(-50%, -50%)',
        borderRadius: '50%',
        background: `radial-gradient(circle, ${color}66 0%, ${color}22 50%, ${color}00 70%)`,
        border: `2px solid ${color}`,
        boxShadow: `0 0 ${size / 2}px ${color}88, inset 0 0 ${size / 3}px ${color}44`,
      }}
    />
  )
}

export default CursorSpotlight
