import type { Participants } from '@/stores/lectureStore'

interface ParticipantsPanelProps {
  participants: Participants
  fallbackStudentCount?: number
  onClose: () => void
  variant?: 'dark' | 'light'
}

function ParticipantsPanel({
  participants,
  fallbackStudentCount = 0,
  onClose,
  variant = 'dark',
}: ParticipantsPanelProps) {
  const studentList = participants.students
  const showFallback = studentList.length === 0 && fallbackStudentCount > 0

  const isDark = variant === 'dark'
  const panelBg = isDark ? 'bg-overlaySurface' : 'bg-white'
  const headerBorder = isDark ? 'border-overlayBorder/50' : 'border-slate-100'
  const textPrimary = isDark ? 'text-onOverlaySurface' : 'text-slate-700'
  const textMuted = isDark ? 'text-onOverlaySurface/70' : 'text-slate-500'
  const rowHover = isDark ? 'hover:bg-white/5' : 'hover:bg-black/5'
  const lecturerBg = isDark ? 'bg-white/5' : 'bg-purple-50'
  const lecturerIconBg = isDark ? 'bg-gradientPurple/30' : 'bg-purple-100'
  const lecturerIconColor = isDark ? 'text-gradientPurple' : 'text-purple-600'
  const studentIconBg = isDark ? 'bg-primary/30' : 'bg-blue-50'
  const studentIconColor = isDark ? 'text-onOverlaySurface' : 'text-blue-600'
  const closeHover = isDark ? 'hover:bg-white/10' : 'hover:bg-black/5'

  return (
    <div className={`absolute inset-0 z-20 flex flex-col ${panelBg}`}>
      <div className={`px-4 py-3 flex items-center justify-between border-b ${headerBorder} flex-shrink-0`}>
        <h3 className={`font-medium ${textPrimary}`}>Participants</h3>
        <button
          onClick={onClose}
          className={`w-7 h-7 flex items-center justify-center rounded-full ${textMuted} ${closeHover} transition-colors`}
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-1 min-h-0">
        {participants.lecturer && (
          <div className={`flex items-center gap-3 px-3 py-2 rounded-lg ${lecturerBg}`}>
            <div className={`w-9 h-9 rounded-full ${lecturerIconBg} flex items-center justify-center ${lecturerIconColor}`}>
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 14l9-5-9-5-9 5 9 5zm0 0l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14z" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <div className={`font-medium truncate ${textPrimary}`}>
                {participants.lecturer.name || 'professor'}
              </div>
            </div>
            {participants.lecturer.connected && (
              <span className="w-2 h-2 rounded-full bg-green-500" />
            )}
          </div>
        )}
        {studentList.map((s) => (
          <div
            key={s.id}
            className={`flex items-center gap-3 px-3 py-2 rounded-lg ${rowHover}`}
          >
            <div className={`w-9 h-9 rounded-full ${studentIconBg} flex items-center justify-center text-sm font-semibold ${studentIconColor} uppercase`}>
              {(s.name || '?').charAt(0)}
            </div>
            <div className="flex-1 min-w-0">
              <div className={`font-medium truncate ${textPrimary}`}>
                {s.name || 'Guest'}
              </div>
            </div>
            <span className="w-2 h-2 rounded-full bg-green-500" />
          </div>
        ))}
        {showFallback && (
          <div className={`text-sm text-center py-4 ${textMuted}`}>
            {fallbackStudentCount} connected (loading names...)
          </div>
        )}
        {!participants.lecturer && studentList.length === 0 && !showFallback && (
          <div className={`text-sm text-center py-8 ${textMuted}`}>
            No participants
          </div>
        )}
      </div>
    </div>
  )
}

export default ParticipantsPanel
