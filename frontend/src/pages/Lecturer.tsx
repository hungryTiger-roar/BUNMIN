import { useEffect, useCallback, useState, useRef, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { useLectureStore } from '@/stores/lectureStore'
import {
  usePreferencesStore,
  type AspectRatio,
  type SubtitleStyle,
} from '@/stores/preferencesStore'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useAudioCapture } from '@/hooks/useAudioCapture'
import { useScreenCapture } from '@/hooks/useScreenCapture'
import SlideUpload from '@/components/lecturer/SlideUpload'
import SlideViewer from '@/components/lecturer/SlideViewer'
import ParticipantsPanel from '@/components/common/ParticipantsPanel'
import AudioLevelMeter from '@/components/lecturer/AudioLevelMeter'
import MicButton from '@/components/lecturer/MicButton'
import CursorSpotlight from '@/components/lecturer/CursorSpotlight'
import ScreenPickerModal from '@/components/lecturer/ScreenPickerModal'
import { WS_PIPELINE_URL, API_BASE } from '@/lib/api'

const ASPECT_OPTIONS: { value: AspectRatio; label: string; className: string }[] = [
  { value: '16/9', label: '16:9', className: 'aspect-[16/9]' },
  { value: '4/3', label: '4:3', className: 'aspect-[4/3]' },
  { value: '5/3', label: '5:3', className: 'aspect-[5/3]' },
]

const STYLE_LABEL: Record<SubtitleStyle, string> = {
  plain: '기본',
  outline: '테두리',
  glow: '글로우',
}

type LecturerLang = 'off' | 'ko' | 'en' | 'de' | 'es' | 'ru'

const LANG_OPTIONS: { value: LecturerLang; label: string }[] = [
  { value: 'off', label: '끄기 (Off)' },
  { value: 'ko', label: '한국어 (Korean)' },
  { value: 'en', label: '영어 (English)' },
  { value: 'de', label: '독일어 (Deutsch)' },
  { value: 'es', label: '스페인어 (Español)' },
  { value: 'ru', label: '러시아어 (Русский)' },
]

const SPOTLIGHT_PRESETS = [
  '#60A5FA', // sky blue
  '#F472B6', // pink
  '#FBBF24', // amber
  '#34D399', // emerald
  '#A78BFA', // purple
  '#EF4444', // red
]

function subtitleStyleToCss(style: SubtitleStyle): CSSProperties {
  switch (style) {
    case 'outline':
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
        ].join(', '),
      }
    case 'glow':
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
      return { color: 'black'}
  }
}

function Lecturer() {
  const navigate = useNavigate()
  const chatScrollRef = useRef<HTMLDivElement>(null)
  const chatInputRef = useRef<HTMLInputElement>(null)
  const slideBoxRef = useRef<HTMLDivElement>(null)

  const [shareUrl, setShareUrl] = useState('')
  const [copied, setCopied] = useState(false)
  const [chatInput, setChatInput] = useState('')
  const [showParticipants, setShowParticipants] = useState(false)
  const [ccEnabled, setCcEnabled] = useState(true)
  const [settingsPanel, setSettingsPanel] = useState<null | 'main' | 'aspect' | 'language' | 'fontSize' | 'style'>(null)
  const [primaryLang, setPrimaryLang] = useState<LecturerLang>('en')
  const [secondaryLang, setSecondaryLang] = useState<LecturerLang>('ko')
  const [showTranscriptModal, setShowTranscriptModal] = useState(false)
  const [spotlightEnabled, setSpotlightEnabled] = useState(false)
  const [spotlightColor, setSpotlightColor] = useState(SPOTLIGHT_PRESETS[0])
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [isNarrow, setIsNarrow] = useState(() => window.innerWidth < 1000)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [slideBoxWidth, setSlideBoxWidth] = useState<number | undefined>(undefined)

  // 커서 위치 상태 (브라우저 전체 기준 vw/vh 비율, 0~1)
  const [cursorPos, setCursorPos] = useState<{ x: number; y: number } | null>(null)

  const {
    isMicOn,
    isLectureStarted,
    isPaused,
    presentationMode,
    slideId,
    slideStatus,
    currentPage,
    slidePages,
    subtitles,
    modelMode,
    chatMessages,
    participants,
    studentCount,
    lectureTitle,
    slideFilename,
    sessionId,
    setLectureTitle,
    setMicOn,
    setLectureStarted,
    setPaused,
    setPresentationMode,
    setCurrentPage,
    reset,
  } = useLectureStore()

  const {
    aspectRatio,
    setAspectRatio,
    lecturerName,
    setLecturerName,
    subtitleSettings,
    setSubtitleSettings,
    theme,
    toggleTheme,
  } = usePreferencesStore()

  const { isConnected, connect, send, sendChat, sendLectureTitle, sendLecturerName } =
    useWebSocket(WS_PIPELINE_URL, 'lecturer')

  const displayTitle =
    lectureTitle.trim() ||
    slideFilename.replace(/\.pdf$/i, '').trim() ||
    ''

  const aspectClass = ASPECT_OPTIONS.find((a) => a.value === aspectRatio)?.className ?? 'aspect-[4/3]'

  const handleAudioData = useCallback(async (audioBlob: Blob) => {
    const arrayBuffer = await audioBlob.arrayBuffer()
    const base64 = btoa(
      new Uint8Array(arrayBuffer).reduce((data, byte) => data + String.fromCharCode(byte), '')
    )
    send({ type: 'audio', audio: base64, sample_rate: 16000, sentAt: Date.now() })
  }, [send])

  const handleScreenData = useCallback((imageData: string) => {
    if (!isPaused && isConnected) {
      send({ type: 'screen', data: imageData })
    }
  }, [send, isPaused, isConnected])

  const {
    startCapture: startAudioCapture,
    stopCapture: stopAudioCapture,
    analyserRef,
    setGain,
  } = useAudioCapture({ onAudioData: handleAudioData })

  const [micGainPct, setMicGainPct] = useState(100)

  const {
    isCapturing: isScreenSharing,
    startCapture: startScreenCapture,
    stopCapture: stopScreenCapture,
    pickerSources: screenPickerSources,
    selectPickerSource: selectScreenSource,
    cancelPicker: cancelScreenPicker,
  } = useScreenCapture({ onFrame: handleScreenData, frameRate: 2 })

  useEffect(() => {
    connect()
  }, [connect])

  useEffect(() => {
    fetch(`${API_BASE}/network/info`)
      .then((res) => res.json())
      .then((data) => {
        const port = window.location.port || data.port
        setShareUrl(`http://${data.lan_ip}:${port}/#/student/start`)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (slideStatus === 'ready' && slideId && isConnected && presentationMode === 'slide') {
      send({ type: 'slide_select', slide_id: slideId })
    }
  }, [slideStatus, slideId, isConnected, send, presentationMode])

  useEffect(() => {
    chatScrollRef.current?.scrollTo({
      top: chatScrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [chatMessages.length])

  useEffect(() => {
    const handle = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', handle)
    return () => document.removeEventListener('fullscreenchange', handle)
  }, [])

  // 창 너비에 따라 사이드바 자동 접기/펼치기
  useEffect(() => {
    const onResize = () => {
      const narrow = window.innerWidth < 1000
      setIsNarrow(narrow)
      setSidebarOpen(!narrow)
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // 슬라이드 박스 폭을 추적해 하단 바 폭을 맞춤 (aspect ratio 변경 시에도 정확히 정렬)
  useEffect(() => {
    const el = slideBoxRef.current
    if (!el) {
      setSlideBoxWidth(undefined)
      return
    }
    const update = () => {
      setSlideBoxWidth(el.getBoundingClientRect().width)
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(el)
    return () => observer.disconnect()
  }, [presentationMode, slideStatus])

  // 커서 위치 추적 + WebSocket 전송 (슬라이드 영역 기준 상대좌표)
  useEffect(() => {
    if (!spotlightEnabled) {
      setCursorPos(null)
      // 스팟라이트 OFF 시 한 번만 visible:false 전송
      if (isConnected && isLectureStarted) {
        send({ type: 'cursor', x: 0, y: 0, visible: false, color: spotlightColor })
      }
      return
    }

    let currentX = 0
    let currentY = 0
    let isInsideSlide = false
    let rafId: number
    let lastSendTime = 0
    const SEND_INTERVAL = 50 // 20fps

    const handleMove = (e: MouseEvent) => {
      const container = slideBoxRef.current
      if (!container) {
        isInsideSlide = false
        setCursorPos(null)
        return
      }

      const containerRect = container.getBoundingClientRect()

      // 컨테이너 내 이미지 요소 찾기 (object-fit: contain 고려)
      const img = container.querySelector('img') as HTMLImageElement | null
      let imgOffsetX = 0
      let imgOffsetY = 0
      let imgWidth = containerRect.width
      let imgHeight = containerRect.height

      if (img && img.naturalWidth && img.naturalHeight) {
        const imgRatio = img.naturalWidth / img.naturalHeight
        const containerRatio = containerRect.width / containerRect.height

        if (imgRatio > containerRatio) {
          imgWidth = containerRect.width
          imgHeight = containerRect.width / imgRatio
        } else {
          imgHeight = containerRect.height
          imgWidth = containerRect.height * imgRatio
        }
        imgOffsetX = (containerRect.width - imgWidth) / 2
        imgOffsetY = (containerRect.height - imgHeight) / 2
      }

      // 이미지 영역 기준 상대 좌표 (0~1)
      const imgLeft = containerRect.left + imgOffsetX
      const imgTop = containerRect.top + imgOffsetY
      const relX = (e.clientX - imgLeft) / imgWidth
      const relY = (e.clientY - imgTop) / imgHeight

      // 이미지 영역 내부인지 확인
      if (relX >= 0 && relX <= 1 && relY >= 0 && relY <= 1) {
        currentX = relX
        currentY = relY
        isInsideSlide = true
        // 로컬 UI: 브라우저 전체 기준 vw/vh로 표시 (fixed positioning)
        setCursorPos({
          x: e.clientX / window.innerWidth,
          y: e.clientY / window.innerHeight,
        })
      } else {
        isInsideSlide = false
        setCursorPos(null)
      }
    }

    const handleLeave = () => {
      isInsideSlide = false
      setCursorPos(null)
      // 즉시 visible:false 전송
      if (isConnected && isLectureStarted) {
        send({ type: 'cursor', x: 0, y: 0, visible: false, color: spotlightColor })
      }
    }

    // 주기적으로 WebSocket 전송 (RAF 기반)
    const tick = () => {
      const now = Date.now()
      if (isConnected && isLectureStarted && now - lastSendTime >= SEND_INTERVAL) {
        lastSendTime = now
        if (isInsideSlide) {
          // 슬라이드 기준 상대좌표 전송
          send({ type: 'cursor', x: currentX, y: currentY, visible: true, color: spotlightColor })
        } else {
          send({ type: 'cursor', x: 0, y: 0, visible: false, color: spotlightColor })
        }
      }
      rafId = requestAnimationFrame(tick)
    }

    window.addEventListener('mousemove', handleMove)
    document.addEventListener('mouseleave', handleLeave)
    rafId = requestAnimationFrame(tick)

    return () => {
      window.removeEventListener('mousemove', handleMove)
      document.removeEventListener('mouseleave', handleLeave)
      cancelAnimationFrame(rafId)
      // cleanup 시 visible:false 전송
      if (isConnected && isLectureStarted) {
        send({ type: 'cursor', x: 0, y: 0, visible: false, color: spotlightColor })
      }
    }
  }, [spotlightEnabled, spotlightColor, isConnected, isLectureStarted, send])

  const handlePageChange = useCallback((page: number) => {
    if (isConnected && slideId && !isPaused) {
      send({ type: 'page_change', slide_id: slideId, page })
    }
  }, [isConnected, slideId, send, isPaused])

  const toggleMic = async () => {
    if (isMicOn) {
      stopAudioCapture()
      setMicOn(false)
    } else {
      await startAudioCapture()
      setMicOn(true)
    }
  }

  const startLecture = () => {
    if (presentationMode === 'slide' && slideStatus !== 'ready') {
      alert('강의자료를 먼저 업로드하세요.')
      return
    }
    setLectureStarted(true)
    setPaused(false)
    send({ type: 'lecture_start', slide_id: slideId, mode: presentationMode })
  }

  const togglePause = () => {
    const newPaused = !isPaused
    setPaused(newPaused)
    send({ type: newPaused ? 'lecture_pause' : 'lecture_resume' })
  }

  const endLecture = () => {
    stopAudioCapture()
    stopScreenCapture()
    setLectureStarted(false)
    setPaused(false)
    send({ type: 'lecture_end', slide_id: slideId })
    setShowTranscriptModal(true)
  }

  const handleExit = () => {
    stopAudioCapture()
    stopScreenCapture()
    reset()
    navigate('/')
  }

  const handleChatSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = chatInput.trim()
    if (!trimmed) return
    sendChat(trimmed)
    setChatInput('')
    requestAnimationFrame(() => chatInputRef.current?.focus())
  }

  const handleCopyLink = () => {
    if (!shareUrl) return
    navigator.clipboard.writeText(shareUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleDownload = (type: 'original' | 'translated') => {
    if (!slideId) return
    const titleParam = displayTitle.trim()
      ? `&title=${encodeURIComponent(displayTitle.trim())}`
      : ''
    window.open(`${API_BASE}/slides/download/${slideId}?type=${type}${titleParam}`, '_blank')
  }

  const toggleFullscreen = () => {
    if (!document.fullscreenElement && slideBoxRef.current) {
      slideBoxRef.current.requestFullscreen().catch(() => {})
    } else if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {})
    }
  }

  const canStartLecture = isConnected && modelMode !== 'switching' && (
    presentationMode === 'screen' || slideStatus === 'ready'
  )

  const participantTotal =
    (participants.lecturer?.connected ? 1 : 0) + participants.students.length
  const displayParticipantCount = Math.max(participantTotal, studentCount + 1)

  const latestSubtitle = subtitles[subtitles.length - 1]

  // 슬라이드 박스 내부에 공통으로 들어가는 자막 오버레이
  const primaryText = !latestSubtitle || primaryLang === 'off' ? null
    : primaryLang === 'ko' ? latestSubtitle.original
    : latestSubtitle.translated

  const secondaryText = !latestSubtitle || secondaryLang === 'off' ? null
    : secondaryLang === 'ko' ? latestSubtitle.original
    : latestSubtitle.translated

  const subtitleOverlay = ccEnabled && (primaryText || secondaryText) ? (
    <div
      className={`absolute left-1/2 -translate-x-1/2 max-w-[85%] px-4 text-center text-white pointer-events-none z-10 ${
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
          className="mt-1 opacity-75 leading-snug"
          style={{ fontSize: `${Math.max(11, subtitleSettings.fontSize - 5)}px` }}
        >
          {secondaryText}
        </p>
      )}
    </div>
  ) : null

  // 슬라이드 박스 내부 하단 컨트롤 바 (CC / 설정 / 전체화면)
  const bottomControlBar = (
    <div className={`absolute left-3 right-3 bottom-3 z-30 flex items-center justify-end gap-2 transition-opacity duration-200 ${
      settingsPanel !== null
        ? 'opacity-100 pointer-events-auto'
        : 'opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto'
    }`}>
      {/* CC 버튼 */}
      <button
        type="button"
        onClick={() => setCcEnabled((v) => !v)}
        className={`p-2 rounded-lg transition-colors ${
                  ccEnabled ? 'bg-white text-gray-900' : 'bg-black/60 text-white hover:bg-black/80'
                }`}
        aria-label={ccEnabled ? '자막 끄기' : '자막 켜기'}
        title={ccEnabled ? '자막 끄기' : '자막 켜기'}
      >
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="2" y="5" width="20" height="14" rx="2" />
          <path strokeLinecap="round" d="M10 9H8a2 2 0 000 4h2M17 9h-2a2 2 0 000 4h2" />
        </svg>
      </button>

      {/* 설정 버튼 */}
      <button
        type="button"
        onClick={() => setSettingsPanel((v) => (v ? null : 'main'))}
        className={`p-2 rounded-lg transition-colors ${
                  settingsPanel ? 'bg-white text-gray-900' : 'bg-black/60 text-white hover:bg-black/80'
                }`}
        aria-label="설정"
        title="설정"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
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
  )

  // 설정 패널 팝업 (슬라이드 박스 내부)
  const settingsPanelPopover = settingsPanel ? (
    <>
      <div
        className="absolute inset-0 z-40"
        onClick={() => setSettingsPanel(null)}
      />
      <div className="absolute right-3 bottom-14 z-50">
        {settingsPanel === 'main' && (
          <div className="w-72 bg-black/90 backdrop-blur-md text-white rounded-xl shadow-2xl overflow-hidden">
            {/* 화면 비율 */}
            <button
              type="button"
              onClick={() => setSettingsPanel('aspect')}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/10 transition-colors"
            >
              <span>화면 비율</span>
              <div className="flex items-center gap-2 text-white/60">
                <span className="text-sm">{aspectRatio.replace('/', ':')}</span>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </div>
            </button>
            <div className="h-px bg-white/10" />
            {/* 언어 설정 */}
            <button
              type="button"
              onClick={() => setSettingsPanel('language')}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/10 transition-colors"
            >
              <span>언어 설정</span>
              <svg className="w-4 h-4 text-white/60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
            <div className="h-px bg-white/10" />
            {/* 글자 크기 */}
            <button
              type="button"
              onClick={() => setSettingsPanel('fontSize')}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/10 transition-colors"
            >
              <span>글자 크기</span>
              <div className="flex items-center gap-2 text-white/60">
                <span className="text-sm">{subtitleSettings.fontSize}px</span>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </div>
            </button>
            <div className="h-px bg-white/10" />
            {/* 글자 스타일 */}
            <button
              type="button"
              onClick={() => setSettingsPanel('style')}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/10 transition-colors"
            >
              <span>글자 스타일</span>
              <div className="flex items-center gap-2 text-white/60">
                <span className="text-sm">{STYLE_LABEL[subtitleSettings.style]}</span>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </div>
            </button>
          </div>
        )}

        {/* 화면 비율 서브패널 */}
        {settingsPanel === 'aspect' && (
          <div className="w-72 bg-black/90 backdrop-blur-md text-white rounded-xl shadow-2xl overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-3 border-b border-white/10">
              <button type="button" onClick={() => setSettingsPanel('main')} className="p-1 rounded hover:bg-white/10" aria-label="뒤로">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
              <span className="font-medium">화면 비율</span>
            </div>
            {ASPECT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => { setAspectRatio(opt.value); setSettingsPanel('main') }}
                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/10 transition-colors"
              >
                <span className={`w-4 text-sm ${aspectRatio === opt.value ? 'opacity-100' : 'opacity-0'}`}>✓</span>
                <span className={aspectRatio === opt.value ? 'font-medium' : ''}>{opt.label}</span>
              </button>
            ))}
          </div>
        )}

        {/* 언어 설정 서브패널 */}
        {settingsPanel === 'language' && (
          <div className="w-[min(90%,560px)] bg-black/90 backdrop-blur-md text-white rounded-xl shadow-2xl overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-3 border-b border-white/10">
              <button type="button" onClick={() => setSettingsPanel('main')} className="p-1 rounded hover:bg-white/10" aria-label="뒤로">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
              <span className="font-medium">언어 설정</span>
            </div>
            <div className="grid grid-cols-2 gap-8 p-6">
              <LangColumn title="자막" value={primaryLang} onChange={setPrimaryLang} />
              <LangColumn title="두번째 자막" value={secondaryLang} onChange={setSecondaryLang} />
            </div>
          </div>
        )}

        {/* 글자 크기 서브패널 */}
        {settingsPanel === 'fontSize' && (
          <div className="w-72 bg-black/90 backdrop-blur-md text-white rounded-xl shadow-2xl overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-3 border-b border-white/10">
              <button type="button" onClick={() => setSettingsPanel('main')} className="p-1 rounded hover:bg-white/10" aria-label="뒤로">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
              <span className="font-medium">글자 크기</span>
            </div>
            <div className="px-4 py-4">
              <div className="flex justify-end items-center mb-3">
                <span className="text-base font-medium">{subtitleSettings.fontSize}px</span>
              </div>
              <input
                type="range"
                min={12}
                max={36}
                step={1}
                value={subtitleSettings.fontSize}
                onChange={(e) => setSubtitleSettings({ fontSize: Number(e.target.value) })}
                className="w-full accent-white"
              />
            </div>
          </div>
        )}

        {/* 글자 스타일 서브패널 */}
        {settingsPanel === 'style' && (
          <div className="w-72 bg-black/90 backdrop-blur-md text-white rounded-xl shadow-2xl overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-3 border-b border-white/10">
              <button type="button" onClick={() => setSettingsPanel('main')} className="p-1 rounded hover:bg-white/10" aria-label="뒤로">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
              <span className="font-medium">글자 스타일</span>
            </div>
            {(Object.keys(STYLE_LABEL) as SubtitleStyle[]).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => { setSubtitleSettings({ style: s }); setSettingsPanel('main') }}
                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/10 transition-colors"
              >
                <span className={`w-4 text-sm ${subtitleSettings.style === s ? 'opacity-100' : 'opacity-0'}`}>✓</span>
                <span className={subtitleSettings.style === s ? 'font-medium' : ''}>{STYLE_LABEL[s]}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </>
  ) : null

  // 슬라이드 박스 내부에 들어가는 공통 오버레이 (자막 + 바텀바 + 팝업 + 제목)
  const slideInnerOverlays = (
    <>
      {/* 상단 호버 제목 */}
      {displayTitle && (
        <div className="absolute top-0 left-0 right-0 z-30 px-4 py-3 bg-gradient-to-b from-black/70 to-transparent opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity duration-200">
          <h2 className="text-white font-medium text-lg drop-shadow truncate">
            {displayTitle}
          </h2>
        </div>
      )}
      {subtitleOverlay}
      {bottomControlBar}
      {settingsPanelPopover}
    </>
  )

  return (
    <div
      className={`h-screen overflow-hidden flex flex-col text-onBackground ${
        theme === 'gradient'
          ? 'bg-home-gradient [background-size:800%_800%] animate-gradient-shift'
          : 'bg-background'
      }`}
    >
      {/* Cursor spotlight (global overlay - 강의자 로컬) */}
      <CursorSpotlight
        x={cursorPos?.x ?? 0}
        y={cursorPos?.y ?? 0}
        visible={spotlightEnabled && cursorPos !== null}
        color={spotlightColor}
        mode="fixed"
      />

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
      <header className="flex items-center justify-between gap-3 px-4 py-3 bg-surface border-b border-primaryContainer flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <h1 className="text-xl font-special-gothic tracking-wide bg-gradient-to-r from-gradientBlue to-gradientPurple bg-clip-text text-transparent">
            Aunion AI
          </h1>
          {isLectureStarted && !isPaused && (
            <span className="flex items-center gap-1.5 px-2.5 py-1 bg-error text-white text-xs font-semibold rounded-full">
              <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse" />
              LIVE
            </span>
          )}
          {isPaused && (
            <span className="flex items-center gap-1.5 px-2.5 py-1 bg-yellow-500 text-white text-xs font-semibold rounded-full">
              <svg className="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 6 8" aria-hidden="true">
                <rect x="0" y="0" width="2" height="8" rx="0.5" />
                <rect x="4" y="0" width="2" height="8" rx="0.5" />
              </svg>
              Paused
            </span>
          )}

          {/* 강사 이름 입력 */}
          <div className="flex items-center gap-1.5 px-2 py-1 bg-primaryContainer/50 rounded-lg text-sm text-onSurface">
            <svg className="w-4 h-4 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 14l9-5-9-5-9 5 9 5zm0 0l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14z" />
            </svg>
            <input
              type="text"
              value={lecturerName}
              onChange={(e) => setLecturerName(e.target.value)}
              onBlur={(e) => sendLecturerName(e.target.value.trim())}
              placeholder="교수명"
              className="bg-transparent text-sm w-28 px-1 py-0.5 focus:outline-none placeholder-onSurface/70"
              maxLength={40}
            />
          </div>

        </div>

        <div className="flex items-center gap-2">
          {/* 초대 링크 복사 — 테두리로 강조 */}
          <button
            type="button"
            onClick={handleCopyLink}
            disabled={!shareUrl}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border-2 ${
              copied
                ? 'bg-emerald-500 text-white border-emerald-600'
                : 'bg-surface hover:bg-primaryContainer text-onSurface border-primary disabled:opacity-40'
            }`}
            title={shareUrl || 'Preparing invite link...'}
          >
            {copied ? (
              <>
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                </svg>
                복사됨
              </>
            ) : (
              <>
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                </svg>
                링크 복사
              </>
            )}
          </button>

          {/* 라이트 / 다크 / 그라데이션 3-모드 토글 (순환) */}
          <button
            type="button"
            onClick={toggleTheme}
            className="flex items-center justify-center w-9 h-9 bg-primaryContainer/50 hover:bg-primaryContainer text-onSurface rounded-lg transition-colors"
            aria-label={`Current: ${theme} mode (click to cycle)`}
            title={`${
              theme === 'light' ? 'Light' : theme === 'dark' ? 'Dark' : 'Gradient'
            } mode — click to cycle`}
          >
            {theme === 'light' ? (
              // 현재: 라이트 (해 아이콘)
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
            ) : theme === 'dark' ? (
              // 현재: 다크 (달 아이콘)
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            ) : (
              // 현재: 그라데이션 (반짝임 아이콘)
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
              </svg>
            )}
          </button>

          <button
            onClick={() => { setShowParticipants((v) => !v); if (isNarrow) setSidebarOpen(true) }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${
              showParticipants
                ? 'bg-primary text-onPrimary'
                : 'bg-primaryContainer/60 hover:bg-primaryContainer text-onSurface'
            }`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <span>{displayParticipantCount}</span>
          </button>

          <button
            onClick={handleExit}
            className="px-3 py-1.5 bg-primaryContainer/60 hover:bg-primaryContainer text-onSurface rounded-lg text-sm"
          >
            나가기
          </button>
        </div>
      </header>

      {/* 메인 */}
      <div className="flex-1 flex gap-4 p-4 overflow-hidden min-h-0 relative">
        {/* 메인 영역 — 세로: 슬라이드(fill) + 하단 바(auto) */}
        <div className="flex-1 flex flex-col gap-3 min-w-0 min-h-0 overflow-hidden">
          {/* 슬라이드/화면 박스 — Student와 동일: h-full + aspect로 세로 고정, 가로만 비율에 따라 변경 */}
          <div className="flex-1 flex items-center justify-center min-w-0 min-h-0">
              {presentationMode === 'slide' && slideStatus === 'ready' ? (
                <SlideViewer
                  onPageChange={handlePageChange}
                  containerRef={slideBoxRef}
                >
                  {slideInnerOverlays}
                </SlideViewer>
              ) : presentationMode === 'slide' ? (
                <div
                  ref={slideBoxRef}
                  className={`relative h-full ${aspectClass} max-w-full bg-surface text-onSurface border-2 border-dashed border-primaryContainer rounded-xl overflow-hidden group ${theme === 'light' ? 'shadow-[0_4px_20px_rgba(0,0,0,0.08)]' : 'shadow-2xl'}`}
                >
                  {/* 강의 제목 + 자료 업로드 — 화면 중앙 */}
                  <div className="absolute inset-0 flex flex-col items-center justify-center p-8 gap-5 overflow-auto">
                    <div className="w-full max-w-md">
                      <label className="text-xs text-onSurface/60 mb-1.5 block font-medium">
                        강의 제목
                      </label>
                      <input
                        type="text"
                        value={lectureTitle}
                        onChange={(e) => setLectureTitle(e.target.value)}
                        onBlur={(e) => sendLectureTitle(e.target.value.trim())}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') e.currentTarget.blur()
                        }}
                        placeholder={
                          slideFilename.replace(/\.pdf$/i, '') ||
                          '미기재 시 업로드한 파일명으로 표기됩니다.'
                        }
                        className="w-full px-3 py-2.5 bg-white border border-primaryContainer rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary"
                        maxLength={80}
                      />
                    </div>
                    <div className="w-full max-w-md">
                      <label className="text-xs text-onSurface/60 mb-1.5 block font-medium">
                        강의 자료
                      </label>
                      <SlideUpload />
                    </div>
                  </div>
                  {slideInnerOverlays}
                </div>
              ) : (
                <div
                  ref={slideBoxRef}
                  className={`relative h-full ${aspectClass} max-w-full bg-black rounded-xl overflow-hidden group ${theme === 'light' ? 'shadow-[0_4px_20px_rgba(0,0,0,0.08)]' : 'shadow-2xl'} flex items-center justify-center`}
                >
                  {isScreenSharing ? (
                    <div className="text-center text-white">
                      <div className="w-16 h-16 mx-auto mb-4 bg-red-500 rounded-full flex items-center justify-center animate-pulse">
                        <svg className="w-8 h-8" fill="currentColor" viewBox="0 0 24 24">
                          <path d="M21 3H3c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H3V5h18v14z" />
                        </svg>
                      </div>
                      <p className="text-lg font-medium">화면 공유 중</p>
                      <button
                        onClick={stopScreenCapture}
                        className="mt-4 px-4 py-2 bg-red-500 hover:bg-red-600 rounded-lg transition-colors"
                      >
                        공유 중지
                      </button>
                    </div>
                  ) : (
                    <div className="text-center text-white/70">
                      <svg className="w-16 h-16 mx-auto mb-3 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                      </svg>
                      <p>화면을 공유하세요</p>
                      <button
                        onClick={startScreenCapture}
                        disabled={!isLectureStarted}
                        className="mt-4 px-4 py-2 bg-primary hover:opacity-90 text-onPrimary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        화면 공유 시작
                      </button>
                    </div>
                  )}
                  {slideInnerOverlays}
                </div>
              )}
            </div>

            {/* 썸네일 행 — 슬라이드 준비 완료 시에만 (슬라이드 폭에 맞춤) */}
            {presentationMode === 'slide' && slideStatus === 'ready' && slidePages.length > 0 && (
              <div
                className="flex gap-2 overflow-x-auto scrollbar-hide flex-shrink-0 mx-auto max-w-full"
                style={{ width: slideBoxWidth }}
              >
                {slidePages.map((page, index) => {
                  const isActive = currentPage === index + 1
                  return (
                    <button
                      key={page.pageNumber}
                      type="button"
                      onClick={() => {
                        setCurrentPage(index + 1)
                        if (slideId && isLectureStarted && !isPaused) {
                          send({ type: 'page_change', slide_id: slideId, page: index + 1 })
                        }
                      }}
                      className={`relative flex-shrink-0 w-24 aspect-[4/3] rounded-lg overflow-hidden border-2 transition-colors ${
                        isActive
                          ? 'border-primary ring-2 ring-primary/30'
                          : 'border-primaryContainer hover:border-primary/60'
                      }`}
                      title={`페이지 ${index + 1}`}
                    >
                      <img
                        src={`${API_BASE}${page.imageUrl}`}
                        alt={`썸네일 ${index + 1}`}
                        className="w-full h-full object-cover"
                      />
                      <span
                        className={`absolute bottom-0 right-0 px-1.5 py-0.5 text-[10px] font-medium rounded-tl ${
                          isActive ? 'bg-primary text-onPrimary' : 'bg-black/60 text-white'
                        }`}
                      >
                        {index + 1}
                      </span>
                    </button>
                  )
                })}
              </div>
            )}

            {/* 하단 바 — 왼쪽: 모드 / 오른쪽: 강의 시작 — 슬라이드와 같은 폭으로 정렬 */}
            <div
              className="flex items-center justify-between gap-4 flex-shrink-0 mx-auto max-w-full"
              style={{ width: slideBoxWidth }}
            >
              <div className="flex bg-primaryContainer/60 rounded-lg p-1">
                <button
                  onClick={() => {
                    if (presentationMode !== 'slide') {
                      if (isScreenSharing) stopScreenCapture()
                      setPresentationMode('slide')
                      if (isLectureStarted) {
                        send({ type: 'presentation_mode', mode: 'slide' })
                        if (slideId) {
                          send({ type: 'slide_select', slide_id: slideId })
                          send({ type: 'page_change', slide_id: slideId, page: currentPage })
                        }
                      }
                    }
                  }}
                  className={`px-4 py-1.5 rounded-md font-medium transition-colors text-sm ${
                    presentationMode === 'slide'
                      ? 'bg-primary text-onPrimary shadow-sm'
                      : 'text-onSurface/70 hover:text-onSurface'
                  }`}
                >
                  강의자료
                </button>
                <button
                  onClick={() => {
                    if (presentationMode !== 'screen') {
                      setPresentationMode('screen')
                      if (isLectureStarted) {
                        send({ type: 'presentation_mode', mode: 'screen' })
                      }
                    }
                  }}
                  className={`px-4 py-1.5 rounded-md font-medium transition-colors text-sm ${
                    presentationMode === 'screen'
                      ? 'bg-primary text-onPrimary shadow-sm'
                      : 'text-onSurface/70 hover:text-onSurface'
                  }`}
                >
                  화면공유
                </button>
              </div>

              <div className="flex items-center gap-2">
                {!isLectureStarted ? (
                  <button
                    onClick={startLecture}
                    disabled={!canStartLecture}
                    className="px-6 py-2.5 bg-emerald-500 hover:bg-emerald-600 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-sm font-semibold shadow-sm"
                  >
                    강의 시작
                  </button>
                ) : (
                  <>
                    <button
                      onClick={togglePause}
                      className={`px-4 py-2.5 rounded-lg transition-colors text-sm font-medium shadow-sm ${
                        isPaused
                          ? 'bg-emerald-500 hover:bg-emerald-600 text-white'
                          : 'bg-yellow-500 hover:bg-yellow-600 text-white'
                      }`}
                    >
                      {isPaused ? '다시 시작' : '일시정지'}
                    </button>
                    <button
                      onClick={endLecture}
                      className="px-4 py-2.5 bg-red-500 hover:bg-red-600 text-white rounded-lg transition-colors text-sm font-medium shadow-sm"
                    >
                      강의 종료
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>

        {/* 사이드바 토글 탭 — 좁은 화면에서만 표시 */}
        {isNarrow && (
          <button
            type="button"
            onClick={() => setSidebarOpen(v => !v)}
            className={`absolute top-1/2 -translate-y-1/2 z-50 flex items-center justify-center w-4 h-20 border border-r-0 rounded-l-lg ${theme === 'light' ? 'bg-surface border-primaryContainer shadow-[0_0_14px_rgba(0,0,0,0.18)]' : theme === 'dark' ? 'bg-overlayBorder border-white/20 shadow-md' : 'bg-[#E0DEF7] border-purple-200/50 shadow-md'} transition-all duration-300 ease-in-out ${
              sidebarOpen ? 'right-80' : 'right-0'
            }`}
            aria-label={sidebarOpen ? '패널 숨기기' : '패널 보기'}
          >
            <svg className="w-3 h-3 text-onSurface" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d={sidebarOpen ? 'M9 5l7 7-7 7' : 'M15 19l-7-7 7-7'} />
            </svg>
          </button>
        )}

        {/* 사이드바 */}
        <aside className={isNarrow
          ? `absolute right-0 top-0 bottom-0 w-80 flex flex-col gap-3 overflow-hidden min-h-0 px-3 py-4 sidebar-panel z-40 transition-transform duration-300 ease-in-out ${sidebarOpen ? 'translate-x-0' : 'translate-x-full'}`
          : 'w-80 flex-shrink-0 flex flex-col gap-3 overflow-hidden min-h-0'
        }>
          <div className="flex-1 overflow-y-auto scrollbar-hide space-y-3 min-h-0">
            
            {/* 기존 마이크/오디오 카드 */}
            <div className="bg-surface dark:bg-overlaySurface text-onSurface rounded-xl p-4 shadow-sm sidebar-card">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold">오디오 테스트</h3>
                <span
                  className={`text-xs font-medium ${
                    isMicOn ? 'text-emerald-600' : 'text-onSurface/50'
                  }`}
                >
                  {isMicOn ? 'ON' : 'OFF'}
                </span>
              </div>

              <div className="flex items-center justify-center mb-4">
                <MicButton
                  isOn={isMicOn}
                  onClick={toggleMic}
                  disabled={!isConnected}
                  size="lg"
                />
              </div>

              {!isLectureStarted && (
                <p className="text-[11px] text-onSurface/60 text-center mb-3">
                  강의 시작 전 오디오 테스트
                </p>
              )}

              <AudioLevelMeter analyser={analyserRef} active={isMicOn} />

              <div className="mt-3 space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-onSurface/70">입력 볼륨</span>
                  <span className="text-onSurface/80 font-mono tabular-nums">
                    {micGainPct}%
                  </span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={200}
                  step={5}
                  value={micGainPct}
                  onChange={(e) => {
                    const v = Number(e.target.value)
                    setMicGainPct(v)
                    setGain(v / 100)
                  }}
                  className="w-full accent-primary"
                  aria-label="마이크 입력 볼륨"
                />
                <div className="flex justify-between text-[10px] text-onSurface/50">
                  <span>0%</span>
                  <span>100%</span>
                  <span>200%</span>
                </div>
              </div>
            </div>

            {/* 마우스 포인터 카드 */}
            <div className="bg-surface dark:bg-overlaySurface text-onSurface rounded-xl p-4 shadow-sm sidebar-card">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold">마우스 포인터</h3>
                <button
                  type="button"
                  onClick={() => setSpotlightEnabled((v) => !v)}
                  className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                    spotlightEnabled
                      ? 'bg-primary text-onPrimary shadow-sm'
                      : 'bg-primaryContainer text-onSurface/60 hover:bg-primaryContainer hover:text-onSurface'
                  }`}
                  aria-pressed={spotlightEnabled}
                >
                  {spotlightEnabled ? 'ON' : 'OFF'}
                </button>
              </div>

              <label className="text-xs text-onSurface/60 mb-1.5 block">
                스팟라이트 색상
              </label>
              <div className="grid grid-cols-6 gap-1.5 mb-2">
                {SPOTLIGHT_PRESETS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => {
                      setSpotlightColor(c)
                      if (!spotlightEnabled) setSpotlightEnabled(true)
                    }}
                    className={`w-full aspect-square rounded-full border-2 transition-transform hover:scale-110 ${
                      spotlightColor === c
                        ? 'border-onSurface ring-2 ring-offset-1 ring-onSurface/30'
                        : 'border-transparent'
                    }`}
                    style={{ backgroundColor: c }}
                    aria-label={`Color ${c}`}
                  />
                ))}
              </div>
              <input
                type="color"
                value={spotlightColor}
                onChange={(e) => {
                  setSpotlightColor(e.target.value)
                  if (!spotlightEnabled) setSpotlightEnabled(true)
                }}
                className="w-full h-8 rounded cursor-pointer border border-primaryContainer"
                aria-label="Custom spotlight color"
              />
            </div>

            {/* 자료 다운로드 */}
            {slideStatus === 'ready' && slideId && (
              <div className="bg-surface dark:bg-overlaySurface text-onSurface rounded-xl p-3 shadow-sm sidebar-card">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-semibold">자료</h3>
                  <span className="text-[10px] text-onSurface/50 truncate max-w-[150px]">
                    {slideFilename.replace(/\.pdf$/i, '')}
                  </span>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleDownload('original')}
                    className="flex-1 flex items-center justify-center gap-1 px-3 py-2 bg-primaryContainer hover:bg-primaryContainer/80 text-onSurface rounded-lg text-xs font-medium transition-colors"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    원본
                  </button>
                  <button
                    onClick={() => handleDownload('translated')}
                    className="flex-1 flex items-center justify-center gap-1 px-3 py-2 bg-primary hover:opacity-90 text-onPrimary rounded-lg text-xs font-medium transition-colors"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    번역본
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Chat 패널 */}
          {isLectureStarted && (
            <div
              className="relative bg-surface dark:bg-overlaySurface text-onSurface rounded-xl shadow-sm flex flex-col overflow-hidden flex-shrink-0 sidebar-card"
              style={{ height: '260px' }}
            >
              <div className="px-4 py-2.5 border-b border-primaryContainer flex items-center gap-2">
                <svg className="w-4 h-4 text-onSurface/60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
                <h3 className="text-sm font-semibold">채팅</h3>
              </div>
              <div
                ref={chatScrollRef}
                className="flex-1 overflow-y-auto scrollbar-hide p-3 space-y-2.5 min-h-0"
              >
                {chatMessages.length === 0 ? (
                  <div className="text-center text-sm text-onSurface/50 mt-6">
                    아직 채팅이 없습니다
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
                          <span className="text-[10px] px-1.5 py-0.5 bg-gradientPurple/20 text-gradientPurple rounded font-medium">
                            강사
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-onSurface/90 leading-relaxed break-words">
                        {msg.text}
                      </p>
                    </div>
                  ))
                )}
              </div>
              <form
                onSubmit={handleChatSubmit}
                className="p-2 border-t border-primaryContainer flex gap-2"
              >
                <input
                  ref={chatInputRef}
                  type="text"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  placeholder={isConnected ? '메시지 입력...' : '연결 중...'}
                  disabled={!isConnected}
                  className="flex-1 bg-primaryContainer/40 text-onSurface placeholder-onSurface/70 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-60"
                  maxLength={200}
                />
                <button
                  type="submit"
                  disabled={!chatInput.trim() || !isConnected}
                  className="px-3 py-2 bg-primary hover:opacity-90 disabled:opacity-40 text-onPrimary rounded-lg text-sm font-medium transition-colors"
                >
                  보내기
                </button>
              </form>

              {showParticipants && (
                <ParticipantsPanel
                  participants={participants}
                  fallbackStudentCount={studentCount}
                  onClose={() => setShowParticipants(false)}
                />
              )}
            </div>
          )}

          {!isLectureStarted && showParticipants && (
            <div
              className="relative bg-surface dark:bg-overlaySurface text-onSurface rounded-xl shadow-sm overflow-hidden flex-shrink-0 sidebar-card"
              style={{ height: '320px' }}
            >
              <ParticipantsPanel
                participants={participants}
                fallbackStudentCount={studentCount}
                onClose={() => setShowParticipants(false)}
              />
            </div>
          )}
        </aside>
      </div>
      {screenPickerSources && (
        <ScreenPickerModal
          sources={screenPickerSources}
          onSelect={selectScreenSource}
          onCancel={cancelScreenPicker}
        />
      )}
    </div>
  )
}

interface LangColumnProps {
  title: string
  value: LecturerLang
  onChange: (v: LecturerLang) => void
}

function LangColumn({ title, value, onChange }: LangColumnProps) {
  return (
    <div>
      <h3 className="text-lg font-semibold mb-4 pl-6">{title}</h3>
      <ul className="space-y-2">
        {LANG_OPTIONS.map((opt) => {
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

export default Lecturer
