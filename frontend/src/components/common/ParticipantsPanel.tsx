import type { Participants } from '@/stores/lectureStore'
import { usePreferencesStore } from '@/stores/preferencesStore'

interface ParticipantsPanelProps {
  participants: Participants
  fallbackStudentCount?: number
  onClose?: () => void
  locale?: 'en' | 'ko'
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
  locale = 'en',
}: ParticipantsPanelProps) {
  const theme = usePreferencesStore((s) => s.theme)
  const c = THEME_COLORS[theme]
  const studentList = participants.students
  const showFallback = studentList.length === 0 && fallbackStudentCount > 0

  const t = locale === 'ko'
    ? {
        title: '참가자 목록',
        close: '닫기',
        professorFallback: '교수',
        guestFallback: '게스트',
        loadingNames: (n: number) => `${n}명 접속 중 (이름 로딩 중...)`,
        noParticipants: '참가자가 없습니다',
      }
    : {
        title: 'Participants',
        close: 'Close',
        professorFallback: 'professor',
        guestFallback: 'Guest',
        loadingNames: (n: number) => `${n} connected (loading names...)`,
        noParticipants: 'No participants',
      }

  // When onClose is provided, render as overlay (backward compat for Lecturer)
  // When not provided, render as pure list component (for Student tabs)
  const wrapperClass = onClose
    ? `absolute inset-0 z-20 flex flex-col ${c.panelBg}`
    : `flex flex-col h-full min-h-0 ${c.panelBg}`

  return (
    <div className={wrapperClass}>
      {/* Header with close button - only shown when onClose is provided */}
      {onClose && (
        <div className={`px-5 py-4 flex items-center justify-between border-b ${c.headerBorder} flex-shrink-0`}>
          <h3 className={`text-2xl font-medium ${c.textPrimary}`}>{t.title}</h3>
          <button
            onClick={onClose}
            className={`w-10 h-10 flex items-center justify-center rounded-full text-2xl ${c.textMuted} ${c.closeHover} transition-colors`}
            aria-label={t.close}
          >
            ✕
          </button>
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-4 space-y-2 min-h-0">
        {participants.lecturer && (
          <div className={`flex items-center gap-4 px-4 py-4 rounded-lg ${c.lecturerBg}`}>
            <div className={`w-14 h-14 rounded-full ${c.iconBg} flex items-center justify-center ${c.iconColor}`}>
              <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 14l9-5-9-5-9 5 9 5zm0 0l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14z" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <div className={`text-2xl font-medium truncate ${c.textPrimary}`}>
                {participants.lecturer.name || t.professorFallback}
              </div>
            </div>
            {participants.lecturer.connected && (
              <span className="w-4 h-4 rounded-full bg-green-500" />
            )}
          </div>
        )}
        {studentList.map((s) => (
          <div
            key={s.id}
            className={`flex items-center gap-4 px-4 py-4 rounded-lg ${c.rowHover}`}
          >
            <div className={`w-14 h-14 rounded-full ${c.iconBg} flex items-center justify-center text-2xl font-semibold ${c.iconColor} uppercase`}>
              {(s.name || '?').charAt(0)}
            </div>
            <div className="flex-1 min-w-0">
              <div className={`text-2xl font-medium truncate ${c.textPrimary}`}>
                {s.name || t.guestFallback}
              </div>
            </div>
            <span className="w-4 h-4 rounded-full bg-green-500" />
          </div>
        ))}
        {showFallback && (
          <div className={`text-2xl text-center py-6 ${c.textMuted}`}>
            {t.loadingNames(fallbackStudentCount)}
          </div>
        )}
        {!participants.lecturer && studentList.length === 0 && !showFallback && (
          <div className={`text-2xl text-center py-10 ${c.textMuted}`}>
            {t.noParticipants}
          </div>
        )}
      </div>
    </div>
  )
}

export default ParticipantsPanel
