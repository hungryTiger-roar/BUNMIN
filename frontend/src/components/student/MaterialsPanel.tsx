import { API_BASE } from '@/lib/api'

export interface MaterialItem {
  slide_id: string
  filename: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  total_pages: number
  has_translated: boolean
}

interface MaterialsPanelProps {
  materials: MaterialItem[]
}

const DocumentIcon = ({ className }: { className?: string }) => (
  <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
  </svg>
)

function MaterialsPanel({ materials }: MaterialsPanelProps) {
  if (materials.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center text-lg wide:text-sm text-onSurface/60">
          <DocumentIcon className="w-12 h-12 mx-auto mb-3 opacity-40" />
          <p>No materials uploaded yet.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto p-3 space-y-1">
      {materials.flatMap((m) => {
        const baseTitle = m.filename.replace(/\.pdf$/i, '')
        const completed = m.status === 'completed'
        const variants: { kind: 'original' | 'translated'; enabled: boolean }[] = [
          { kind: 'original', enabled: completed },
          { kind: 'translated', enabled: completed && m.has_translated },
        ]
        return variants.map(({ kind, enabled }) => {
          const label = kind === 'original' ? 'Original' : 'Translated'
          const displayStatus = completed
            ? `${m.total_pages} pages · ${label}`
            : m.status === 'processing'
              ? 'Processing...'
              : m.status === 'pending'
                ? 'Pending...'
                : m.status === 'failed'
                  ? 'Failed'
                  : ''
          const fileTitleParam = encodeURIComponent(baseTitle)
          return (
            <button
              key={`${m.slide_id}-${kind}`}
              type="button"
              disabled={!enabled}
              onClick={() =>
                window.open(
                  `${API_BASE}/slides/download/${m.slide_id}?type=${kind}&title=${fileTitleParam}`,
                  '_blank',
                )
              }
              className={`w-full flex items-center gap-2 px-2 py-2 rounded-lg transition-colors text-left ${
                enabled
                  ? 'hover:bg-primaryContainer/40 cursor-pointer'
                  : 'opacity-60 cursor-not-allowed'
              }`}
              title={enabled ? `Download ${baseTitle} (${label})` : 'Not ready yet'}
            >
              <svg
                className="w-5 h-5 wide:w-4 wide:h-4 flex-shrink-0 text-onSurface/70"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
              </svg>
              <div className="flex-1 min-w-0">
                <div className="text-base wide:text-sm truncate">
                  {baseTitle} <span className="text-onSurface/60">({label})</span>
                </div>
                <div className="text-sm wide:text-[11px] opacity-60">{displayStatus}</div>
              </div>
              <svg
                className="w-5 h-5 wide:w-4 wide:h-4 flex-shrink-0 text-onSurface/70"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
            </button>
          )
        })
      })}
    </div>
  )
}

export default MaterialsPanel
