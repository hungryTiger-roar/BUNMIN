interface MicButtonProps {
  isOn: boolean
  onClick: () => void
  disabled?: boolean
  size?: 'sm' | 'md' | 'lg'
}

function MicButton({ isOn, onClick, disabled, size = 'md' }: MicButtonProps) {
  const sizeClass = {
    sm: 'w-14 h-14',
    md: 'w-20 h-20',
    lg: 'w-24 h-24',
  }[size]
  const iconSize = {
    sm: 'w-6 h-6',
    md: 'w-8 h-8',
    lg: 'w-10 h-10',
  }[size]

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`group relative ${sizeClass} rounded-full flex items-center justify-center transition-all ${
        isOn
          ? 'bg-white shadow-lg shadow-emerald-400/40'
          : 'bg-slate-300 hover:bg-slate-400'
      } ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
      aria-label={isOn ? 'Microphone on' : 'Microphone off'}
      aria-pressed={isOn}
    >
      {/* 초록색 링 (on일 때만) */}
      {isOn && (
        <>
          <span className="absolute inset-0 rounded-full ring-[3px] ring-emerald-500" />
          <span className="absolute inset-0 rounded-full ring-[3px] ring-emerald-400 animate-ping opacity-60" />
        </>
      )}

      {/* 마이크 아이콘 */}
      {isOn ? (
        <svg className={`${iconSize} text-slate-700 relative`} fill="currentColor" viewBox="0 0 24 24">
          <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z" />
        </svg>
      ) : (
        <svg className={`${iconSize} text-slate-500 relative`} fill="currentColor" viewBox="0 0 24 24">
          <path d="M19 11h-1.7c0 .74-.16 1.43-.43 2.05l1.23 1.23c.56-.98.9-2.09.9-3.28zM14.98 11.17c0-.06.02-.11.02-.17V5c0-1.66-1.34-3-3-3S9 3.34 9 5v.18l5.98 5.99zM4.27 3L3 4.27l6.01 6.01V11c0 1.66 1.33 3 2.99 3 .22 0 .44-.03.65-.08l1.66 1.66c-.71.33-1.5.52-2.31.52-2.76 0-5.3-2.1-5.3-5.1H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c.91-.13 1.77-.45 2.54-.9L19.73 21 21 19.73 4.27 3z" />
        </svg>
      )}
    </button>
  )
}

export default MicButton
