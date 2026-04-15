interface OverlayItem {
  original: string
  translated: string
  bbox: number[] // [x1, y1, x2, y2]
  confidence: number
}

interface ScreenOverlayProps {
  items: OverlayItem[]
}

function ScreenOverlay({ items }: ScreenOverlayProps) {
  if (items.length === 0) return null

  return (
    <div className="absolute inset-0 pointer-events-none">
      {items.map((item, index) => {
        const [x1, y1, x2, y2] = item.bbox
        const width = x2 - x1
        const height = y2 - y1

        // 너무 작은 영역은 스킵
        if (width < 10 || height < 5) return null

        // 신뢰도가 낮은 항목은 스킵
        if (item.confidence < 0.5) return null

        return (
          <div
            key={index}
            className="absolute bg-slate-900/85 text-white px-2 py-1 rounded text-sm leading-tight"
            style={{
              left: `${(x1 / 1920) * 100}%`,
              top: `${(y1 / 1080) * 100}%`,
              maxWidth: `${(width / 1920) * 100 + 5}%`,
            }}
          >
            {item.translated}
          </div>
        )
      })}
    </div>
  )
}

export default ScreenOverlay
