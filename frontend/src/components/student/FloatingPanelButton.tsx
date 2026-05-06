interface FloatingPanelButtonProps {
  onClick: () => void
  hasUnread?: boolean
}

function FloatingPanelButton({ onClick, hasUnread }: FloatingPanelButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="floating-panel-button"
      aria-label="Open chat panel"
    >
      <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
        />
      </svg>

      {hasUnread && (
        <span className="absolute -top-1 -right-1 w-4 h-4 bg-error rounded-full" />
      )}
    </button>
  )
}

export default FloatingPanelButton
