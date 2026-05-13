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
import DrawingToolbar from '@/components/lecturer/DrawingToolbar'
import { DrawingCanvas, type DrawingTool, type DrawingCanvasHandle } from '@/components/common/DrawingCanvas'
import ScreenPickerModal from '@/components/lecturer/ScreenPickerModal'
import { WS_PIPELINE_URL, API_BASE, getSlideLibrary } from '@/lib/api'
import SlideLibrarySearchModal from '@/components/lecturer/SlideLibrarySearchModal'
import type { SlideLibraryItem } from '@/types/slide'

const ASPECT_OPTIONS: { value: AspectRatio; label: string; className: string }[] = [
  { value: '16/9', label: '16:9', className: 'aspect-[16/9]' },
  { value: '4/3', label: '4:3', className: 'aspect-[4/3]' },
  { value: '5/3', label: '5:3', className: 'aspect-[5/3]' },
]

const STYLE_LABEL: Record<SubtitleStyle, string> = {
  plain: '기본',
  outline: '테두리',
  glow: '글로우',
  background: '배경',
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
          '0 0 8px rgba(255,255,255,0.95)',
          '0 0 16px rgba(255,255,255,0.75)',
          '0 0 28px rgba(255,255,255,0.5)',
          '0 0 40px rgba(255,255,255,0.35)',
        ].join(', '),
      }
    default:
      return { color: 'black' }
  }
}

function Lecturer() {
  const navigate = useNavigate()
  const chatScrollRef = useRef<HTMLDivElement>(null)
  const chatInputRef = useRef<HTMLInputElement>(null)
  const slideBoxRef = useRef<HTMLDivElement>(null)
  const thumbnailStripRef = useRef<HTMLDivElement>(null)

  const [shareUrl, setShareUrl] = useState('')
  const [copied, setCopied] = useState(false)
  const [chatInput, setChatInput] = useState('')
  const [showParticipants, setShowParticipants] = useState(false)
  const [ccEnabled, setCcEnabled] = useState(false)
  const [settingsPanel, setSettingsPanel] = useState<null | 'main' | 'aspect' | 'language' | 'fontSize' | 'style'>(null)
  const [primaryLang, setPrimaryLang] = useState<LecturerLang>('en')
  const [secondaryLang, setSecondaryLang] = useState<LecturerLang>('ko')
  const [showTranscriptModal, setShowTranscriptModal] = useState(false)
  const [showMaterialChangeModal, setShowMaterialChangeModal] = useState(false)
  const [libraryItems, setLibraryItems] = useState<SlideLibraryItem[]>([])
  const [showEndConfirm, setShowEndConfirm] = useState(false)
  const [spotlightEnabled, setSpotlightEnabled] = useState(false)
  const [spotlightColor, setSpotlightColor] = useState(SPOTLIGHT_PRESETS[0])
  // 필기 도구 상태 — 마우스 포인터와 동일한 6색 팔레트 공유
  const [drawingEnabled, setDrawingEnabled] = useState(false)
  const [drawingTool, setDrawingTool] = useState<DrawingTool>('pencil')
  const [drawingColor, setDrawingColor] = useState(SPOTLIGHT_PRESETS[0])
  // 강의자 캔버스 imperative 핸들 — "전체 지우기" 버튼 등 외부 트리거용
  const drawingCanvasRef = useRef<DrawingCanvasHandle>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [isNarrow, setIsNarrow] = useState(() => window.innerWidth < 1000)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [panelOnTop, setPanelOnTop] = useState<'library' | 'sidebar'>('library')
  const [slideBoxWidth, setSlideBoxWidth] = useState<number | undefined>(undefined)
  const [pendingStart, setPendingStart] = useState(false)
  // 강의 시작 전 화면공유 시도 시 잠깐 보여줄 안내 문구
  const [screenShareNotice, setScreenShareNotice] = useState(false)
  const screenShareNoticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => {
    if (screenShareNoticeTimerRef.current) clearTimeout(screenShareNoticeTimerRef.current)
  }, [])

  // 커서 위치 상태 (브라우저 전체 기준 vw/vh 비율, 0~1)
  const [cursorPos, setCursorPos] = useState<{ x: number; y: number } | null>(null)

  // selector 별 구독 — 전체 destructure 시 store 어떤 변화에도 재렌더되어
  // useWebSocket의 콜백 ref가 흔들리고 useEffect 무한 루프 발생
  const isMicOn = useLectureStore((s) => s.isMicOn)
  const isLectureStarted = useLectureStore((s) => s.isLectureStarted)
  const isPaused = useLectureStore((s) => s.isPaused)
  const presentationMode = useLectureStore((s) => s.presentationMode)
  const slideId = useLectureStore((s) => s.slideId)
  const slideStatus = useLectureStore((s) => s.slideStatus)
  const currentPage = useLectureStore((s) => s.currentPage)
  const slidePages = useLectureStore((s) => s.slidePages)
  const subtitles = useLectureStore((s) => s.subtitles)
  const modelMode = useLectureStore((s) => s.modelMode)
  const chatMessages = useLectureStore((s) => s.chatMessages)
  const participants = useLectureStore((s) => s.participants)
  const studentCount = useLectureStore((s) => s.studentCount)
  const lectureTitle = useLectureStore((s) => s.lectureTitle)
  const slideFilename = useLectureStore((s) => s.slideFilename)
  const sessionId = useLectureStore((s) => s.sessionId)
  const setLectureTitle = useLectureStore((s) => s.setLectureTitle)
  const setMicOn = useLectureStore((s) => s.setMicOn)
  const setLectureStarted = useLectureStore((s) => s.setLectureStarted)
  const setPaused = useLectureStore((s) => s.setPaused)
  const setPresentationMode = useLectureStore((s) => s.setPresentationMode)
  const setCurrentPage = useLectureStore((s) => s.setCurrentPage)
  const reset = useLectureStore((s) => s.reset)

  const aspectRatio = usePreferencesStore((s) => s.aspectRatio)
  const setAspectRatio = usePreferencesStore((s) => s.setAspectRatio)
  const lecturerName = usePreferencesStore((s) => s.lecturerName)
  const setLecturerName = usePreferencesStore((s) => s.setLecturerName)
  const subtitleSettings = usePreferencesStore((s) => s.subtitleSettings)
  const setSubtitleSettings = usePreferencesStore((s) => s.setSubtitleSettings)
  const theme = usePreferencesStore((s) => s.theme)
  const toggleTheme = usePreferencesStore((s) => s.toggleTheme)

  // WebRTC: 학생별 RTCPeerConnection 관리. participants로부터 학생 ID 추적.
  const peerConnectionsRef = useRef<Map<string, RTCPeerConnection>>(new Map())
  // 학생별 — setRemoteDescription(answer) 전에 도착한 ICE candidate 버퍼 (표준 패턴).
  //   (없으면 answer 처리 중 도착한 candidate 가 버려져 LAN 에서도 간헐적 연결 실패)
  const pendingIceByStudentRef = useRef<Map<string, RTCIceCandidateInit[]>>(new Map())

  const handleWebRtcAnswer = useCallback(async (sender: string, sdp: RTCSessionDescriptionInit) => {
    const pc = peerConnectionsRef.current.get(sender)
    if (!pc) return
    try {
      await pc.setRemoteDescription(sdp)
      // remoteDescription 세팅 완료 — 그 사이 큐에 모인 ICE candidate 일괄 추가.
      const queued = pendingIceByStudentRef.current.get(sender) ?? []
      pendingIceByStudentRef.current.set(sender, [])
      for (const c of queued) {
        try { await pc.addIceCandidate(c) } catch (e) { console.warn('[Lecturer] queued ICE 추가 실패:', e) }
      }
    } catch (err) {
      console.error('[Lecturer] setRemoteDescription failed:', err)
    }
  }, [])

  const handleWebRtcIce = useCallback((sender: string | null, candidate: RTCIceCandidateInit) => {
    if (!sender) return
    const pc = peerConnectionsRef.current.get(sender)
    if (!pc || !pc.remoteDescription) {
      // PC 없음 / setRemoteDescription 아직 안 끝남 — 큐에 보관, handleWebRtcAnswer 가 처리.
      const q = pendingIceByStudentRef.current.get(sender) ?? []
      q.push(candidate)
      pendingIceByStudentRef.current.set(sender, q)
      return
    }
    pc.addIceCandidate(candidate).catch((e) => console.warn('[Lecturer] ICE 추가 실패:', e))
  }, [])

  const { isConnected, connect, send, sendChat, sendLectureTitle, sendLecturerName } =
    useWebSocket(WS_PIPELINE_URL, 'lecturer', {
      onWebRtcAnswer: handleWebRtcAnswer,
      onWebRtcIce: handleWebRtcIce,
    })

  const displayTitle =
    lectureTitle.trim() ||
    slideFilename.replace(/\.pdf$/i, '').trim() ||
    ''

  const aspectClass = ASPECT_OPTIONS.find((a) => a.value === aspectRatio)?.className ?? 'aspect-[4/3]'

  const handleAudioData = useCallback(async (audioBlob: Blob) => {
    // 일시정지 중에는 audio 전송 안 함 — 자막 생성/공유 차단 (page_change/screen과 동일한 정책)
    if (isPaused) return
    const arrayBuffer = await audioBlob.arrayBuffer()
    const base64 = btoa(
      new Uint8Array(arrayBuffer).reduce((data, byte) => data + String.fromCharCode(byte), '')
    )
    send({ type: 'audio', audio: base64, sample_rate: 16000, sentAt: Date.now() })
  }, [send, isPaused])

  const {
    startCapture: startAudioCapture,
    stopCapture: stopAudioCapture,
    analyserRef,
    setGain,
    micStream,
  } = useAudioCapture({
    onAudioData: handleAudioData,
  })

  const micStreamRef = useRef<MediaStream | null>(null)
  useEffect(() => { micStreamRef.current = micStream }, [micStream])

  const [micGainPct, setMicGainPct] = useState(100)

  const screenVideoRef = useRef<HTMLVideoElement>(null)

  // 캡처 종료 시 슬라이드 모드 복귀 — 가드 없이 항상 알림.
  // closure에 presentationMode를 묶어두면 stale일 때 메시지가 누락 → 학생이 마지막 프레임에 멈춤.
  // onCaptureEnd는 캡처가 실제로 활성이었을 때만 호출되므로 가드 필요 없음.
  const handleScreenCaptureEnd = useCallback(() => {
    setPresentationMode('slide')
    if (useLectureStore.getState().isLectureStarted) {
      send({ type: 'presentation_mode', mode: 'slide' })
    }
  }, [setPresentationMode, send])

  const {
    isCapturing: isScreenSharing,
    stream: screenStream,
    startCapture: startScreenCapture,
    stopCapture: stopScreenCapture,
    pickerSources: screenPickerSources,
    selectPickerSource: selectScreenSource,
    cancelPicker: cancelScreenPicker,
  } = useScreenCapture({
    maxWidth: 1280,
    onCaptureEnd: handleScreenCaptureEnd,
  })

  const screenStreamRef = useRef<MediaStream | null>(null)
  useEffect(() => { screenStreamRef.current = screenStream }, [screenStream])

  // 강의자 본인 화면용 — srcObject + autoPlay 조합은 일부 브라우저에서 자동재생 X → 명시적 play()
  useEffect(() => {
    const v = screenVideoRef.current
    if (v) {
      v.srcObject = screenStream
      if (screenStream) v.play().catch(() => {})
    }
  }, [screenStream])

  // 학생별 sendonly transceiver 보관 — mic/screen 토글 시 sender.replaceTrack 으로
  // 재협상 없이 트랙 swap. 학생 측 ontrack 은 1회만 발화, DelayNode source 유지 →
  // 토글 시 audio gap 없음, 15초 sync 그대로 보존.
  const peerTransceiversRef = useRef<Map<string, {
    audio: RTCRtpTransceiver
    video: RTCRtpTransceiver
  }>>(new Map())

  // WebRTC: 학생당 1개 PC 생성 → audio/video sendonly transceiver 등록 → 트랙 attach → offer 송신.
  //   - 스트림 유무와 무관하게 transceiver 는 항상 둘 — m-line 확보 → 이후 replaceTrack 만으로 동작.
  //   - 화면공유 없이 마이크만으로도, 마이크 없이도 연결 가능 (원본 오디오 전용 모드).
  const createOfferForStudent = useCallback(async (studentId: string) => {
    const existing = peerConnectionsRef.current.get(studentId)
    if (existing) {
      existing.close()
      peerConnectionsRef.current.delete(studentId)
      peerTransceiversRef.current.delete(studentId)
    }
    pendingIceByStudentRef.current.set(studentId, [])  // 새 PC — 옛 큐 비움
    const pc = new RTCPeerConnection({
      iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
    })
    peerConnectionsRef.current.set(studentId, pc)
    pc.onicecandidate = (e) => {
      if (e.candidate) {
        send({ type: 'webrtc_ice', target: studentId, candidate: e.candidate.toJSON() })
      }
    }
    // WebRTC 연결 진단 — 'failed' / 계속 'checking' 이면 학생과 P2P 안 닿음 (클라이언트 격리/방화벽)
    //   → 학생측 원본 음성 무음. host candidate(같은 LAN)로 연결돼야 정상.
    pc.oniceconnectionstatechange = () => console.log(`[Lecturer] ICE state (${studentId.slice(0, 8)}): ${pc.iceConnectionState}`)
    pc.onconnectionstatechange = () => {
      console.log(`[Lecturer] PC state (${studentId.slice(0, 8)}): ${pc.connectionState}`)
      if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
        peerConnectionsRef.current.delete(studentId)
        peerTransceiversRef.current.delete(studentId)
        pendingIceByStudentRef.current.delete(studentId)
      }
    }

    // 동기적으로 transceiver 등록 — useEffect 가 즉시 replaceTrack 호출해도 안전.
    const audio = pc.addTransceiver('audio', { direction: 'sendonly' })
    const video = pc.addTransceiver('video', { direction: 'sendonly' })
    peerTransceiversRef.current.set(studentId, { audio, video })

    const screenS = screenStreamRef.current
    const micS = micStreamRef.current
    const replaces: Promise<void>[] = []
    if (micS) {
      const t = micS.getAudioTracks()[0]
      if (t) replaces.push(audio.sender.replaceTrack(t))
    }
    if (screenS) {
      const t = screenS.getVideoTracks()[0]
      if (t) replaces.push(video.sender.replaceTrack(t))
    }
    await Promise.all(replaces)

    try {
      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)
      send({ type: 'webrtc_offer', target: studentId, sdp: pc.localDescription })
      console.log('[Lecturer] WebRTC offer 송신', {
        studentId,
        audio: !!micS?.getAudioTracks()[0],
        video: !!screenS?.getVideoTracks()[0],
      })
    } catch (err) {
      console.error('[Lecturer] createOffer failed:', err)
      pc.close()
      peerConnectionsRef.current.delete(studentId)
      peerTransceiversRef.current.delete(studentId)
      pendingIceByStudentRef.current.delete(studentId)
    }
  }, [send])

  // 화면 공유 시작/종료 + 학생 입출 + 마이크 스트림 변경에 따라 PC 동기화.
  //   - 마이크/화면 토글 시 PC 닫지 않음. sender.replaceTrack 으로 트랙만 swap →
  //     학생 측 ontrack 재발화 없음, DelayNode source 유지 → 토글 시 audio gap 없음.
  //   - 모든 스트림 해제 (강의 종료/handleExit) 시점에만 PC 정리.
  const prevStreamRef = useRef<MediaStream | null>(null)
  const prevStudentIdsRef = useRef<Set<string>>(new Set())
  const prevMicStreamRef = useRef<MediaStream | null>(null)
  useEffect(() => {
    const prevStream = prevStreamRef.current
    const prevIds = prevStudentIdsRef.current
    const prevMicStream = prevMicStreamRef.current
    const currentIds = new Set(participants.students.map((s) => s.id))

    const screenChanged = screenStream !== prevStream
    const micChanged = micStream !== prevMicStream
    const hasAnyStream = !!screenStream || !!micStream

    if (!hasAnyStream) {
      // 모든 스트림 해제 — 모든 PC 정리.
      peerConnectionsRef.current.forEach((pc) => pc.close())
      peerConnectionsRef.current.clear()
      peerTransceiversRef.current.clear()
      pendingIceByStudentRef.current.clear()
    } else {
      // 1) 기존 PC 트랙 교체 (재협상 X) — 학생 측 ontrack 재발화 없음.
      if (micChanged || screenChanged) {
        peerTransceiversRef.current.forEach(({ audio, video }) => {
          if (micChanged) {
            const t = micStream?.getAudioTracks()[0] ?? null
            audio.sender.replaceTrack(t).catch((err) =>
              console.error('[Lecturer] audio replaceTrack failed:', err))
          }
          if (screenChanged) {
            const t = screenStream?.getVideoTracks()[0] ?? null
            video.sender.replaceTrack(t).catch((err) =>
              console.error('[Lecturer] video replaceTrack failed:', err))
          }
        })
      }
      // 2) 신규 학생 → 새 PC + offer.
      currentIds.forEach((id) => {
        if (!peerConnectionsRef.current.has(id)) createOfferForStudent(id)
      })
      // 3) 떠난 학생 PC 정리.
      prevIds.forEach((id) => {
        if (!currentIds.has(id)) {
          const pc = peerConnectionsRef.current.get(id)
          if (pc) {
            pc.close()
            peerConnectionsRef.current.delete(id)
            peerTransceiversRef.current.delete(id)
          }
          pendingIceByStudentRef.current.delete(id)
        }
      })
    }

    prevStreamRef.current = screenStream
    prevStudentIdsRef.current = currentIds
    prevMicStreamRef.current = micStream
  }, [screenStream, micStream, participants.students, createOfferForStudent])

  useEffect(() => {
    connect()
  }, [connect])

  // 강사 기본값 — 원본 PDF 보기. lectureStore 의 default 는 'translated' (수강자 기준).
  // 강사 페이지 mount 시 강사용으로 override. 이후 강사가 토글로 변경 가능.
  useEffect(() => {
    useLectureStore.getState().setMaterialMode('original')
  }, [])

  useEffect(() => {
    fetch(`${API_BASE}/network/info`)
      .then((res) => res.json())
      .then((data) => {
        const port = window.location.port || data.port
        // 수강자는 BrowserRouter 사용 — # 없는 깨끗한 URL 로 공유.
        setShareUrl(`http://${data.lan_ip}:${port}/student/start`)
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

  // 현재 페이지 썸네일이 스트립 중앙에 오도록 스크롤 (앞/뒤 끝에서는 클램프)
  useEffect(() => {
    const strip = thumbnailStripRef.current
    if (!strip) return
    const ITEM_WIDTH = 96 + 8 // w-24(96px) + gap-2(8px)
    const thumbCenter = (currentPage - 1) * ITEM_WIDTH + 48
    const scrollLeft = thumbCenter - strip.clientWidth / 2
    strip.scrollTo({
      left: Math.max(0, Math.min(scrollLeft, strip.scrollWidth - strip.clientWidth)),
      behavior: 'smooth',
    })
  }, [currentPage])

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

      // 컨테이너 내 미디어 요소 찾기 (슬라이드 모드 = img, 화면공유 모드 = video)
      const media = container.querySelector('img, video') as HTMLImageElement | HTMLVideoElement | null
      let imgOffsetX = 0
      let imgOffsetY = 0
      let imgWidth = containerRect.width
      let imgHeight = containerRect.height

      const naturalW = media instanceof HTMLImageElement ? media.naturalWidth
                     : media instanceof HTMLVideoElement ? media.videoWidth
                     : 0
      const naturalH = media instanceof HTMLImageElement ? media.naturalHeight
                     : media instanceof HTMLVideoElement ? media.videoHeight
                     : 0

      if (naturalW && naturalH) {
        const ratio = naturalW / naturalH
        const containerRatio = containerRect.width / containerRect.height

        if (ratio > containerRatio) {
          imgWidth = containerRect.width
          imgHeight = containerRect.width / ratio
        } else {
          imgHeight = containerRect.height
          imgWidth = containerRect.height * ratio
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
      // startAudioCapture는 내부에서 에러를 catch하므로 success 반환값으로 성공 여부 판단
      // (실패 시 isMicOn=true가 되어 UI는 ON인데 실제로는 OFF인 불일치 방지)
      const success = await startAudioCapture()
      if (success) setMicOn(true)
    }
  }

  const startLecture = () => {
    if (presentationMode === 'slide' && slideStatus !== 'ready') {
      alert('강의자료를 먼저 선택하세요.')
      return
    }
    // 모델 전환 중이면 보류 — 전환 완료 시 useEffect가 자동으로 강의 시작 트리거
    if (modelMode === 'switching') {
      setPendingStart(true)
      return
    }
    setLectureStarted(true)
    setPaused(false)
    send({ type: 'lecture_start', slide_id: slideId, page: currentPage, mode: presentationMode })
  }

  // 보류된 강의 시작이 있고 모델 전환이 끝났으면 자동으로 강의 시작
  useEffect(() => {
    if (pendingStart && modelMode !== 'switching') {
      setPendingStart(false)
      setLectureStarted(true)
      setPaused(false)
      send({ type: 'lecture_start', slide_id: slideId, page: currentPage, mode: presentationMode })
    }
  }, [pendingStart, modelMode, slideId, currentPage, presentationMode, send, setLectureStarted, setPaused])

  const togglePause = () => {
    const newPaused = !isPaused
    setPaused(newPaused)
    send({ type: newPaused ? 'lecture_pause' : 'lecture_resume' })
  }

  const endLecture = () => {
    stopAudioCapture()
    stopScreenCapture()
    // 이전 강의의 필기 잔류 제거 — DrawingCanvas pageActionsRef 가 page 번호로만 keying
    // 되어 새 강의자료 선택 / 같은 슬라이드 재시작 시 옛 stroke 가 그대로 노출됨.
    drawingCanvasRef.current?.clearAllPages()
    setLectureStarted(false)
    setPaused(false)
    send({ type: 'lecture_end', slide_id: slideId })
    setShowTranscriptModal(true)
  }

  const handleExit = () => {
    stopAudioCapture()
    stopScreenCapture()
    reset()
    navigate('/lecturer/home')
  }

  const openMaterialChangeModal = async () => {
    try {
      const data = await getSlideLibrary('recent')
      setLibraryItems(data.items)
    } catch (err) {
      console.error('[Lecturer] 라이브러리 로드 실패:', err)
      setLibraryItems([])
    }
    setShowMaterialChangeModal(true)
    setPanelOnTop('library')
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

  // 강의 자료 선택은 필수 — 화면공유만을 위해 강의 시작하는 시나리오는 허용하지 않음.
  // (선택 없이 시작하면 store에 남아있던 이전 자료가 학생 화면에 잘못 노출됨)
  const canStartLecture = isConnected && slideStatus === 'ready'

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

  const isBgStyle = subtitleSettings.style === 'background'
  const bgSpanStyle = isBgStyle ? {
    backgroundColor: `rgba(8,8,8,${subtitleSettings.subtitleBgOpacity ?? 0.75})`,
    padding: '0 8px',
    WebkitBoxDecorationBreak: 'clone',
    boxDecorationBreak: 'clone',
  } as React.CSSProperties : {} as React.CSSProperties

  const subtitleOverlay = ccEnabled && (primaryText || secondaryText) ? (
    <div
      className={`absolute left-1/2 -translate-x-1/2 max-w-[85%] text-center text-white pointer-events-none z-10 ${
        subtitleSettings.position === 'top' ? 'top-6' : 'bottom-20'
      } px-4`}
      style={{
        fontSize: `${subtitleSettings.fontSize}px`,
        opacity: subtitleSettings.opacity,
        ...(isBgStyle ? {} : subtitleStyleToCss(subtitleSettings.style)),
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
          style={{ fontSize: `${Math.max(11, subtitleSettings.fontSize - 5)}px`, ...(isBgStyle ? {} : { opacity: 0.75 }) }}
        >
          <span style={bgSpanStyle}>{secondaryText}</span>
        </p>
      )}
    </div>
  ) : null

  // 슬라이드 박스 내부 하단 컨트롤 바 (CC / 설정 / 전체화면)
  // z-40 — DrawingCanvas (z-30) 위에 두어 필기 모드 활성 시에도 버튼 클릭 가로채이지 않게.
  const bottomControlBar = (
    <div className={`absolute left-3 right-3 bottom-3 z-40 flex items-center justify-end gap-2 transition-opacity duration-200 ${
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
            {/* 자막 크기 */}
            <button
              type="button"
              onClick={() => setSettingsPanel('fontSize')}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/10 transition-colors"
            >
              <span>자막 크기</span>
              <div className="flex items-center gap-2 text-white/60">
                <span className="text-sm">{subtitleSettings.fontSize}px</span>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </div>
            </button>
            <div className="h-px bg-white/10" />
            {/* 자막 스타일 */}
            <button
              type="button"
              onClick={() => setSettingsPanel('style')}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/10 transition-colors"
            >
              <span>자막 스타일</span>
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

        {/* 자막 크기 서브패널 */}
        {settingsPanel === 'fontSize' && (
          <div className="w-72 bg-black/90 backdrop-blur-md text-white rounded-xl shadow-2xl overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-3 border-b border-white/10">
              <button type="button" onClick={() => setSettingsPanel('main')} className="p-1 rounded hover:bg-white/10" aria-label="뒤로">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
              <span className="font-medium">자막 크기</span>
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

        {/* 자막 스타일 서브패널 */}
        {settingsPanel === 'style' && (
          <div className="w-72 bg-black/90 backdrop-blur-md text-white rounded-xl shadow-2xl overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-3 border-b border-white/10">
              <button type="button" onClick={() => setSettingsPanel('main')} className="p-1 rounded hover:bg-white/10" aria-label="뒤로">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
              <span className="font-medium">자막 스타일</span>
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
                  <span>배경 투명도</span>
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
      {/* 필기 캔버스 — pointerEvents는 canvas 내부에서 active일 때만 활성화 */}
      <DrawingCanvas
        ref={drawingCanvasRef}
        mode="lecturer"
        containerRef={slideBoxRef}
        page={currentPage}
        active={drawingEnabled && isLectureStarted}
        tool={drawingTool}
        color={drawingColor}
        send={send}
      />
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
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-surface rounded-2xl shadow-2xl p-6 w-[min(90%,400px)] flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-onSurface">강의 자막 저장</h2>
              <button
                type="button"
                onClick={() => { setShowTranscriptModal(false); reset(); navigate('/lecturer') }}
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

      {showMaterialChangeModal && (
        <SlideLibrarySearchModal
          items={libraryItems}
          onClose={() => setShowMaterialChangeModal(false)}
          onDeleted={(ids) => setLibraryItems((prev) => prev.filter((it) => !ids.includes(it.slide_id)))}
        />
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
              theme === 'light' ? '라이트' : theme === 'dark' ? '다크' : '기본'
            } 모드 — 변경하려면 클릭하세요.`}
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
            title="참가자 목록"
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
                    <div className="w-full max-w-3xl">
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
                    <>
                      <video
                        ref={screenVideoRef}
                        autoPlay
                        muted
                        playsInline
                        className="w-full h-full object-contain"
                      />
                      <button
                        onClick={stopScreenCapture}
                        className="absolute top-3 right-3 z-40 flex items-center gap-2 px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg transition-colors text-sm font-medium shadow-lg"
                      >
                        <span className="w-2 h-2 bg-white rounded-full animate-pulse" />
                        공유 중지
                      </button>
                    </>
                  ) : (
                    <div className="relative z-40 text-center text-white/70">
                      <svg className="w-16 h-16 mx-auto mb-3 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                      </svg>
                      <p>화면을 공유하세요</p>
                      <div className="relative inline-flex flex-col items-center mt-4">
                        <button
                          onClick={() => {
                            if (!isLectureStarted) {
                              if (screenShareNoticeTimerRef.current) {
                                clearTimeout(screenShareNoticeTimerRef.current)
                              }
                              setScreenShareNotice(true)
                              screenShareNoticeTimerRef.current = setTimeout(() => {
                                setScreenShareNotice(false)
                                screenShareNoticeTimerRef.current = null
                              }, 2200)
                              return
                            }
                            startScreenCapture()
                          }}
                          aria-disabled={!isLectureStarted}
                          className={`px-4 py-2 bg-primary text-onPrimary rounded-lg transition-colors ${
                            isLectureStarted ? 'hover:opacity-90' : 'opacity-50 cursor-not-allowed'
                          }`}
                        >
                          화면 공유 시작
                        </button>
                        <div
                          aria-live="polite"
                          className={`pointer-events-none absolute top-full mt-2 px-3 py-1.5 rounded-md text-xs whitespace-nowrap bg-black/80 text-white shadow-md transition-opacity duration-200 ${
                            screenShareNotice ? 'opacity-100' : 'opacity-0'
                          }`}
                        >
                          강의 시작 후 화면을 공유해주세요.
                        </div>
                      </div>
                    </div>
                  )}
                  {slideInnerOverlays}
                </div>
              )}
            </div>

            {/* 썸네일 행 — 슬라이드 준비 완료 시에만 (슬라이드 폭에 맞춤) */}
            {presentationMode === 'slide' && slideStatus === 'ready' && slidePages.length > 0 && (
              <div
                ref={thumbnailStripRef}
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
                  <>
                    {canStartLecture && (
                      <button
                        type="button"
                        onClick={openMaterialChangeModal}
                        className="px-4 py-2.5 bg-primaryContainer hover:bg-primaryContainer/70 text-onSurface rounded-lg transition-colors text-sm font-medium shadow-sm"
                      >
                        강의자료 변경
                      </button>
                    )}
                    <button
                      onClick={startLecture}
                      disabled={!canStartLecture || pendingStart}
                      className="px-6 py-2.5 bg-emerald-500 hover:bg-emerald-600 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-sm font-semibold shadow-sm"
                    >
                      {pendingStart ? '준비 중...' : '강의 시작'}
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={openMaterialChangeModal}
                      className="px-4 py-2.5 bg-primaryContainer hover:bg-primaryContainer/70 text-onSurface rounded-lg transition-colors text-sm font-medium shadow-sm"
                    >
                      강의자료 변경
                    </button>
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
                    <div className="relative">
                      {showEndConfirm && (
                        <div className="absolute bottom-full mb-2 right-0 z-[70] bg-surface sidebar-card text-onSurface border border-primaryContainer/60 rounded-xl shadow-2xl p-3 w-60">
                          <div className="flex justify-between mb-1">
                            <p className="text-sm font-bold mb-2.5">강의 종료</p>
                            <button
                              type="button"
                              onClick={() => setShowEndConfirm(false)}
                              className="w-5 h-5 flex items-center justify-center text-onSurface/50 hover:text-onSurface transition-colors text-xs"
                            >✕</button>
                          </div>
                          <p className="text-sm mb-2.5">강의를 종료하시겠습니까?</p>
                          <button
                            type="button"
                            onClick={() => { setShowEndConfirm(false); endLecture() }}
                            className="w-full py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg text-sm font-medium transition-colors"
                          >
                            종료
                          </button>
                        </div>
                      )}
                      <button
                        type="button"
                        onClick={() => setShowEndConfirm((v) => !v)}
                        className={`px-4 py-2.5 rounded-lg transition-colors text-sm font-medium shadow-sm ${showEndConfirm ? 'bg-red-600 text-white' : 'bg-red-500 hover:bg-red-600 text-white'}`}
                      >
                        강의 종료
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>

        {/* 사이드바 토글 탭 — 좁은 화면에서만 표시 */}
        {isNarrow && (
          <button
            type="button"
            onClick={() => { setSidebarOpen(v => { if (!v) setPanelOnTop('sidebar'); return !v }) }}
            className={`absolute top-1/2 -translate-y-1/2 z-[55] flex items-center justify-center w-4 h-20 border border-r-0 rounded-l-lg ${theme === 'light' ? 'bg-surface border-primaryContainer shadow-[0_0_14px_rgba(0,0,0,0.18)]' : theme === 'dark' ? 'bg-overlayBorder border-white/20 shadow-md' : 'bg-[#E0DEF7] border-purple-200/50 shadow-md'} transition-all duration-300 ease-in-out ${
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
          ? `absolute right-0 top-0 bottom-0 w-80 flex flex-col gap-3 overflow-hidden min-h-0 px-3 py-4 sidebar-panel ${panelOnTop === 'sidebar' ? 'z-[65]' : 'z-[55]'} transition-transform duration-300 ease-in-out ${sidebarOpen ? 'translate-x-0' : 'translate-x-full'}`
          : 'relative z-[55] w-80 flex-shrink-0 flex flex-col gap-3 overflow-hidden min-h-0'
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
            </div>

            {/* 필기 카드 */}
            <DrawingToolbar
              enabled={drawingEnabled}
              setEnabled={setDrawingEnabled}
              tool={drawingTool}
              setTool={setDrawingTool}
              color={drawingColor}
              setColor={setDrawingColor}
              palette={SPOTLIGHT_PRESETS}
              onClearAll={() => {
                drawingCanvasRef.current?.clearPage(currentPage)
                if (isConnected && isLectureStarted) {
                  send({ type: 'draw_clear', page: currentPage })
                }
              }}
            />

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
                            강사
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-onSurface/90 leading-relaxed break-words">
                        {linkifyText(msg.text)}
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
                  className="flex-1 bg-white text-gray-900 placeholder-gray-400 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-60"
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
                  locale="ko"
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
                locale="ko"
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
