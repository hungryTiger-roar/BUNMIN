import type { Participants } from '@/stores/lectureStore'
import { usePreferencesStore } from '@/stores/preferencesStore'

interface ParticipantsPanelProps {
  participants: Participants
  fallbackStudentCount?: number
  onClose: () => void
}

const THEME_COLORS = {
  light: {
    panelBg: 'bg-white',
    headerBorder: 'border-slate-100',
    textPrimary: 'text-slate-700',
    textMuted: 'text-slate-500',
    rowHover: 'hover:bg-black/5',
    lecturerBg: 'bg-purple-50',
    iconBg: 'bg-purple-100',
    iconColor: 'text-purple-600',
    closeHover: 'hover:bg-black/5',
  },
  dark: {
    panelBg: 'bg-overlaySurface',
    headerBorder: 'border-overlayBorder/50',
    textPrimary: 'text-onOverlaySurface',
    textMuted: 'text-onOverlaySurface/70',
    rowHover: 'hover:bg-white/5',
    lecturerBg: 'bg-white/5',
    iconBg: 'bg-primary/30',
    iconColor: 'text-onOverlaySurface',
    closeHover: 'hover:bg-white/10',
  },
  gradient: {
    panelBg: 'bg-[#E0DEF7]',
    headerBorder: 'border-white/40',
    textPrimary: 'text-slate-700',
    textMuted: 'text-slate-500',
    rowHover: 'hover:bg-white/40',
    lecturerBg: 'bg-white/50',
    iconBg: 'bg-white/70',
    iconColor: 'text-purple-600',
    closeHover: 'hover:bg-white/40',
  },
} as const

function ParticipantsPanel({
  participants,
  fallbackStudentCount = 0,
  onClose,
}: ParticipantsPanelProps) {
  const theme = usePreferencesStore((s) => s.theme)
  const c = THEME_COLORS[theme]
  const studentList = participants.students
  const showFallback = studentList.length === 0 && fallbackStudentCount > 0

  return (
    <div className={`absolute inset-0 z-20 flex flex-col ${c.panelBg}`}>
      <div className={`px-4 py-3 flex items-center justify-between border-b ${c.headerBorder} flex-shrink-0`}>
        <h3 className={`font-medium ${c.textPrimary}`}>Participants</h3>
        <button
          onClick={onClose}
          className={`w-7 h-7 flex items-center justify-center rounded-full ${c.textMuted} ${c.closeHover} transition-colors`}
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-1 min-h-0">
        {participants.lecturer && (
          <div className={`flex items-center gap-3 px-3 py-2 rounded-lg ${c.lecturerBg}`}>
            <div className={`w-9 h-9 rounded-full ${c.iconBg} flex items-center justify-center ${c.iconColor}`}>
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 14l9-5-9-5-9 5 9 5zm0 0l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14z" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <div className={`font-medium truncate ${c.textPrimary}`}>
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
            className={`flex items-center gap-3 px-3 py-2 rounded-lg ${c.rowHover}`}
          >
            <div className={`w-9 h-9 rounded-full ${c.iconBg} flex items-center justify-center text-sm font-semibold ${c.iconColor} uppercase`}>
              {(s.name || '?').charAt(0)}
            </div>
            <div className="flex-1 min-w-0">
              <div className={`font-medium truncate ${c.textPrimary}`}>
                {s.name || 'Guest'}
              </div>
            </div>
            <span className="w-2 h-2 rounded-full bg-green-500" />
          </div>
        ))}
        {showFallback && (
          <div className={`text-sm text-center py-4 ${c.textMuted}`}>
            {fallbackStudentCount} connected (loading names...)
          </div>
        )}
        {!participants.lecturer && studentList.length === 0 && !showFallback && (
          <div className={`text-sm text-center py-8 ${c.textMuted}`}>
            No participants
          </div>
        )}
      </div>
    </div>
  )
}

export default ParticipantsPanel
