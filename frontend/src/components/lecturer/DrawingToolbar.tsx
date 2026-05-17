/**
 * DrawingToolbar — 강의자 사이드바 필기 카드
 * 도구: 연필 / 형광펜 / 사각형 / 지우개 + 액션: 전체 지우기
 * 색상: 마우스 포인터와 동일한 6색 팔레트 (지우개/전체지우기 선택 시 색 disabled)
 */
import type { DrawingTool } from '@/components/common/DrawingCanvas'

interface DrawingToolbarProps {
  enabled: boolean
  setEnabled: (v: boolean) => void
  tool: DrawingTool
  setTool: (t: DrawingTool) => void
  color: string
  setColor: (c: string) => void
  /** 마우스 포인터 카드와 동일한 6색 팔레트 */
  palette: readonly string[]
  /** "전체 지우기" 버튼 — 현재 페이지의 모든 필기 삭제 */
  onClearAll: () => void
}

const TOOL_BUTTONS: { value: DrawingTool; label: string; icon: JSX.Element }[] = [
  {
    value: 'pencil',
    label: '연필',
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.862 4.487zM19.5 7.125l-2.625-2.625" />
      </svg>
    ),
  },
  {
    value: 'highlighter',
    label: '형광펜',
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 11l3 3L22 4l-3-3-10 10zm0 0l-5 5v3h3l5-5m-3-3l5 5" />
      </svg>
    ),
  },
  {
    value: 'rect',
    label: '사각형',
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
        <rect x="4" y="5" width="16" height="14" rx="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    value: 'eraser',
    label: '지우개',
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 3.5l4 4-11 11h-5v-5l11-11a1.4 1.4 0 012 0l1 1zM9 19h12" />
      </svg>
    ),
  },
]

function DrawingToolbar({
  enabled,
  setEnabled,
  tool,
  setTool,
  color,
  setColor,
  palette,
  onClearAll,
}: DrawingToolbarProps) {
  return (
    <div className="bg-surface dark:bg-overlaySurface text-onSurface rounded-xl p-4 shadow-sm sidebar-card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold">필기</h3>
        <button
          type="button"
          onClick={() => setEnabled(!enabled)}
          className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
            enabled
              ? 'bg-primary text-onPrimary shadow-sm'
              : 'bg-primaryContainer text-onSurface/60 hover:bg-primaryContainer hover:text-onSurface'
          }`}
          aria-pressed={enabled}
        >
          {enabled ? 'ON' : 'OFF'}
        </button>
      </div>

      <label className="text-xs text-onSurface/60 mb-1.5 block">도구</label>
      <div className="grid grid-cols-5 gap-1 mb-3">
        {TOOL_BUTTONS.map((b) => (
          <button
            key={b.value}
            type="button"
            onClick={() => {
              setTool(b.value)
              if (!enabled) setEnabled(true)
            }}
            className={`flex flex-col items-center justify-center gap-1 py-2 rounded-md border transition-colors ${
              tool === b.value && enabled
                ? 'bg-primary text-onPrimary border-primary'
                : 'bg-primaryContainer/40 text-onSurface/70 border-transparent hover:bg-primaryContainer/70'
            }`}
            aria-pressed={tool === b.value}
            aria-label={b.label}
          >
            {b.icon}
            <span className="text-[10px] font-medium">{b.label}</span>
          </button>
        ))}
        {/* 전체 지우기 — 1회성 액션 (선택 상태 없음). 다른 미선택 도구 버튼과 동일 톤. */}
        <button
          type="button"
          onClick={onClearAll}
          className="flex flex-col items-center justify-center gap-1 py-2 rounded-md border border-transparent bg-primaryContainer/40 text-onSurface/70 hover:bg-primaryContainer/70 transition-colors"
          aria-label="현재 페이지 전체 지우기"
          title="현재 페이지의 모든 필기 삭제"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M1 7h22M9 7V4a1 1 0 011-1h4a1 1 0 011 1v3" />
          </svg>
          <span className="text-[10px] font-medium leading-tight whitespace-nowrap">전체삭제</span>
        </button>
      </div>

      <label
        className={`text-xs mb-1.5 block ${
          tool === 'eraser' ? 'text-onSurface/30' : 'text-onSurface/60'
        }`}
      >
        색상
      </label>
      <div className="grid grid-cols-6 gap-1.5">
        {palette.map((c) => (
          <button
            key={c}
            type="button"
            disabled={tool === 'eraser'}
            onClick={() => {
              setColor(c)
              if (!enabled) setEnabled(true)
            }}
            className={`w-full aspect-square rounded-full border-2 transition-transform hover:scale-110 ${
              color === c
                ? 'border-onSurface ring-2 ring-offset-1 ring-onSurface/30'
                : 'border-transparent'
            } ${tool === 'eraser' ? 'opacity-30 cursor-not-allowed hover:scale-100' : ''}`}
            style={{ backgroundColor: c }}
            aria-label={`Color ${c}`}
          />
        ))}
      </div>
      {/* 커스텀 색상 피커 — 6색 외에 자유 선택 */}
      <input
        type="color"
        value={color}
        disabled={tool === 'eraser'}
        onChange={(e) => {
          setColor(e.target.value)
          if (!enabled) setEnabled(true)
        }}
        className={`w-full h-8 rounded mt-2 border border-primaryContainer ${
          tool === 'eraser' ? 'opacity-30 cursor-not-allowed' : 'cursor-pointer'
        }`}
        aria-label="필기 색상 직접 선택"
      />
    </div>
  )
}

export default DrawingToolbar
