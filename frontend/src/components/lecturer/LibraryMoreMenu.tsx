import { useEffect, useRef, useState } from 'react'

interface Props {
  onSelectDelete: () => void
}

export default function LibraryMoreMenu({ onSelectDelete }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="더보기"
        onClick={() => setOpen((o) => !o)}
        className="p-1.5 text-onSurface/60 hover:bg-primaryContainer/40 rounded transition-colors"
      >
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
          <circle cx="12" cy="5" r="1.5" />
          <circle cx="12" cy="12" r="1.5" />
          <circle cx="12" cy="19" r="1.5" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-32 bg-surface border border-primaryContainer rounded-lg shadow-md z-10 overflow-hidden">
          <button
            type="button"
            onClick={() => {
              setOpen(false)
              onSelectDelete()
            }}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-onSurface hover:bg-primaryContainer/40 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            삭제
          </button>
        </div>
      )}
    </div>
  )
}
