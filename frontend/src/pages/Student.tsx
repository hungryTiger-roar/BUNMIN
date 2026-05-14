﻿﻿﻿﻿﻿import { useEffect, useState, useRef, useCallback, type CSSProperties } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useLectureStore } from '@/stores/lectureStore'
import {
  usePreferencesStore,
  type TranslationLang,
  type SubtitleStyle,
  type AspectRatio,
} from '@/stores/preferencesStore'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useTTS } from '@/hooks/useTTS'
import { useDelayBufferPlayer } from '@/hooks/useDelayBufferPlayer'
import ParticipantsPanel from '@/components/common/ParticipantsPanel'
import MaterialViewToggle from '@/components/common/MaterialViewToggle'
import { StudentCursorOverlay, useCursorOverlay } from '@/components/student/StudentCursorOverlay'
import { DrawingCanvas, type DrawingCanvasHandle } from '@/components/common/DrawingCanvas'
import { WS_PIPELINE_URL, API_BASE } from '@/lib/api'

const LANG_OPTIONS: { value: TranslationLang; label: string }[] = [
  { value: 'off', label: 'Off' },
  { value: 'ko', label: '한국어 (Korean)' },
  { value: 'en', label: '영어 (English)' },
  { value: 'de', label: '독일어 (Deutsch)' },
  { value: 'es', label: '스페인어 (Español)' },
  { value: 'ru', label: '러시아어 (Русский)' },
]

const AUDIO_LANG_OPTIONS: { value: TranslationLang; label: string }[] = [
  { value: 'off', label: 'Off' },
  { value: 'original', label: '원본 (Original)' },
  { value: 'en', label: '영어 (English)' },
  { value: 'de', label: '독일어 (Deutsch)' },
  { value: 'es', label: '스페인어 (Español)' },
  { value: 'ru', label: '러시아어 (Русский)' },
]
const SUBTITLE_LANG_OPTIONS = LANG_OPTIONS

const STYLE_LABEL: Record<SubtitleStyle, string> = {
  plain: 'Plain',
  outline: 'Outline',
  glow: 'Glow',
  background: 'Background',
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
  const location = useLocation()
  const slideRef = useRef<HTMLDivElement>(null)
  const chatScrollRef = useRef<HTMLDivElement>(null)
  const chatInputRef = useRef<HTMLInputElement>(null)

  // focused selectors — 각 필드 변경 시 정확하게 리렌더 트리거 (특히 subtitles 즉시 반영)
  const slideStatus = useLectureStore((s) => s.slideStatus)
  const currentPage = useLectureStore((s) => s.currentPage)
  const totalPages = useLectureStore((s) => s.totalPages)
  const slidePages = useLectureStore((s) => s.slidePages)
  const isLectureStarted = useLectureStore((s) => s.isLectureStarted)
  const isPaused = useLectureStore((s) => s.isPaused)
  const presentationMode = useLectureStore((s) => s.presentationMode)
  const subtitles = useLectureStore((s) => s.subtitles)
  const studentName = useLectureStore((s) => s.studentName)
  const setStudentName = useLectureStore((s) => s.setStudentName)
  const studentCount = useLectureStore((s) => s.studentCount)
  const chatMessages = useLectureStore((s) => s.chatMessages)
  const participants = useLectureStore((s) => s.participants)
  const lectureTitle = useLectureStore((s) => s.lectureTitle)
  const slideFilename = useLectureStore((s) => s.slideFilename)
  const sessionId = useLectureStore((s) => s.sessionId)
  const materialMode = useLectureStore((s) => s.materialMode)

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

  // TTS — Student 전용, 영어 엔진 항시 로드 정책.
  // audioLang 토글 (en ↔ original ↔ off ...) 시 엔진 재초기화 비용 제거 + 모드 전환 즉시 반응.
  // de/es/ru 등 비영어 옵션 선택 시 TTS 음성은 안 나가지만 (다국어 정책 보류), dropdown 은 유지.
  // ttsMs 는 player 가 playSentence return 에서 받아 commitSubtitle 에 전달 → 자막 commit 시점 기록.
  const {
    playSentence,
    unlockAudio: unlockTTS,
    status: ttsStatus,
    setVolume: setTTSVolume,
  } = useTTS(true, 'en')

  const audioLangRef = useRef(audioLang)
  useEffect(() => { audioLangRef.current = audioLang }, [audioLang])

  const [isAudioUnlocked, setIsAudioUnlocked] = useState(false)
  const isAudioUnlockedRef = useRef(false)
  const [autoUnlockSettled, setAutoUnlockSettled] = useState(false)

  const originalAudioRef = useRef<HTMLAudioElement>(null)

  // 원본 음성 (WebRTC) → DelayNode → GainNode → destination 파이프라인.
  //   - <audio> 엘리먼트는 트랙 keepalive 용으로 srcObject 유지 + 항상 muted=true.
  //   - 실제 출력은 Web Audio API 라인에서 발생 → DelayNode 로 자막/그림과 같은 박자.
  //   - AudioContext 는 user gesture (unlockAudio) 시점에 초기화 (브라우저 자동재생 정책).
  const audioContextRef = useRef<AudioContext | null>(null)
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const delayNodeRef = useRef<DelayNode | null>(null)
  const gainNodeRef = useRef<GainNode | null>(null)
  const pendingAudioStreamRef = useRef<MediaStream | null>(null)

  // delayMs 는 useDelayBufferPlayer 와 동일한 값 사용 — 강사 박자 정합성.
  const delayMs = Number(import.meta.env.VITE_SYNC_DELAY_MS) || 15000

  const unlockAudio = useCallback(async () => {
    const ok = await unlockTTS()
    if (!ok) return
    isAudioUnlockedRef.current = true
    setIsAudioUnlocked(true)

    // AudioContext + DelayNode 초기화 — user gesture 내부라 안전.
    if (!audioContextRef.current) {
      try {
        const ctx = new AudioContext()
        // maxDelayTime 은 delayMs + 5s buffer (실행 중 동적 조정 여지).
        const delayNode = ctx.createDelay((delayMs / 1000) + 5)
        delayNode.delayTime.value = delayMs / 1000
        const gainNode = ctx.createGain()
        gainNode.gain.value = 0  // 초기 0 — sync effect 가 즉시 올림
        delayNode.connect(gainNode).connect(ctx.destination)

        audioContextRef.current = ctx
        delayNodeRef.current = delayNode
        gainNodeRef.current = gainNode

        // ontrack 이 unlock 보다 먼저 도착해서 보관된 stream 이 있으면 지금 연결.
        if (pendingAudioStreamRef.current) {
          try {
            const src = ctx.createMediaStreamSource(pendingAudioStreamRef.current)
            src.connect(delayNode)
            sourceNodeRef.current = src
            pendingAudioStreamRef.current = null
          } catch (err) {
            console.error('[OriginalAudio] pending stream 연결 실패:', err)
          }
        }

        if (ctx.state === 'suspended') {
          await ctx.resume()
        }
        console.log(`[OriginalAudio] DelayNode 파이프라인 초기화 완료 (delay=${delayMs}ms)`)
      } catch (err) {
        console.error('[OriginalAudio] AudioContext 초기화 실패:', err)
      }
    }

    originalAudioRef.current?.play().catch(() => {})
    console.log('[Audio] 재생 잠금 해제됨')
  }, [unlockTTS, delayMs])

  // 학생측 player — wall-clock + 고정 lag (delay-buffer) 로 강사 박자 그대로 재현.
  // delayMs 는 unlockAudio 위에서 선언 — 원본 음성 DelayNode 와 동일한 값 공유.
  const playSentenceRef = useRef(playSentence)
  useEffect(() => { playSentenceRef.current = playSentence }, [playSentence])

  const unitPlayer = useDelayBufferPlayer({
    playSentence: (text: string, lang: TranslationLang) =>
      playSentenceRef.current(text, lang),
    isAudioUnlocked: () => isAudioUnlockedRef.current,
    getAudioLang: () => audioLangRef.current,
    delayMs,
  })

  useEffect(() => {
    console.log(`[SyncMode] delay-buffer (delay=${delayMs}ms)`)
  }, [delayMs])

  // ref 기반 커서 오버레이 (React 상태 없이 DOM 직접 조작)
  // slideRef를 전달해서 컨테이너 크기 기준으로 px 변환
  const { spotlightRef, onCursor } = useCursorOverlay(slideRef)

  // 강의자 필기 수신 — imperative 캔버스, React 리렌더 없이 DOM 직접 조작
  const drawingCanvasRef = useRef<DrawingCanvasHandle>(null)
  const onDraw = useCallback((msg: import('@/hooks/useWebSocket').DrawMessage) => {
    drawingCanvasRef.current?.receiveDraw(msg)
  }, [])

  // 화면 공유 = WebRTC peer-to-peer (Zoom과 동일 방식)
  // 강의자가 보낸 offer를 받아 answer 회신 → ontrack으로 MediaStream 수신 → <video srcObject>
  const screenVideoRef = useRef<HTMLVideoElement>(null)
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null)
  const pendingStreamRef = useRef<MediaStream | null>(null)
  const sendRef = useRef<((data: object) => void) | null>(null)

  const handleWebRtcOffer = useCallback(async (sdp: RTCSessionDescriptionInit) => {
    if (peerConnectionRef.current) {
      peerConnectionRef.current.close()
      peerConnectionRef.current = null
    }
    const pc = new RTCPeerConnection({
      iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
    })
    peerConnectionRef.current = pc
    pc.ontrack = (e) => {
      if (e.track.kind === 'video') {
        const stream = e.streams[0]
        pendingStreamRef.current = stream
        if (screenVideoRef.current) {
          screenVideoRef.current.srcObject = stream
        }
      } else if (e.track.kind === 'audio') {
        const audioStream = new MediaStream([e.track])
        // <audio> 엘리먼트: 트랙 keepalive 용 srcObject 만 유지, 출력은 항상 muted.
        // 실제 재생은 Web Audio API (DelayNode → GainNode) 라인 — 자막/그림과 같은
        // 박자로 wall-clock + delayMs 후 출력.
        // play() 명시 호출 — autoPlay 속성이 srcObject 교체 시점 (재협상) 에 항상 트리거
        // 되진 않음. 일부 Chrome 에서 element 가 paused 면 WebRTC 디코더가 frame 흘리는 걸
        // 중단 → MediaStreamSource 가 무음 받음 → 'original' 선택해도 안 들림.
        if (originalAudioRef.current) {
          originalAudioRef.current.srcObject = audioStream
          originalAudioRef.current.muted = true
          originalAudioRef.current.play().catch(() => { /* 다음 인터랙션에서 sync effect 가 재시도 */ })
        }
        // AudioContext 가 이미 있으면 즉시 wire, 없으면 unlockAudio 시점에 처리.
        pendingAudioStreamRef.current = audioStream
        const ctx = audioContextRef.current
        const delayNode = delayNodeRef.current
        if (ctx && delayNode) {
          try { sourceNodeRef.current?.disconnect() } catch {}
          try {
            const src = ctx.createMediaStreamSource(audioStream)
            src.connect(delayNode)
            sourceNodeRef.current = src
            pendingAudioStreamRef.current = null
            console.log('[OriginalAudio] WebRTC audio track 즉시 DelayNode 에 연결')
          } catch (err) {
            console.error('[OriginalAudio] stream 연결 실패:', err)
          }
        } else {
          console.log('[OriginalAudio] WebRTC audio track 도착 — AudioContext 대기 중 (unlockAudio 시 연결)')
        }
      }
    }
    pc.onicecandidate = (e) => {
      if (e.candidate && sendRef.current) {
        sendRef.current({ type: 'webrtc_ice', candidate: e.candidate.toJSON() })
      }
    }
    try {
      await pc.setRemoteDescription(sdp)
      const answer = await pc.createAnswer()
      await pc.setLocalDescription(answer)
      sendRef.current?.({ type: 'webrtc_answer', sdp: pc.localDescription })
    } catch (err) {
      console.error('[Student] WebRTC handshake failed:', err)
      pc.close()
      peerConnectionRef.current = null
    }
  }, [])

  const handleWebRtcIce = useCallback((_sender: string | null, candidate: RTCIceCandidateInit) => {
    const pc = peerConnectionRef.current
    if (!pc) return
    pc.addIceCandidate(candidate).catch(() => { /* 핸드셰이크 도중 도착 가능 — 무시 */ })
  }, [])

  // unit player 콜백 — useWebSocket 이 호출. transcription 은 sentence unit 으로,
  // lifecycle (lecture_end/pause/resume) 은 lifecycle unit 으로 큐에 적재.
  const onTranscription = useCallback((params: {
    text: string
    commitSubtitle: (ttsMs?: number) => void
    speechStartAt: number
    sentAt: number
  }) => {
    unitPlayer.enqueueSentence(params)
  }, [unitPlayer])

  const onLifecycle = useCallback((apply: () => void | Promise<void>, label: string) => {
    unitPlayer.enqueueLifecycle(apply, label)
  }, [unitPlayer])

  const { isConnected, connect, send, sendChat, sendStudentRename } = useWebSocket(
    WS_PIPELINE_URL,
    'student',
    {
      onCursor,
      onDraw,
      onWebRtcOffer: handleWebRtcOffer,
      onWebRtcIce: handleWebRtcIce,
      unitPlayer,
      onTranscription,
      onLifecycle,
    },
  )

  useEffect(() => { sendRef.current = send }, [send])

  const [isFullscreen, setIsFullscreen] = useState(false)
  const [volume, setVolume] = useState(70)
  const [isMuted, setIsMuted] = useState(false)
  const [ccEnabled, setCcEnabled] = useState(true)
  const [settingsPanel, setSettingsPanel] = useState<null | 'main' | 'aspect' | 'language' | 'fontSize' | 'style'>(null)
  const [chatInput, setChatInput] = useState('')
  const [showParticipants, setShowParticipants] = useState(false)
  const [materials, setMaterials] = useState<MaterialItem[]>([])
  const [showTranscriptModal, setShowTranscriptModal] = useState(false)
  const [isNarrow, setIsNarrow] = useState(() => window.innerWidth < 1000)
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const [loadingVideoSrc] = useState(() => Math.random() > 0.5 ? '/animation_white.webm' : '/animation_black.webm')

  // 수강자 이름 인라인 편집 — 헤더 뱃지 클릭 시 input으로 전환
  const [isEditingName, setIsEditingName] = useState(false)
  const [editingNameValue, setEditingNameValue] = useState('')
  const editingNameInputRef = useRef<HTMLInputElement>(null)

  const startEditingName = useCallback(() => {
    setEditingNameValue(studentName)
    setIsEditingName(true)
  }, [studentName])

  const cancelEditingName = useCallback(() => {
    setIsEditingName(false)
    setEditingNameValue('')
  }, [])

  const saveEditingName = useCallback(() => {
    const trimmed = editingNameValue.trim()
    if (!trimmed || trimmed === studentName) {
      cancelEditingName()
      return
    }
    setStudentName(trimmed)
    if (localStorage.getItem('student_name')) {
      localStorage.setItem('student_name', trimmed)
    }
    sendStudentRename(trimmed)
    setIsEditingName(false)
  }, [editingNameValue, studentName, setStudentName, sendStudentRename, cancelEditingName])

  useEffect(() => {
    if (isEditingName) {
      editingNameInputRef.current?.focus()
      editingNameInputRef.current?.select()
    }
  }, [isEditingName])

  // 슬라이드 줌/팬
  const [zoom, setZoom] = useState(100)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [zoomBadgeVisible, setZoomBadgeVisible] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const zoomTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isDraggingRef = useRef(false)
  const dragStartRef = useRef({ x: 0, y: 0, panX: 0, panY: 0 })
  const zoomRef = useRef(zoom)

  // 자막 다운로드 모달 트리거 — sessionId null → 값 transition.
  //   학생은 강의 진행 중엔 sessionId 가 null 이고, lecture_end 메시지 도착 시점에
  //   useWebSocket 이 즉시 setSessionId 를 호출하므로 그 순간 모달이 뜸.
  //   (lifecycle queue 에 들어간 UI 종료 전환은 발화 큐가 다 끝난 뒤 적용되지만,
  //    sessionId 자체는 큐와 무관하게 즉시 세팅되어 모달은 빠르게 노출.)
  const prevSessionIdRef = useRef<string | null>(null)
  useEffect(() => {
    if (!prevSessionIdRef.current && sessionId) {
      setShowTranscriptModal(true)
    }
    prevSessionIdRef.current = sessionId
  }, [sessionId])

  // 강의 종료 시 캔버스 잔류 제거 — DrawingCanvas pageActionsRef 가 page 번호로만
  // keying 되어 다음 강의에서 옛 강의의 stroke 가 그대로 노출되는 것 차단.
  // isLectureStarted true→false 전환 (lecture_end lifecycle apply 적용 후) 시점에 정리.
  const prevIsLectureStartedRef = useRef<boolean>(false)
  useEffect(() => {
    if (prevIsLectureStartedRef.current && !isLectureStarted) {
      drawingCanvasRef.current?.clearAllPages()
    }
    prevIsLectureStartedRef.current = isLectureStarted
  }, [isLectureStarted])

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

  // WebSocket 연결은 항상 자동
  useEffect(() => {
    connect()
  }, [connect])

  // 화면 공유 모드 진입 → 이미 받아둔 stream을 video에 연결, 종료 시 PC + srcObject 정리
  useEffect(() => {
    const video = screenVideoRef.current
    if (isLectureStarted && presentationMode === 'screen') {
      // ontrack이 useEffect보다 먼저 발화했을 수 있으므로 pendingStream을 적용
      if (video && pendingStreamRef.current) {
        video.srcObject = pendingStreamRef.current
      }
      return
    }
    // 화면 공유 모드 이탈 → PC 종료 + video 비우기
    if (peerConnectionRef.current) {
      peerConnectionRef.current.close()
      peerConnectionRef.current = null
    }
    pendingStreamRef.current = null
    if (video) video.srcObject = null
  }, [isLectureStarted, presentationMode])

  // 자동 unlock 은 autoEnter 경로 한정 — /start "강의 참여" 클릭의 transient
  // activation 이 SPA 라우팅으로 보존되는 케이스에만 신뢰성 있게 동작.
  //
  // 주의: F5 / Ctrl+R 새로고침 시 브라우저 history.state 가 보존되어
  // location.state.autoEnter 가 false 가 되지 않음 → reload 감지로 명시적 차단.
  // performance.getEntriesByType('navigation')[0].type 이 'reload' 면 자동 unlock
  // 안 시도하고 모달 노출. (직접 URL 진입은 'navigate' 라 fromStart 자체가 false)
  useEffect(() => {
    const fromStart = (location.state as { autoEnter?: boolean } | null)?.autoEnter
    const navEntry = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
    const isReload = navEntry?.type === 'reload'
    if (fromStart && !isReload) {
      unlockAudio().finally(() => setAutoUnlockSettled(true))
    } else {
      setAutoUnlockSettled(true)  // 새로고침 / 직접 진입 → 모달 즉시 노출
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 직접 접속/새로고침 시: 첫 인터랙션(클릭·키·터치)에서 자동 언락
  useEffect(() => {
    if (isAudioUnlocked) return
    const unlock = () => unlockAudio()
    document.addEventListener('click',      unlock, { once: true })
    document.addEventListener('keydown',    unlock, { once: true })
    document.addEventListener('touchstart', unlock, { once: true, passive: true })
    return () => {
      document.removeEventListener('click',      unlock)
      document.removeEventListener('keydown',    unlock)
      document.removeEventListener('touchstart', unlock)
    }
  }, [isAudioUnlocked, unlockAudio])

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

  // 휠 스크롤 줌 (passive: false 필요 → addEventListener 직접)
  useEffect(() => {
    const el = slideRef.current
    if (!el) return
    const handleWheel = (e: WheelEvent) => {
      if (!isLectureStarted || presentationMode !== 'slide') return
      e.preventDefault()
      const step = e.deltaY < 0 ? 10 : -10
      setZoom(prev => Math.max(100, Math.min(500, prev + step)))
      setZoomBadgeVisible(true)
      if (zoomTimerRef.current) clearTimeout(zoomTimerRef.current)
      zoomTimerRef.current = setTimeout(() => setZoomBadgeVisible(false), 1500)
    }
    el.addEventListener('wheel', handleWheel, { passive: false })
    return () => el.removeEventListener('wheel', handleWheel)
  }, [isLectureStarted, presentationMode])

  // zoomRef 동기화 (드래그 핸들러 클로저에서 최신 zoom 참조용)
  useEffect(() => { zoomRef.current = zoom }, [zoom])

  // 줌 변경 시 pan을 이미지 경계 내로 clamp (축소 시 범위 벗어난 pan 보정)
  useEffect(() => {
    if (zoom === 100) { setPan({ x: 0, y: 0 }); return }
    const el = slideRef.current
    if (!el) return
    const f = zoom / 100
    const maxX = (f - 1) * el.clientWidth / 2
    const maxY = (f - 1) * el.clientHeight / 2
    setPan(prev => ({
      x: Math.max(-maxX, Math.min(maxX, prev.x)),
      y: Math.max(-maxY, Math.min(maxY, prev.y)),
    }))
  }, [zoom])

  // 모드 전환(슬라이드↔화면공유) 시 줌/팬 리셋
  useEffect(() => {
    setZoom(100)
    setPan({ x: 0, y: 0 })
  }, [presentationMode])

  // 드래그 팬 — window 기준으로 추적해 컨테이너 밖으로 빠져도 동작
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDraggingRef.current) return
      const dx = e.clientX - dragStartRef.current.x
      const dy = e.clientY - dragStartRef.current.y
      const rawX = dragStartRef.current.panX + dx
      const rawY = dragStartRef.current.panY + dy
      const f = zoomRef.current / 100
      const el = slideRef.current
      if (el) {
        const maxX = (f - 1) * el.clientWidth / 2
        const maxY = (f - 1) * el.clientHeight / 2
        setPan({
          x: Math.max(-maxX, Math.min(maxX, rawX)),
          y: Math.max(-maxY, Math.min(maxY, rawY)),
        })
      } else {
        setPan({ x: rawX, y: rawY })
      }
    }
    const handleMouseUp = () => {
      if (!isDraggingRef.current) return
      isDraggingRef.current = false
      setIsDragging(false)
    }
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [])

  // 줌 배지 타이머 정리
  useEffect(() => () => { if (zoomTimerRef.current) clearTimeout(zoomTimerRef.current) }, [])

  // 원본 음성 Web Audio 파이프라인 cleanup — unmount 시 노드 해제 + 컨텍스트 종료.
  useEffect(() => () => {
    try { sourceNodeRef.current?.disconnect() } catch {}
    try { delayNodeRef.current?.disconnect() } catch {}
    try { gainNodeRef.current?.disconnect() } catch {}
    audioContextRef.current?.close().catch(() => {})
    sourceNodeRef.current = null
    delayNodeRef.current = null
    gainNodeRef.current = null
    audioContextRef.current = null
  }, [])

  // 원본 AudioContext suspend 복구 (옵션 B) — sync 보존형.
  //   단순 ctx.resume() 은 DelayNode 의 stale buffer 가 그대로 출력돼 visual/자막과
  //   N초 (= suspend 시간) desync 됨. 대신 resume 직후 DelayNode 와 MediaStreamSource 를
  //   재생성해 buffer 를 비우고 새로 15초 채우게 함 → 복귀 후 15초 무음 후 sync 그대로 복구.
  //   gainNode 는 유지 (audioLang 별 mute 상태 보존).
  useEffect(() => {
    const rebuildPipeline = async () => {
      const ctx = audioContextRef.current
      const gain = gainNodeRef.current
      if (!ctx || !gain) return
      if (ctx.state !== 'suspended') return

      try {
        try { sourceNodeRef.current?.disconnect() } catch { /* ignore */ }
        try { delayNodeRef.current?.disconnect() } catch { /* ignore */ }
        sourceNodeRef.current = null
        delayNodeRef.current = null

        await ctx.resume()

        // 새 DelayNode — 이전 buffer (suspend 시점에 freeze 된 stale 샘플) 폐기
        const newDelayNode = ctx.createDelay((delayMs / 1000) + 5)
        newDelayNode.delayTime.value = delayMs / 1000
        newDelayNode.connect(gain)
        delayNodeRef.current = newDelayNode

        // WebRTC MediaStream 재연결 — audio element 의 srcObject 우선, 없으면 pending
        const audioEl = originalAudioRef.current
        const stream = (audioEl?.srcObject as MediaStream | null)
                    ?? pendingAudioStreamRef.current
        if (stream) {
          try {
            const src = ctx.createMediaStreamSource(stream)
            src.connect(newDelayNode)
            sourceNodeRef.current = src
            // audio element 도 재생 보장 (suspend 중 paused 됐을 수 있음)
            if (audioEl?.paused) audioEl.play().catch(() => { /* 다음 인터랙션 재시도 */ })
          } catch (err) {
            console.error('[OriginalAudio] resume 후 source 재연결 실패:', err)
          }
        }
        console.log('[OriginalAudio] sync 보존 — DelayNode 재생성 (15초 후 정상 출력)')
      } catch (err) {
        console.error('[OriginalAudio] resume/rebuild 실패:', err)
      }
    }

    const onVisibility = () => {
      if (document.visibilityState === 'visible') rebuildPipeline()
    }
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pageshow', rebuildPipeline)
    window.addEventListener('focus', rebuildPipeline)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pageshow', rebuildPipeline)
      window.removeEventListener('focus', rebuildPipeline)
    }
  }, [delayMs])

  // volume/muted/audioLang → TTS GainNode 실시간 동기화.
  // audioLang !== 'en' 이면 강제 mute — 토글 시 in-flight TTS 가 원본 음성과 동시 출력되는 것 차단.
  // (큐 새 진입은 unitPlayer 의 gate 가 막지만, 이미 재생 중인 sentence 는 GainNode mute 로만 차단 가능)
  useEffect(() => {
    const ttsEffectiveMuted = isMuted || audioLang !== 'en'
    setTTSVolume(volume, ttsEffectiveMuted)
  }, [volume, isMuted, audioLang, setTTSVolume])

  // audioLang/volume/muted → 원본 음성 GainNode 동기화 (Web Audio 라인이 실제 출력).
  // <audio> 엘리먼트 정책 — Chrome WebRTC 트랙은 attached 된 element 가 "playing" 상태일 때만
  // MediaStreamAudioSourceNode 로 audio frames 를 흘려보냄. muted=true 는 OK 지만 volume=0 까지
  // 더하면 일부 Chrome 버전에서 트랙 디코딩 중단 → DelayNode 버퍼가 무음으로 채워져 'original' 선택해도
  // 안 들리는 증상 발생. 그래서 volume 은 1 그대로 두고 muted 만 true 로 유지.
  useEffect(() => {
    const audio = originalAudioRef.current
    if (audio) {
      audio.muted = true
      // 명시적으로 재생 유지 — 어떤 사유로든 pause 되면 트랙 디코딩 중단됨.
      if (audio.paused) {
        audio.play().catch(() => {})
      }
    }
    const gain = gainNodeRef.current
    const ctx = audioContextRef.current
    if (gain && ctx) {
      const target = (audioLang === 'original' && !isMuted) ? (volume / 100) : 0
      // 10ms 선형 ramp — 사람의 짧은 gap 감지 임계(~5-10ms) 아래라 "즉시" 로 느껴지면서
      // sample boundary 클릭/팝 차단. (이전 setTargetAtTime(0.05) 는 ~250ms 까지 끌어
      // 토글 시 부드럽지만 살짝 느린 감 있었음.)
      const now = ctx.currentTime
      gain.gain.cancelScheduledValues(now)
      gain.gain.setValueAtTime(gain.gain.value, now)
      gain.gain.linearRampToValueAtTime(target, now + 0.01)
    }
  }, [audioLang, volume, isMuted, isAudioUnlocked])

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
    requestAnimationFrame(() => chatInputRef.current?.focus())
  }

  const handleExit = () => {
    navigate('/')
  }

  const currentSlideImage = slidePages[currentPage - 1]?.imageUrl
  const slideImageUrl = currentSlideImage
    ? `${API_BASE}${currentSlideImage}${materialMode === 'translated' ? '?translated=true' : ''}`
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
    <div
      className="h-screen overflow-hidden flex flex-col bg-background text-onBackground"
    >
      {/* 원본 오디오 — audioLang=original 일 때만 언뮤트, 평소엔 muted */}
      <audio ref={originalAudioRef} autoPlay muted playsInline style={{ display: 'none' }} />

      {/* 음성 활성화 오버레이 — 새로고침 / 직접 URL 진입 시 user gesture 확보 용도.
          브라우저 autoplay 정책상 사용자 클릭 없이 AudioContext.resume() 통과 불가 →
          명확한 버튼으로 학생이 의식적으로 음성을 켜게 함. /start 경유 시 autoEnter
          로 자동 unlock 되어 이 오버레이는 안 뜸. */}
      {!isAudioUnlocked && autoUnlockSettled && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-surface rounded-2xl shadow-2xl p-8 w-[min(90%,420px)] flex flex-col items-center gap-5">
            <div className="text-5xl">🔊</div>
            <div className="text-center">
              <h2 className="text-xl font-semibold text-onSurface mb-1">Start Lecture Audio</h2>
              <p className="text-sm text-onSurface/70">
                Click below to play the live voice.
              </p>
              <p className="text-xs text-onSurface/50 mt-1">
                강의 음성을 시작하려면 클릭하세요.
              </p>
            </div>
            <button
              type="button"
              onClick={unlockAudio}
              className="w-full py-3 rounded-xl bg-primary text-onPrimary font-medium hover:opacity-90 transition-opacity shadow-lg shadow-primary/20"
            >
              Start Audio
            </button>
          </div>
        </div>
      )}

      {/* 자막 다운로드 모달 */}
      {showTranscriptModal && sessionId && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-surface rounded-2xl shadow-2xl p-6 w-[min(90%,400px)] flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-onSurface">Save Lecture Subtitles</h2>
              <button
                type="button"
                onClick={() => setShowTranscriptModal(false)}
                className="w-7 h-7 rounded-full flex items-center justify-center text-onSurface/60 hover:bg-black/10 transition-colors"
              >✕</button>
            </div>
            <p className="text-sm text-onSurface/70">Download the subtitles recognized during the lecture.</p>
            <div className="flex flex-col gap-2">
              <a
                href={`${API_BASE}/transcripts/${sessionId}/download?format=txt`}
                download
                className="flex items-center justify-center gap-2 w-full py-3 rounded-xl bg-primary text-onPrimary font-medium hover:opacity-90 transition-opacity"
              >
                <span>📄</span> Download TXT
              </a>
              <a
                href={`${API_BASE}/transcripts/${sessionId}/download?format=srt`}
                download
                className="flex items-center justify-center gap-2 w-full py-3 rounded-xl bg-primaryContainer text-onPrimaryContainer font-medium hover:opacity-90 transition-opacity"
              >
                <span>🎬</span> Download SRT
              </a>
            </div>
          </div>
        </div>
      )}

      {/* 헤더 */}
      <header className="flex items-center justify-between gap-3 px-4 py-3 border-b border-primaryContainer bg-surface backdrop-blur-md shadow-sm flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <h1 className="text-xl font-special-gothic tracking-wide">Aunion AI</h1>
          {isLectureStarted && !isPaused && (
            <span className="flex items-center gap-1.5 px-2.5 py-1 bg-error text-white text-xs font-semibold rounded-full shadow-lg shadow-error/30">
              <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse" />
              LIVE
            </span>
          )}
          {isPaused && (
            <span className="flex items-center gap-1.5 px-2.5 py-1 bg-yellow-500 text-white text-xs font-semibold rounded-full shadow-lg shadow-yellow-500/30">
              <svg className="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 6 8" aria-hidden="true">
                <rect x="0" y="0" width="2" height="8" rx="0.5" />
                <rect x="4" y="0" width="2" height="8" rx="0.5" />
              </svg>
              Paused
            </span>
          )}
          {isLectureStarted && slideStatus === 'ready' && totalPages > 0 && (
            <div className="flex items-center gap-1.5 px-3 py-1 bg-primaryContainer/60 rounded-full text-sm text-onSurface">
              <span className="font-medium">{currentPage}</span>
              <span className="opacity-60">/</span>
              <span className="opacity-60">{totalPages}</span>
            </div>
          )}
          {ttsStatus === 'loading' && (
            <span className="flex items-center gap-1.5 px-2.5 py-1 bg-yellow-500/20 text-yellow-600 dark:text-yellow-400 text-xs font-medium rounded-full border border-yellow-500/30">
              <span className="w-1.5 h-1.5 bg-yellow-500 rounded-full animate-pulse" />
              TTS 로딩 중
            </span>
          )}
          {ttsStatus === 'error' && (
            <span className="flex items-center gap-1.5 px-2.5 py-1 bg-error/20 text-error text-xs font-medium rounded-full border border-error/30">
              TTS 오류
            </span>
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
            onClick={() => { setShowParticipants((v) => !v); if (isNarrow) setSidebarOpen(true) }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${
              showParticipants
                ? 'bg-primary text-onPrimary'
                : 'bg-primaryContainer/60 hover:bg-primaryContainer text-onSurface'
            }`}
            title="Participant list"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <span>{displayParticipantCount}</span>
          </button>

          {studentName && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-primaryContainer/60 rounded-lg text-sm text-onSurface">
              {isEditingName ? (
                <input
                  ref={editingNameInputRef}
                  type="text"
                  value={editingNameValue}
                  onChange={(e) => setEditingNameValue(e.target.value)}
                  onBlur={saveEditingName}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      saveEditingName()
                    } else if (e.key === 'Escape') {
                      e.preventDefault()
                      cancelEditingName()
                    }
                  }}
                  maxLength={20}
                  aria-label="이름 수정"
                  className="bg-white/95 rounded px-2 py-0.5 text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary w-32 text-sm"
                />
              ) : (
                <button
                  type="button"
                  onClick={startEditingName}
                  className="flex items-center gap-1.5 hover:opacity-80 transition-opacity"
                  title="이름 수정"
                  aria-label={`이름 수정 (현재 이름: ${studentName})`}
                >
                  <svg className="w-4 h-4 opacity-70 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                  <span className="truncate">{studentName}</span>
                  <svg className="w-3.5 h-3.5 opacity-60 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                </button>
              )}
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
      <main className="flex-1 flex gap-4 px-4 py-4 overflow-hidden min-h-0 relative">
        <div className="flex-1 flex items-center justify-center min-w-0 min-h-0">
          <div
            ref={slideRef}
            className={`group relative bg-black rounded-xl overflow-hidden ${theme === 'light' ? 'shadow-[0_4px_20px_rgba(0,0,0,0.08)]' : 'shadow-2xl'} h-full ${aspectClass} max-w-full ${zoom > 100 ? (isDragging ? 'cursor-grabbing' : 'cursor-grab') : ''}`}
            onMouseDown={(e) => {
              if (zoom <= 100) return
              e.preventDefault()
              isDraggingRef.current = true
              setIsDragging(true)
              dragStartRef.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y }
            }}
          >
            {/* 강의자 커서 오버레이 (ref 기반, 리렌더링 없음) */}
            {!isPaused && <StudentCursorOverlay spotlightRef={spotlightRef} />}

            {/* 강의자 필기 오버레이 (ref 기반 imperative 캔버스, 리렌더링 없음) */}
            <DrawingCanvas
              ref={drawingCanvasRef}
              mode="student"
              containerRef={slideRef}
              page={currentPage}
            />


            {/* 강의자료 원본/번역 토글 (강의 시작 후 슬라이드 표시 중일 때만) */}
            {isLectureStarted && presentationMode === 'slide' && slideStatus === 'ready' && slideImageUrl && (
              <MaterialViewToggle className={`absolute top-3 z-40 right-3`} />
            )}

            {/* 줌 배율 배지 — 스크롤 직후 잠시 표시 후 fade-out */}
            {isLectureStarted && presentationMode === 'slide' && slideStatus === 'ready' && slideImageUrl && (
              <div
                className={`absolute top-14 right-3 z-30 px-3 py-1 bg-black/60 backdrop-blur-sm text-white text-sm font-semibold rounded-lg shadow-lg pointer-events-none transition-opacity duration-500 ${
                  zoomBadgeVisible ? 'opacity-100' : 'opacity-0'
                }`}
              >
                {zoom}%
              </div>
            )}

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

            {/* 슬라이드/화면공유 — 강의 시작 후에만 노출 */}
            {isLectureStarted && presentationMode === 'screen' ? (
              <video
                ref={screenVideoRef}
                autoPlay
                muted
                playsInline
                className="w-full h-full object-contain"
              />
            ) : isLectureStarted && slideStatus === 'ready' && slideImageUrl ? (
              <img
                key={`${currentPage}`}
                src={slideImageUrl}
                alt={`슬라이드 ${currentPage}`}
                className="w-full h-full object-contain select-none"
                draggable={false}
                style={{
                  transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom / 100})`,
                  transformOrigin: 'center center',
                  transition: isDragging ? 'none' : 'transform 0.1s ease-out',
                }}
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center text-white/50">
                <div className="text-center">
                  <video src={loadingVideoSrc} autoPlay loop muted playsInline className="w-16 h-16 mx-auto" />
                  <div className="loader --4 mb-4" />
                  {!isConnected ? (
                    <p className="text-lg">Connecting to server...</p>
                  ) : !isLectureStarted ? (
                    <p className="text-lg">Waiting for the lecture to start...</p>
                  ) : (
                    <p className="text-lg">Loading lecture material...</p>
                  )}
                </div>
              </div>
            )}

            {/* 자막 오버레이 */}
            {ccEnabled && (primaryText || secondaryText) && (() => {
              const isBg = subtitleSettings.style === 'background'
              const textShadowIfNotBg = isBg ? {} : subtitleStyleToCss(subtitleSettings.style)
              const bgSpanStyle = isBg ? {
                backgroundColor: `rgba(8,8,8,${subtitleSettings.subtitleBgOpacity ?? 0.75})`,
                padding: '0 8px',
                WebkitBoxDecorationBreak: 'clone',
                boxDecorationBreak: 'clone',
              } as CSSProperties : {} as CSSProperties
              return (
                <div
                  className={`absolute left-1/2 -translate-x-1/2 max-w-[90%] text-center text-white pointer-events-none z-10 ${
                    subtitleSettings.position === 'top' ? 'top-6' : 'bottom-20'
                  } px-4`}
                  style={{
                    fontSize: `${subtitleSettings.fontSize}px`,
                    opacity: subtitleSettings.opacity,
                    ...textShadowIfNotBg,
                  }}
                >
                  {primaryText && (
                    <p className="font-medium leading-snug">
                      <span style={bgSpanStyle}>{primaryText}</span>
                    </p>
                  )}
                  {secondaryText && (
                    <p
                      className="mt-1 leading-snug"
                      style={{ fontSize: `${Math.max(12, subtitleSettings.fontSize - 4)}px`, ...(isBg ? {} : { opacity: 0.8 }) }}
                    >
                      <span style={bgSpanStyle}>{secondaryText}</span>
                    </p>
                  )}
                </div>
              )
            })()}

            {/* 화면 내부 하단 컨트롤 바 — 마우스 올렸을 때만 표시 (설정 열려있으면 항상 표시) */}
            <div className={`absolute left-3 right-3 bottom-3 z-30 flex items-center gap-2 transition-opacity duration-200 ${
              settingsPanel !== null
                ? 'opacity-100 pointer-events-auto'
                : 'opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto'
            }`}>
              {/* 볼륨 — 스피커 아이콘에 마우스 올리면 슬라이더 표시 */}
              <div className="group/vol flex items-center bg-black/60 backdrop-blur-sm rounded-full pl-2 pr-2 py-1.5 group-hover/vol:pr-3 transition-all">
                <button
                  type="button"
                  onClick={() => { unlockAudio(); setIsMuted(!isMuted) }}
                  className="text-white hover:opacity-80 relative"
                  aria-label={isMuted ? '음소거 해제' : '음소거'}
                >
                  {!isAudioUnlocked && (
                    <span className="absolute -top-1 -right-1 w-2 h-2 bg-yellow-400 rounded-full" title="클릭하여 오디오 활성화" />
                  )}
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

              {/* CC 버튼 */}
              <button
                type="button"
                onClick={() => setCcEnabled((v) => !v)}
                className={`p-2 rounded-lg transition-colors ${
                  ccEnabled ? 'bg-white text-gray-900' : 'bg-black/60 text-white hover:bg-black/80'
                }`}
                aria-label={ccEnabled ? 'Turn off subtitles' : 'Turn on subtitles'}
                title={ccEnabled ? 'Turn off subtitles' : 'Turn on subtitles'}
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
                aria-label="Settings"
                title="Settings"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              </button>

              {/* 전체화면 버튼 */}
              <button
                type="button"
                onClick={toggleFullscreen}
                className="p-2 bg-black/60 text-white rounded-lg hover:bg-black/80"
                aria-label={isFullscreen ? 'Exit full screen' : 'Full screen'}
                title={isFullscreen ? 'Exit full screen' : 'Full screen'}
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

            {/* 설정 패널 */}
            {settingsPanel && (
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
                        <span>Aspect Ratio</span>
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
                        <span>Language</span>
                        <svg className="w-4 h-4 text-white/60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                      </button>

                      <div className="h-px bg-white/10" />

                      {/* 자막 크기 */}
                      <button
                        type="button"
                        onClick={() => setSettingsPanel('fontSize')}
                        className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/10 transition-colors"
                      >
                        <span>Subtitle Font Size</span>
                        <div className="flex items-center gap-2 text-white/60">
                          <span className="text-sm">{subtitleSettings.fontSize}px</span>
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                          </svg>
                        </div>
                      </button>

                      <div className="h-px bg-white/10" />

                      {/* 스타일 */}
                      <button
                        type="button"
                        onClick={() => setSettingsPanel('style')}
                        className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/10 transition-colors"
                      >
                        <span>Subtitle Style</span>
                        <div className="flex items-center gap-2 text-white/60">
                          <span className="text-sm">{STYLE_LABEL[subtitleSettings.style]}</span>
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                          </svg>
                        </div>
                      </button>
                    </div>
                  )}

                  {settingsPanel === 'aspect' && (
                    <div className="w-72 bg-black/90 backdrop-blur-md text-white rounded-xl shadow-2xl overflow-hidden">
                      <div className="flex items-center gap-2 px-3 py-3 border-b border-white/10">
                        <button
                          type="button"
                          onClick={() => setSettingsPanel('main')}
                          className="p-1 rounded hover:bg-white/10"
                          aria-label="뒤로"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                          </svg>
                        </button>
                        <span className="font-medium">Aspect Ratio</span>
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

                  {settingsPanel === 'language' && (
                    <div className="w-[min(90%,700px)] bg-black/90 backdrop-blur-md text-white rounded-xl shadow-2xl overflow-hidden">
                      <div className="flex items-center gap-2 px-3 py-3 border-b border-white/10">
                        <button
                          type="button"
                          onClick={() => setSettingsPanel('main')}
                          className="p-1 rounded hover:bg-white/10"
                          aria-label="뒤로"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                          </svg>
                        </button>
                        <span className="font-medium">Language</span>
                      </div>
                      <div className="grid grid-cols-3 gap-6 p-6">
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
                      </div>
                    </div>
                  )}

                  {/* 글자 크기 서브패널 */}
                  {settingsPanel === 'fontSize' && (
                    <div className="w-72 bg-black/90 backdrop-blur-md text-white rounded-xl shadow-2xl overflow-hidden">
                      <div className="flex items-center gap-2 px-3 py-3 border-b border-white/10">
                        <button
                          type="button"
                          onClick={() => setSettingsPanel('main')}
                          className="p-1 rounded hover:bg-white/10"
                          aria-label="뒤로"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                          </svg>
                        </button>
                        <span className="font-medium">Subtitle Font Size</span>
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

                  {/* 스타일 서브패널 */}
                  {settingsPanel === 'style' && (
                    <div className="w-72 bg-black/90 backdrop-blur-md text-white rounded-xl shadow-2xl overflow-hidden">
                      <div className="flex items-center gap-2 px-3 py-3 border-b border-white/10">
                        <button
                          type="button"
                          onClick={() => setSettingsPanel('main')}
                          className="p-1 rounded hover:bg-white/10"
                          aria-label="뒤로"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                          </svg>
                        </button>
                        <span className="font-medium">Subtitle Style</span>
                      </div>
                      {(Object.keys(STYLE_LABEL) as SubtitleStyle[]).map((s) => (
                        <button
                          key={s}
                          type="button"
                          onClick={() => setSubtitleSettings({ style: s })}
                          className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/10 transition-colors"
                        >
                          <span className={`w-4 text-sm ${subtitleSettings.style === s ? 'opacity-100' : 'opacity-0'}`}>✓</span>
                          <span className={subtitleSettings.style === s ? 'font-medium' : ''}>{STYLE_LABEL[s]}</span>
                        </button>
                      ))}
                      {subtitleSettings.style === 'background' && (
                        <div className="px-4 py-3 border-t border-white/10">
                          <div className="flex justify-between text-xs text-white/70 mb-1">
                            <span>Background opacity</span>
                            <span>{Math.round((subtitleSettings.subtitleBgOpacity ?? 0.8) * 100)}%</span>
                          </div>
                          <input
                            type="range"
                            min={0}
                            max={100}
                            step={5}
                            value={Math.round((subtitleSettings.subtitleBgOpacity ?? 0.8) * 100)}
                            onChange={(e) => setSubtitleSettings({ subtitleBgOpacity: Number(e.target.value) / 100 })}
                            className="w-full accent-white"
                          />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>

        {/* 사이드바 토글 탭 — 좁은 화면에서만 표시 */}
        {isNarrow && (
          <button
            type="button"
            onClick={() => setSidebarOpen(v => !v)}
            className={`absolute top-1/2 -translate-y-1/2 z-[55] flex items-center justify-center w-4 h-20 border border-r-0 rounded-l-lg ${theme === 'light' ? 'bg-surface border-primaryContainer shadow-[0_0_14px_rgba(0,0,0,0.18)]' : theme === 'dark' ? 'bg-overlayBorder border-white/20 shadow-md' : 'bg-[#E0DEF7] border-purple-200/50 shadow-md'} transition-all duration-300 ease-in-out ${
              sidebarOpen ? 'right-80' : 'right-0'
            }`}
            aria-label={sidebarOpen ? 'Hide panel' : 'Show panel'}
          >
            <svg className="w-3 h-3 text-onSurface" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d={sidebarOpen ? 'M9 5l7 7-7 7' : 'M15 19l-7-7 7-7'} />
            </svg>
          </button>
        )}

        {/* 우측 사이드: 강의자료 + 채팅 */}
        <aside className={isNarrow
          ? `absolute right-0 top-0 bottom-0 w-80 flex flex-col gap-3 min-h-0 px-3 py-4 sidebar-panel z-[55] transition-transform duration-300 ease-in-out ${sidebarOpen ? 'translate-x-0' : 'translate-x-full'}`
          : 'relative z-[55] w-80 flex-shrink-0 flex flex-col gap-3 min-h-0'
        }>
          {/* 오늘의 강의 자료 — 강의 시작 후에만 노출 */}
          {isLectureStarted && (
          <div
            className="flex-shrink-0 flex flex-col bg-surface text-onSurface backdrop-blur-md rounded-xl border border-primaryContainer shadow-sm overflow-hidden sidebar-card"
            style={{ maxHeight: '50%' }}
          >
            <div className="px-4 py-3 border-b border-primaryContainer flex items-center gap-2 flex-shrink-0">
              <svg className="w-5 h-5 opacity-80" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <h3 className="font-medium">Today's lecture material</h3>
            </div>
            <div className="flex-1 overflow-y-auto scrollbar-hide p-2 space-y-1 min-h-0">
              {materials.length === 0 ? (
                <div className="text-center text-sm text-onSurface/60 py-6">
                  There is no lecture material uploaded yet.
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
          )}

          {/* 채팅 패널 (참여자 패널이 오버레이로 덮음) */}
          <div className="relative flex-1 flex flex-col bg-surface text-onSurface backdrop-blur-md rounded-xl border border-primaryContainer shadow-sm overflow-hidden min-h-0 sidebar-card">
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
                  <div className="flex items-center gap-1.5 mb-0.5">
                    {msg.sender === 'lecturer' && (
                      <svg
                        className="w-4 h-4 text-lecturerAccent flex-shrink-0"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth={1.7}
                        viewBox="0 0 24 24"
                        aria-hidden="true"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" d="M4.26 10.147a60.438 60.438 0 0 0-.491 6.347A48.62 48.62 0 0 1 12 20.904a48.62 48.62 0 0 1 8.232-4.41 60.46 60.46 0 0 0-.491-6.347m-15.482 0a50.636 50.636 0 0 0-2.658-.813A59.906 59.906 0 0 1 12 3.493a59.903 59.903 0 0 1 10.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.717 50.717 0 0 1 12 13.489a50.702 50.702 0 0 1 7.74-3.342M6.75 15a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm0 0v-3.675A55.378 55.378 0 0 1 12 8.443m-7.007 11.55A5.981 5.981 0 0 0 6.75 15.75v-1.5" />
                      </svg>
                    )}
                    <span
                      className={`text-sm font-semibold ${
                        msg.sender === 'lecturer' ? 'text-lecturerAccent' : 'text-onSurface'
                      }`}
                    >
                      {msg.name}
                    </span>
                    {msg.sender === 'lecturer' && (
                      <span className="text-xs px-1.5 py-0.5 bg-lecturerAccent/15 text-lecturerAccent rounded font-medium">
                        Lecturer
                      </span>
                    )}
                  </div>
                  <p
                    className={`text-sm leading-relaxed break-words ${
                      msg.sender === 'lecturer'
                        ? 'text-lecturerAccent/95'
                        : 'text-onSurface/90'
                    }`}
                  >
                    {linkifyText(msg.text)}
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

function linkifyText(text: string) {
  const URL_REGEX = /https?:\/\/[^\s]+/g
  const parts: React.ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  URL_REGEX.lastIndex = 0
  while ((match = URL_REGEX.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index))
    const url = match[0]
    parts.push(
      <a key={match.index} href={url} target="_blank" rel="noopener noreferrer"
        className="underline hover:opacity-70 break-all"
        onClick={(e) => e.stopPropagation()}
      >{url}</a>
    )
    lastIndex = match.index + url.length
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex))
  return parts.length === 0 ? text : parts
}

function LangColumn({ title, value, onChange, options }: LangColumnProps) {
  return (
    <div>
      <h3 className="text-base font-semibold mb-4 pl-6 h-12 leading-snug">{title}</h3>
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
