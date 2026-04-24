import { useEffect, useRef, useState, type RefObject } from 'react'

interface AudioLevelMeterProps {
  analyser: RefObject<AnalyserNode | null>
  active: boolean
}

const MIN_DB = -60
const MAX_DB = 0

function dbToPercent(db: number): number {
  if (!isFinite(db)) return 0
  const clamped = Math.max(MIN_DB, Math.min(MAX_DB, db))
  return ((clamped - MIN_DB) / (MAX_DB - MIN_DB)) * 100
}

function AudioLevelMeter({ analyser, active }: AudioLevelMeterProps) {
  const [levelDb, setLevelDb] = useState<number>(MIN_DB)
  const [peakDb, setPeakDb] = useState<number>(MIN_DB)
  const rafRef = useRef<number | null>(null)
  const peakHoldRef = useRef<number>(MIN_DB)
  const peakDecayRef = useRef<number>(0)

  useEffect(() => {
    if (!active) {
      setLevelDb(MIN_DB)
      setPeakDb(MIN_DB)
      peakHoldRef.current = MIN_DB
      peakDecayRef.current = 0
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      return
    }

    const buffer = new Float32Array(2048)

    const update = () => {
      const node = analyser.current
      if (!node) {
        rafRef.current = requestAnimationFrame(update)
        return
      }

      node.getFloatTimeDomainData(buffer)

      let sumSq = 0
      for (let i = 0; i < buffer.length; i++) {
        sumSq += buffer[i] * buffer[i]
      }
      const rms = Math.sqrt(sumSq / buffer.length)
      const db = 20 * Math.log10(Math.max(rms, 1e-10))

      setLevelDb(db)

      // peak hold with delayed decay
      if (db > peakHoldRef.current) {
        peakHoldRef.current = db
        peakDecayRef.current = 0
      } else {
        peakDecayRef.current += 1
        if (peakDecayRef.current > 30) {
          peakHoldRef.current -= 0.7
        }
      }
      setPeakDb(peakHoldRef.current)

      rafRef.current = requestAnimationFrame(update)
    }

    rafRef.current = requestAnimationFrame(update)

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [active, analyser])

  const levelPct = dbToPercent(levelDb)
  const peakPct = dbToPercent(peakDb)

  const displayDb = isFinite(levelDb) && levelDb > MIN_DB ? Math.round(levelDb) : null
  const inTarget = levelDb >= -20 && levelDb <= -15
  const inPeakWarn = levelDb >= -6

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-onSurface/70">평균 레벨</span>
        <span
          className={`font-mono tabular-nums ${
            !active
              ? 'text-onSurface/40'
              : inPeakWarn
                ? 'text-red-500 font-semibold'
                : inTarget
                  ? 'text-emerald-500 font-semibold'
                  : 'text-onSurface/80'
          }`}
        >
          {displayDb === null ? '—' : `${displayDb} dB`}
        </span>
      </div>
      <div className="relative h-3 rounded-full overflow-hidden bg-gradient-to-r from-emerald-400 via-yellow-400 to-red-500">
        {/* Unlit overlay from the right */}
        <div
          className="absolute top-0 bottom-0 right-0 bg-slate-200 transition-[width] duration-75"
          style={{ width: `${100 - levelPct}%` }}
        />
        {/* Peak hold line */}
        {active && peakPct > 0 && (
          <div
            className="absolute top-0 bottom-0 w-0.5 bg-white/90 shadow-md"
            style={{ left: `${peakPct}%` }}
          />
        )}
        {/* Target zone markers at -20 and -15 dB */}
        <div
          className="absolute top-0 bottom-0 w-px bg-emerald-700/40"
          style={{ left: `${dbToPercent(-20)}%` }}
        />
        <div
          className="absolute top-0 bottom-0 w-px bg-emerald-700/40"
          style={{ left: `${dbToPercent(-15)}%` }}
        />
      </div>
      <div className="flex justify-between text-[10px] text-onSurface/50 tabular-nums">
        <span>-60</span>
        <span className="text-emerald-600">-20 ~ -15 (적정)</span>
        <span className="text-red-500">0 dB</span>
      </div>
    </div>
  )
}

export default AudioLevelMeter
