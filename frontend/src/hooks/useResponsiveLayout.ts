import { useState, useEffect } from 'react'

// Wide layout constants
export const WIDE_MIN_WIDTH = 900
export const WIDE_MIN_HEIGHT = 500
export const WIDE_MEDIA_QUERY = `(min-width: ${WIDE_MIN_WIDTH}px) and (min-height: ${WIDE_MIN_HEIGHT}px)`

type LayoutMode = 'compact' | 'wide'

interface LayoutState {
  mode: LayoutMode
  isWide: boolean
  isCompact: boolean
}

function getLayoutMode(): LayoutMode {
  // SSR safety
  if (typeof window === 'undefined') return 'compact'
  return window.matchMedia(WIDE_MEDIA_QUERY).matches ? 'wide' : 'compact'
}

export function useResponsiveLayout(): LayoutState {
  const [mode, setMode] = useState<LayoutMode>(() => getLayoutMode())

  useEffect(() => {
    const handleChange = () => {
      const nextMode = getLayoutMode()
      // Skip setState if mode unchanged (prevents unnecessary re-renders)
      setMode(prev => (prev === nextMode ? prev : nextMode))
    }

    const mediaQuery = window.matchMedia(WIDE_MEDIA_QUERY)

    // Listen to resize + orientationchange + matchMedia
    window.addEventListener('resize', handleChange)
    window.addEventListener('orientationchange', handleChange)
    mediaQuery.addEventListener('change', handleChange)

    // Check actual viewport after initial render
    handleChange()

    return () => {
      window.removeEventListener('resize', handleChange)
      window.removeEventListener('orientationchange', handleChange)
      mediaQuery.removeEventListener('change', handleChange)
    }
  }, [])

  return {
    mode,
    isWide: mode === 'wide',
    isCompact: mode === 'compact',
  }
}
