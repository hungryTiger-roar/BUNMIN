import { useEffect } from 'react'

interface MobileBottomSheetProps {
  isOpen: boolean
  onClose: () => void
  children: React.ReactNode
}

function MobileBottomSheet({ isOpen, onClose, children }: MobileBottomSheetProps) {
  // Close on ESC key
  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  return (
    <>
      {/* Backdrop - z-50 */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-50"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Sheet - z-60 */}
      <div
        role="dialog"
        aria-modal={isOpen ? 'true' : undefined}
        aria-hidden={!isOpen}
        aria-label="Lecture panel"
        className={`
          mobile-bottom-sheet
          fixed left-0 right-0 bottom-0 z-60
          flex flex-col
          bg-surface rounded-t-2xl shadow-2xl
          transition-transform duration-300 ease-out
          ${isOpen
            ? 'translate-y-0 pointer-events-auto'
            : 'translate-y-full pointer-events-none'}
        `}
        style={{
          height: 'min(calc(var(--app-height, 100dvh) * 0.5), 400px)',
        }}
      >
        {/* Drag handle */}
        <div className="flex justify-center py-3 shrink-0">
          <div className="w-10 h-1 bg-onSurface/30 rounded-full" />
        </div>

        {/* Content - safe-area padding applied via CSS */}
        <div className="mobile-bottom-sheet-content flex-1 min-h-0 overflow-hidden">
          {children}
        </div>
      </div>
    </>
  )
}

export default MobileBottomSheet
