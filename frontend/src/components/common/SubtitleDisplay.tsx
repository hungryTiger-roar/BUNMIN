interface Subtitle {
  id: string
  original: string
  translated: string
  timestamp: number
}

interface SubtitleDisplayProps {
  subtitles: Subtitle[]
  maxItems?: number
  variant?: 'light' | 'dark'
}

function SubtitleDisplay({ subtitles, maxItems = 3, variant = 'light' }: SubtitleDisplayProps) {
  const recentSubtitles = subtitles.slice(-maxItems)

  if (recentSubtitles.length === 0) {
    return (
      <div className={`text-center py-4 ${variant === 'dark' ? 'text-slate-500' : 'text-slate-400'}`}>
        <p className="text-sm">자막이 여기에 표시됩니다</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {recentSubtitles.map((subtitle, index) => {
        const isLatest = index === recentSubtitles.length - 1
        const opacity = isLatest ? 1 : 0.6

        return (
          <div
            key={subtitle.id}
            className={`transition-opacity duration-300 ${
              variant === 'dark' ? 'text-white' : ''
            }`}
            style={{ opacity }}
          >
            {variant === 'light' ? (
              // 강의자용 (밝은 배경)
              <div className="space-y-1">
                <p className="text-sm text-slate-500">
                  <span className="inline-block w-8 text-xs font-medium text-slate-400">[한]</span>
                  {subtitle.original}
                </p>
                <p className="text-sm text-slate-800">
                  <span className="inline-block w-8 text-xs font-medium text-blue-500">[EN]</span>
                  {subtitle.translated}
                </p>
              </div>
            ) : (
              // 수강자용 (어두운 배경)
              <div className="text-center">
                <p className="text-lg font-medium leading-relaxed">
                  {subtitle.translated}
                </p>
                <p className="text-sm text-slate-400 mt-1">
                  {subtitle.original}
                </p>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default SubtitleDisplay
