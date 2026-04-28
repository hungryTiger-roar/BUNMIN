import { useEffect, useState, useRef, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { useLectureStore } from '@/stores/lectureStore'
import {
  usePreferencesStore,
  type TranslationLang,
  type SubtitleStyle,
  type AspectRatio,
} from '@/stores/preferencesStore'
import { useWebSocket } from '@/hooks/useWebSocket'
import ConnectionStatus from '@/components/common/ConnectionStatus'
import ParticipantsPanel from '@/components/common/ParticipantsPanel'
import { WS_PIPELINE_URL, API_BASE } from '@/lib/api'

const LANG_OPTIONS: { value: TranslationLang; label: string }[] = [
  { value: 'off', label: 'Off' },
  { value: 'ko', label: '한국어 (Korean)' },
  { value: 'en', label: '영어 (English)' },
  { value: 'de', label: '독일어 (Deutsch)' },
  { value: 'es', label: '스페인어 (Español)' },
  { value: 'ru', label: '러시아어 (Русский)' },
]

const AUDIO_LANG_OPTIONS = LANG_OPTIONS
const SUBTITLE_LANG_OPTIONS = LANG_OPTIONS

const STYLE_LABEL: Record<SubtitleStyle, string> = {
  plain: '기본',
  outline: '테두리',
  glow: '글로우',
}

const ASPECT_OPTIONS: { value: AspectRatio; label: string; className: string }[] = [
  { value: '16/9', label: '16:9', className: 'aspect-[16/9]' },
  { value: '4/3', label: '4:3', className: 'aspect-[4/3]' },
  { value: '5/3', label: '5:3', className: 'aspect-[5/3]' },
]

interface MaterialItem {
  slide_id: string
  filename: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  total_pages: number
  has_translated: boolean
}

function subtitleStyleToCss(style: SubtitleStyle): CSSProperties {
  switch (style) {
    case 'outline':
      // 또렷한 2px 검정 외곽선 — 8방향 shadow로 fill 굵기 손상 없이
      return {
        textShadow: [
          '-2px -2px 0 #000',
          '0 -2px 0 #000',
          '2px -2px 0 #000',
          '2px 0 0 #000',
          '2px 2px 0 #000',
          '0 2px 0 #000',
          '-2px 2px 0 #000',
          '-2px 0 0 #000',
          '-1px -1px 0 #000',
          '1px -1px 0 #000',
          '-1px 1px 0 #000',
          '1px 1px 0 #000',
        ].join(', '),
      }
    case 'glow':
      // 순수 하얀 빛 할로 — 단계적 블러 레이어
      return {
        textShadow: [
          '0 0 8px rgba(0,0,0,0.8)',
          '0 0 8px rgba(255, 255, 255, 0.95)',
          '0 0 16px rgba(255, 255, 255, 0.75)',
          '0 0 28px rgba(255, 255, 255, 0.5)',
          '0 0 40px rgba(255, 255, 255, 0.35)',
        ].join(', '),
      }
    default:
      return { color: 'black' }
  }
}

function Student() {
  const navigate = useNavigate()
  const slideRef = useRef<HTMLDivElement>(null)
  const chatScrollRef = useRef<HTMLDivElement>(null)
  const chatInputRef = useRef<HTMLInputElement>(null)

  const {
    slideStatus,
    currentPage,
    totalPages,
    slidePages,
    isLectureStarted,
    isPaused,
    presentationMode,
    currentScreen,
    isSubtitleOn,
    subtitles,
    studentName,
    studentCount,
    chatMessages,
    participants,
    lectureTitle,
    slideFilename,
    sessionId,
  } = useLectureStore()

  const displayTitle =
    lectureTitle.trim() ||
    slideFilename.replace(/\.pdf$/i, '').trim() ||
    ''

  const {
    subtitleSettings,
    setSubtitleSettings,
    audioLang,
    subtitleLang,
    secondarySubtitleLang,
    setAudioLang,
    setSubtitleLang,
    setSecondarySubtitleLang,
    aspectRatio,
    setAspectRatio,
    theme,
    toggleTheme,
  } = usePreferencesStore()

  const { isConnected, connect, sendChat } = useWebSocket(WS_PIPELINE_URL, 'student')

  const [isFullscreen, setIsFullscreen] = useState(false)
  const [volume, setVolume] = useState(70)
  const [isMuted, setIsMuted] = useState(false)
  const [chatInput, setChatInput] = useState('')
  const [showSubtitleSettings, setShowSubtitleSettings] = useState(false)
  const [showLangPanel, setShowLangPanel] = useState(false)
  const [showParticipants, setShowParticipants] = useState(false)
  const [materials, setMaterials] = useState<MaterialItem[]>([])
  const [showTranscriptModal, setShowTranscriptModal] = useState(false)

  useEffect(() => {
    if (sessionId) setShowTranscriptModal(true)
  }, [sessionId])

  useEffect(() => {
    let cancelled = false
    const fetchMaterials = async () => {
      try {
        const res = await fetch(`${API_BASE}/slides/list`)
        if (!res.ok) return
        const data = await res.json()
        if (!cancelled) {
          setMaterials(Array.isArray(data.items) ? data.items : [])
        }
      } catch {
        /* ignore */
      }
    }
    fetchMaterials()
    const interval = setInterval(fetchMaterials, 10000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  useEffect(() => {
    connect()
  }, [connect])

  useEffect(() => {
    const handle = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', handle)
    return () => document.removeEventListener('fullscreenchange', handle)
  }, [])

  useEffect(() => {
    chatScrollRef.current?.scrollTo({
      top: chatScrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [chatMessages.length])

  const toggleFullscreen = () => {
    if (!document.fullscreenElement && slideRef.current) {
      slideRef.current.requestFullscreen().catch(() => {})
    } else if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {})
    }
  }

  const handleChatSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = chatInput.trim()
    if (!trimmed) return
    sendChat(trimmed)
    setChatInput('')
    // 커서 유지
    requestAnimationFrame(() => chatInputRef.current?.focus())
  }

  const handleExit = () => {
    navigate('/')
  }

  const currentSlideImage = slidePages[currentPage - 1]?.imageUrl
  const slideImageUrl = currentSlideImage
    ? `${API_BASE}${currentSlideImage}`
    : null

  const latestSubtitle = subtitles[subtitles.length - 1]
  const primaryText = !latestSubtitle || subtitleLang === 'off' ? null
    : subtitleLang === 'ko' ? latestSubtitle.original
    : latestSubtitle.translated
  const secondaryText = !latestSubtitle || secondarySubtitleLang === 'off' ? null
    : secondarySubtitleLang === 'ko' ? latestSubtitle.original
    : latestSubtitle.translated
  const effectiveVolume = isMuted ? 0 : volume

  const participantTotal =
    (participants.lecturer?.connected ? 1 : 0) + participants.students.length
  const displayParticipantCount = Math.max(participantTotal, studentCount + 1)

  const aspectClass =
    ASPECT_OPTIONS.find((a) => a.value === aspectRatio)?.className ?? 'aspect-[4/3]'

  return (
    <div className="h-screen overflow-hidden flex flex-col bg-background text-onBackground">
      {/* 자막 다운로드 모달 */}
      {showTranscriptModal && sessionId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-surface rounded-2xl shadow-2xl p-6 w-[min(90%,400px)] flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-onSurface">강의 자막 저장</h2>
              <button
                type="button"
                onClick={() => setShowTranscriptModal(false)}
                className="w-7 h-7 rounded-full flex items-center justify-center text-onSurface/60 hover:bg-black/10 transition-colors"
              >✕</button>
            </div>
            <p className="text-sm text-onSurface/70">강의 중 인식된 자막을 파일로 다운로드합니다.</p>
            <div className="flex flex-col gap-2">
              <a
                href={`${API_BASE}/transcripts/${sessionId}/download?format=txt`}
                download
                className="flex items-center justify-center gap-2 w-full py-3 rounded-xl bg-primary text-onPrimary font-medium hover:opacity-90 transition-opacity"
              >
                <span>📄</span> TXT 다운로드
              </a>
              <a
                href={`${API_BASE}/transcripts/${sessionId}/download?format=srt`}
                download
                className="flex items-center justify-center gap-2 w-full py-3 rounded-xl bg-primaryContainer text-onPrimaryContainer font-medium hover:opacity-90 transition-opacity"
              >
                <span>🎬</span> SRT 다운로드
              </a>
            </div>
          </div>
        </div>
      )}

      {/* 헤더 */}
      <header className="flex items-center justify-between gap-3 px-4 py-3 border-b border-primaryContainer bg-surface backdrop-blur-md shadow-sm flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <h1 className="text-lg font-special-gothic tracking-wide">Aunion AI</h1>
          <ConnectionStatus isConnected={isConnected} />
          {isLectureStarted && (
            <span className="flex items-center gap-1.5 px-2.5 py-1 bg-error text-white text-xs font-semibold rounded-full shadow-lg shadow-error/30">
              <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse" />
              LIVE
            </span>
          )}
          {isPaused && (
            <span className="px-2.5 py-1 bg-yellow-500/80 text-white text-xs font-semibold rounded-full">
              일시정지
            </span>
          )}
          {slideStatus === 'ready' && totalPages > 0 && (
            <div className="flex items-center gap-1.5 px-3 py-1 bg-primaryContainer/60 rounded-full text-sm text-onSurface">
              <span className="font-medium">{currentPage}</span>
              <span className="opacity-60">/</span>
              <span className="opacity-60">{totalPages}</span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* 라이트 / 다크 / 그라데이션 3-모드 토글 */}
          <button
            type="button"
            onClick={toggleTheme}
            className="flex items-center justify-center w-9 h-9 rounded-lg transition-colors bg-primaryContainer/60 hover:bg-primaryContainer text-onSurface"
            aria-label={`Current: ${theme} mode (click to cycle)`}
            title={`${
              theme === 'light' ? 'Light' : theme === 'dark' ? 'Dark' : 'Gradient'
            } mode — click to cycle`}
          >
            {theme === 'light' ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
            ) : theme === 'dark' ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
              </svg>
            )}
          </button>

          <button
            onClick={() => setShowParticipants((v) => !v)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${
              showParticipants
                ? 'bg-primary text-onPrimary'
                : 'bg-primaryContainer/60 hover:bg-primaryContainer text-onSurface'
            }`}
            title="참여자 목록"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <span>{displayParticipantCount}</span>
          </button>

          {studentName && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-primaryContainer/60 rounded-lg text-sm text-onSurface">
              <svg className="w-4 h-4 opacity-70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
              {studentName}
            </div>
          )}

          <button
            onClick={handleExit}
            className="px-3 py-1.5 bg-primaryContainer/60 hover:bg-primaryContainer text-onSurface rounded-lg text-sm"
          >
            Leave
          </button>
        </div>
      </header>

      {/* 메인: 화면 + 채팅 */}
      <main className="flex-1 flex gap-4 px-4 py-4 overflow-hidden min-h-0">
        <div className="flex-1 flex items-center justify-center min-w-0 min-h-0">
          <div
            ref={slideRef}
            className={`group relative bg-black rounded-xl overflow-hidden shadow-2xl h-full ${aspectClass} max-w-full`}
          >
            {/* 상단 강의 제목 바 — 마우스 올렸을 때만 표시 */}
            {displayTitle && (
              <div className="absolute top-0 left-0 right-0 z-30 px-4 py-3 bg-gradient-to-b from-black/70 to-transparent opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity duration-200">
                <h2 className="text-white font-medium text-lg drop-shadow truncate">
                  {displayTitle}
                </h2>
              </div>
            )}

            {/* 일시정지 오버레이 */}
            {isPaused && isLectureStarted && (
              <div className="absolute inset-0 bg-black/85 flex items-center justify-center z-20">
                <div className="text-center text-white">
                  <svg className="w-16 h-16 mx-auto mb-4 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <p className="text-xl font-medium">Paused — will resume shortly</p>
                  <p className="text-sm mt-2 opacity-70">The lecturer has paused the lecture</p>
                </div>
              </div>
            )}

            {/* 슬라이드/화면공유 */}
            {presentationMode === 'screen' && currentScreen ? (
              <img
                src={`data:image/jpeg;base64,${currentScreen}`}
                alt="화면 공유"
                className="w-full h-full object-contain"
              />
            ) : slideStatus === 'ready' && slideImageUrl ? (
              <img
                key={`${currentPage}`}
                src={slideImageUrl}
                alt={`슬라이드 ${currentPage}`}
                className="w-full h-full object-contain"
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center text-white/50">
                <div className="text-center">
                  {!isConnected ? (
                    <>
                      <svg className="w-16 h-16 mx-auto mb-4 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M18.364 5.636a9 9 0 010 12.728M15.536 8.464a5 5 0 010 7.072" />
                      </svg>
                      <p className="text-lg">Connecting to server...</p>
                    </>
                  ) : !isLectureStarted ? (
                    <>
                      <svg className="w-16 h-16 mx-auto mb-4 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      <p className="text-lg">Waiting for the lecture to start...</p>
                    </>
                  ) : (
                    <>
                      <svg className="w-16 h-16 mx-auto mb-4 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      <p className="text-lg">Loading lecture material...</p>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* 자막 오버레이 */}
            {isSubtitleOn && (primaryText || secondaryText) && (
              <div
                className={`absolute left-1/2 -translate-x-1/2 max-w-[90%] px-4 text-center text-white pointer-events-none z-10 ${
                  subtitleSettings.position === 'top' ? 'top-6' : 'bottom-20'
                }`}
                style={{
                  fontSize: `${subtitleSettings.fontSize}px`,
                  opacity: subtitleSettings.opacity,
                  ...subtitleStyleToCss(subtitleSettings.style),
                }}
              >
                {primaryText && <p className="font-medium leading-snug">{primaryText}</p>}
                {secondaryText && (
                  <p
                    className="mt-1 leading-snug opacity-80"
                    style={{ fontSize: `${Math.max(12, subtitleSettings.fontSize - 4)}px` }}
                  >
                    {secondaryText}
                  </p>
                )}
              </div>
            )}

            {/* 화면 내부 하단 컨트롤 바 — 마우스 올렸을 때만 표시 */}
            <div className="absolute left-3 right-3 bottom-3 z-30 flex items-center gap-2 flex-wrap opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto transition-opacity duration-200">
              {/* 볼륨 — 스피커 아이콘에 마우스 올리면 슬라이더 표시 */}
              <div className="group/vol flex items-center bg-black/60 backdrop-blur-sm rounded-full pl-2 pr-2 py-1.5 group-hover/vol:pr-3 transition-all">
                <button
                  type="button"
                  onClick={() => setIsMuted(!isMuted)}
                  className="text-white hover:opacity-80"
                  aria-label={isMuted ? '음소거 해제' : '음소거'}
                >
                  {isMuted || volume === 0 ? (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" />
                    </svg>
                  ) : (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                    </svg>
                  )}
                </button>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={5}
                  value={effectiveVolume}
                  onChange={(e) => {
                    const v = Number(e.target.value)
                    setVolume(v)
                    if (v > 0) setIsMuted(false)
                  }}
                  className="w-0 opacity-0 ml-0 group-hover/vol:w-24 group-hover/vol:opacity-100 group-hover/vol:ml-2 accent-primary transition-all"
                  aria-label="볼륨"
                />
              </div>

              <div className="flex-1" />

              {/* 화면 비율 */}
              <div className="flex bg-black/60 backdrop-blur-sm rounded-full p-1">
                {ASPECT_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setAspectRatio(opt.value)}
                    className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-colors ${
                      aspectRatio === opt.value
                        ? 'bg-white text-gray-900'
                        : 'text-white/80 hover:text-white'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>

              {/* 언어 팝업 */}
              <button
                type="button"
                onClick={() => {
                  setShowLangPanel((v) => !v)
                  setShowSubtitleSettings(false)
                }}
                className={`p-2 rounded-lg transition-colors ${
                  showLangPanel ? 'bg-white text-gray-900' : 'bg-black/60 text-white hover:bg-black/80'
                }`}
                aria-label="언어 선택"
                title="언어 선택"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
                </svg>
              </button>

              {/* 자막 커스텀 */}
              <button
                type="button"
                onClick={() => {
                  setShowSubtitleSettings((v) => !v)
                  setShowLangPanel(false)
                }}
                className={`p-2 rounded-lg transition-colors ${
                  showSubtitleSettings ? 'bg-white text-gray-900' : 'bg-black/60 text-white hover:bg-black/80'
                }`}
                aria-label="자막 설정"
                title="자막 설정"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z" />
                </svg>
              </button>

              {/* 전체화면 */}
              <button
                type="button"
                onClick={toggleFullscreen}
                className="p-2 bg-black/60 text-white rounded-lg hover:bg-black/80"
                aria-label={isFullscreen ? '전체화면 종료' : '전체화면'}
                title={isFullscreen ? '전체화면 종료' : '전체화면'}
              >
                {isFullscreen ? (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 9V4.5M9 9H4.5M9 9L3.75 3.75M15 15v4.5M15 15h4.5M15 15l5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M9 15H4.5M9 15v4.5M9 15l-5.25 5.25" />
                  </svg>
                ) : (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-5h-4m4 0v4m0-4l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                  </svg>
                )}
              </button>
            </div>

            {/* 언어 선택 팝업 (화면 내부) */}
            {showLangPanel && (
              <>
                <div
                  className="absolute inset-0 bg-black/40 z-40"
                  onClick={() => setShowLangPanel(false)}
                />
                <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[min(90%,800px)] max-h-[80%] overflow-y-auto bg-black/80 backdrop-blur-md text-white rounded-xl shadow-2xl p-8 grid grid-cols-3 gap-12">
                  <LangColumn
                    title="Audio"
                    value={audioLang}
                    onChange={setAudioLang}
                    options={AUDIO_LANG_OPTIONS}
                  />
                  <LangColumn
                    title="Subtitles"
                    value={subtitleLang}
                    onChange={setSubtitleLang}
                    options={SUBTITLE_LANG_OPTIONS}
                  />
                  <LangColumn
                    title="Secondary Subtitles"
                    value={secondarySubtitleLang}
                    onChange={setSecondarySubtitleLang}
                    options={SUBTITLE_LANG_OPTIONS}
                  />
                  <button
                    type="button"
                    onClick={() => setShowLangPanel(false)}
                    className="absolute top-3 right-3 w-7 h-7 rounded-full flex items-center justify-center text-white/70 hover:text-white hover:bg-white/10"
                    aria-label="닫기"
                  >
                    ✕
                  </button>
                </div>
              </>
            )}

            {/* 자막 설정 팝업 (화면 내부) */}
            {showSubtitleSettings && (
              <>
                <div
                  className="absolute inset-0 bg-black/40 z-40"
                  onClick={() => setShowSubtitleSettings(false)}
                />
                <div className="absolute right-3 bottom-16 z-50 w-72 bg-surface text-onSurface rounded-xl shadow-2xl p-4 border border-black/5">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="font-semibold">자막 설정</h3>
                    <button
                      onClick={() => setShowSubtitleSettings(false)}
                      className="text-onSurface/60 hover:text-onSurface"
                    >
                      ✕
                    </button>
                  </div>

                  <div className="mb-4">
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="text-sm">글자 크기</label>
                      <span className="text-sm text-onSurface/70">{subtitleSettings.fontSize}px</span>
                    </div>
                    <input
                      type="range"
                      min={12}
                      max={36}
                      step={1}
                      value={subtitleSettings.fontSize}
                      onChange={(e) => setSubtitleSettings({ fontSize: Number(e.target.value) })}
                      className="w-full accent-overlaySurface"
                    />
                  </div>

                  <div>
                    <label className="text-sm block mb-1.5">스타일</label>
                    <div className="grid grid-cols-3 gap-2">
                      {(Object.keys(STYLE_LABEL) as SubtitleStyle[]).map((s) => (
                        <button
                          key={s}
                          onClick={() => setSubtitleSettings({ style: s })}
                          className={`py-2 text-sm rounded-lg border transition-colors ${
                            subtitleSettings.style === s
                              ? 'bg-overlaySurface text-onOverlaySurface border-overlaySurface'
                              : 'bg-primaryContainer text-onSurface border-transparent hover:bg-primaryContainer/80'
                          }`}
                        >
                          {STYLE_LABEL[s]}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* 우측 사이드: 강의자료 + 채팅 */}
        <aside className="w-80 flex flex-col gap-3 min-h-0">
          {/* 오늘의 강의 자료 */}
          <div
            className="flex-shrink-0 flex flex-col bg-surface text-onSurface backdrop-blur-md rounded-xl border border-primaryContainer shadow-sm overflow-hidden"
            style={{ maxHeight: '50%' }}
          >
            <div className="px-4 py-3 border-b border-primaryContainer flex items-center gap-2 flex-shrink-0">
              <svg className="w-5 h-5 opacity-80" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <h3 className="font-medium">오늘의 강의 자료</h3>
            </div>
            <div className="flex-1 overflow-y-auto scrollbar-hide p-2 space-y-1 min-h-0">
              {materials.length === 0 ? (
                <div className="text-center text-sm text-onSurface/60 py-6">
                  아직 업로드된 자료가 없습니다
                </div>
              ) : (
                materials.flatMap((m) => {
                  const baseTitle = m.filename.replace(/\.pdf$/i, '')
                  const completed = m.status === 'completed'
                  const variants: { kind: 'original' | 'translated'; enabled: boolean }[] = [
                    { kind: 'original', enabled: completed },
                    { kind: 'translated', enabled: completed && m.has_translated },
                  ]
                  return variants.map(({ kind, enabled }) => {
                    const label = kind === 'original' ? '원본' : '번역본'
                    const displayStatus = completed
                      ? `${m.total_pages}페이지 · ${label}`
                      : m.status === 'processing'
                        ? '처리 중...'
                        : m.status === 'pending'
                          ? '대기 중...'
                          : m.status === 'failed'
                            ? '실패'
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
                        title={enabled ? `${baseTitle} ${label} 다운로드` : '아직 준비되지 않음'}
                      >
                        <svg
                          className="w-4 h-4 flex-shrink-0 text-onSurface/70"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                        </svg>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm truncate">
                            {baseTitle} <span className="text-onSurface/60">({label})</span>
                          </div>
                          <div className="text-[11px] opacity-60">{displayStatus}</div>
                        </div>
                        <svg
                          className="w-4 h-4 flex-shrink-0 text-onSurface/70"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                      </button>
                    )
                  })
                })
              )}
            </div>
          </div>

          {/* 채팅 패널 (참여자 패널이 오버레이로 덮음) */}
          <div className="relative flex-1 flex flex-col bg-surface text-onSurface backdrop-blur-md rounded-xl border border-primaryContainer shadow-sm overflow-hidden min-h-0">
            <div className="px-4 py-3 border-b border-primaryContainer flex items-center gap-2 flex-shrink-0">
              <svg className="w-5 h-5 opacity-80" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
              <h3 className="font-medium">Chat</h3>
            </div>

          <div
            ref={chatScrollRef}
            className="flex-1 overflow-y-auto p-3 space-y-3 min-h-0"
          >
            {chatMessages.length === 0 ? (
              <div className="text-center text-sm text-onSurface/60 mt-8">
                No messages yet
              </div>
            ) : (
              chatMessages.map((msg) => (
                <div key={msg.id}>
                  <div className="flex items-baseline gap-1.5 mb-0.5">
                    <span
                      className={`text-sm font-semibold ${
                        msg.sender === 'lecturer' ? 'text-gradientPurple' : 'text-onSurface'
                      }`}
                    >
                      {msg.name}
                    </span>
                    {msg.sender === 'lecturer' && (
                      <span className="text-[10px] px-1.5 py-0.5 bg-gradientPurple/40 text-white rounded font-medium">
                        Lecturer
                      </span>
                    )}
                  </div>
                  <p
                    className={`text-sm leading-relaxed break-words ${
                      msg.sender === 'lecturer'
                        ? 'text-gradientPurple/95'
                        : 'text-onSurface/90'
                    }`}
                  >
                    {msg.text}
                  </p>
                </div>
              ))
            )}
          </div>

          <form
            onSubmit={handleChatSubmit}
            className="p-3 border-t border-primaryContainer flex gap-2 flex-shrink-0"
          >
            <input
              ref={chatInputRef}
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder={isConnected ? 'Type a message...' : 'Connecting...'}
              disabled={!isConnected}
              className="flex-1 bg-white text-gray-900 placeholder-gray-400 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-onPrimary disabled:opacity-60"
              maxLength={200}
            />
            <button
              type="submit"
              disabled={!chatInput.trim() || !isConnected}
              className="px-3 py-2 bg-primary hover:opacity-90 disabled:opacity-40 text-onPrimary rounded-lg text-sm font-medium transition-opacity"
            >
              Send
            </button>
          </form>

            {/* 참여자 패널 — 채팅창 위에 오버레이 */}
            {showParticipants && (
              <ParticipantsPanel
                participants={participants}
                fallbackStudentCount={studentCount}
                onClose={() => setShowParticipants(false)}
                variant="dark"
              />
            )}
          </div>
        </aside>
      </main>
    </div>
  )
}

interface LangColumnProps {
  title: string
  value: TranslationLang
  onChange: (v: TranslationLang) => void
  options: { value: TranslationLang; label: string }[]
}

function LangColumn({ title, value, onChange, options }: LangColumnProps) {
  return (
    <div>
      <h3 className="text-lg font-semibold mb-4 pl-6">{title}</h3>
      <ul className="space-y-2">
        {options.map((opt) => {
          const selected = value === opt.value
          return (
            <li key={opt.value}>
              <button
                type="button"
                onClick={() => onChange(opt.value)}
                className={`w-full text-left flex items-center gap-2 px-2 py-1.5 rounded-md transition-colors ${
                  selected ? 'text-white' : 'text-white/60 hover:text-white/90 hover:bg-white/5'
                }`}
              >
                <span className={`w-4 text-sm ${selected ? 'opacity-100' : 'opacity-0'}`}>✓</span>
                <span className={selected ? 'font-medium' : ''}>{opt.label}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export default Student
