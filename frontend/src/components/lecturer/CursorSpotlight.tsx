import { useEffect, useState } from 'react'

interface CursorSpotlightProps {
  enabled: boolean
  color: string
  size?: number
}

function CursorSpotlight({ enabled, color, size = 40 }: CursorSpotlightProps) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)

  useEffect(() => {
    if (!enabled) {
      setPos(null)
      return
    }
    const handleMove = (e: MouseEvent) => {
      setPos({ x: e.clientX, y: e.clientY })
    }
    const handleLeave = () => setPos(null)
    window.addEventListener('mousemove', handleMove)
    document.addEventListener('mouseleave', handleLeave)
    return () => {
      window.removeEventListener('mousemove', handleMove)
      document.removeEventListener('mouseleave', handleLeave)
    }
  }, [enabled])

  if (!enabled || !pos) return null

  return (
    <div
      className="pointer-events-none fixed z-[9999]"
      style={{
        left: pos.x,
        top: pos.y,
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
