import { useCallback, useEffect, useRef, useState } from 'react'
import { useLectureStore } from '@/stores/lectureStore'
import { usePreferencesStore } from '@/stores/preferencesStore'
import { API_BASE } from '@/lib/api'

interface WebSocketMessage {
  type: string
  [key: string]: unknown
}

type Role = 'lecturer' | 'student'

/** 커서 메시지 타입 (ref 기반 DOM 업데이트용) */
export interface CursorMessage {
  x: number
  y: number
  visible: boolean
  color: string
}

interface UseWebSocketOptions {
  /** 커서 메시지 수신 시 콜백 (React 상태 대신 DOM 직접 업데이트용) */
  onCursor?: (cursor: CursorMessage) => void
  /** 번역 텍스트 수신 시 콜백 (TTS 합성 등) */
  onTranslation?: (text: string) => void
  /** WebRTC offer 수신 (수강자 전용) */
  onWebRtcOffer?: (sdp: RTCSessionDescriptionInit) => void
  /** WebRTC answer 수신 (강의자 전용) — sender = student id */
  onWebRtcAnswer?: (sender: string, sdp: RTCSessionDescriptionInit) => void
  /** WebRTC ICE candidate 수신 — 강의자는 sender(학생id), 수강자는 sender=null */
  onWebRtcIce?: (sender: string | null, candidate: RTCIceCandidateInit) => void
}

export function useWebSocket(url: string, role: Role = 'student', options: UseWebSocketOptions = {}) {
  const { onCursor, onTranslation, onWebRtcOffer, onWebRtcAnswer, onWebRtcIce } = options
  const socketRef = useRef<WebSocket | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>()

  // 각 setter를 개별 selector로 구독 — Zustand action은 stable 이므로 재렌더 트리거하지 않음
  // (전체 destructure 시 store 어떤 필드가 바뀌어도 useWebSocket 재렌더 → send/connect ref 흔들림)
  const addSubtitle = useLectureStore((s) => s.addSubtitle)
  const setConnected = useLectureStore((s) => s.setConnected)
  const setSlideId = useLectureStore((s) => s.setSlideId)
  const setSlideStatus = useLectureStore((s) => s.setSlideStatus)
  const setSlidePages = useLectureStore((s) => s.setSlidePages)
  const setCurrentPage = useLectureStore((s) => s.setCurrentPage)
  const setLectureStarted = useLectureStore((s) => s.setLectureStarted)
  const setPaused = useLectureStore((s) => s.setPaused)
  const setPresentationMode = useLectureStore((s) => s.setPresentationMode)
  const setCurrentScreen = useLectureStore((s) => s.setCurrentScreen)
  const setStudentCount = useLectureStore((s) => s.setStudentCount)
  const addChatMessage = useLectureStore((s) => s.addChatMessage)
  const setParticipants = useLectureStore((s) => s.setParticipants)
  const setLectureTitle = useLectureStore((s) => s.setLectureTitle)
  const setSlideFilename = useLectureStore((s) => s.setSlideFilename)
  const setSessionId = useLectureStore((s) => s.setSessionId)
  const studentName = useLectureStore((s) => s.studentName)

  const lecturerName = usePreferencesStore((s) => s.lecturerName)

  const registerNameRef = useRef(role === 'lecturer' ? lecturerName : studentName)
  useEffect(() => {
    registerNameRef.current = role === 'lecturer' ? lecturerName : studentName
  }, [role, lecturerName, studentName])

  // onCursor / onTranslation callback refs (stale closure 방지)
  const onCursorRef = useRef(onCursor)
  useEffect(() => { onCursorRef.current = onCursor }, [onCursor])

  const onTranslationRef = useRef(onTranslation)
  useEffect(() => { onTranslationRef.current = onTranslation }, [onTranslation])

  const onWebRtcOfferRef = useRef(onWebRtcOffer)
  useEffect(() => { onWebRtcOfferRef.current = onWebRtcOffer }, [onWebRtcOffer])
  const onWebRtcAnswerRef = useRef(onWebRtcAnswer)
  useEffect(() => { onWebRtcAnswerRef.current = onWebRtcAnswer }, [onWebRtcAnswer])
  const onWebRtcIceRef = useRef(onWebRtcIce)
  useEffect(() => { onWebRtcIceRef.current = onWebRtcIce }, [onWebRtcIce])

  // 슬라이드 페이지 로드
  const loadSlidePages = useCallback(async (slideId: string) => {
    try {
      const response = await fetch(`${API_BASE}/slides/pages/${slideId}`)
      if (!response.ok) throw new Error('Failed to load slides')

      const data = await response.json()
      setSlidePages(data.pages)
      if (typeof data.filename === 'string') {
        setSlideFilename(data.filename)
      }
      setSlideStatus('ready')
    } catch (err) {
      console.error('[WebSocket] 슬라이드 로드 실패:', err)
    }
  }, [setSlidePages, setSlideStatus, setSlideFilename])

  const handleMessage = useCallback((data: WebSocketMessage) => {
    switch (data.type) {
      case 'transcription': {
        // 강의 시작 전엔 강의자 마이크 테스트 자막을 수강자에게 표시/재생 안 함
        if (role === 'student' && !useLectureStore.getState().isLectureStarted) {
          break
        }
        // 번역 결과 수신
        const outputTime = Date.now()
        const inputTime = data.sentAt as number | undefined
        addSubtitle({
          original: data.original as string,
          translated: data.translated as string,
          timestamp: outputTime,
          inputTime,
        })

        // 번역 텍스트 콜백 (TTS 등 상위에서 처리)
        if (data.translated) {
          onTranslationRef.current?.(data.translated as string)
        }
        break
      }

      case 'slide_select':
        // 강의자가 슬라이드 선택
        if (role === 'student') {
          const slideId = data.slide_id as string
          setSlideId(slideId)
          setSlideStatus('processing')
          loadSlidePages(slideId)
        }
        break

      case 'page_change':
        // 페이지 변경 동기화
        if (role === 'student') {
          const page = data.page as number
          setCurrentPage(page)
        }
        break

      case 'lecture_start':
        // 강의 시작
        setLectureStarted(true)
        if (role === 'student' && data.slide_id) {
          const slideId = data.slide_id as string
          setSlideId(slideId)
          setSlideStatus('processing')
          loadSlidePages(slideId)
        }
        console.log('[WebSocket] 강의 시작')
        break

      case 'session_started':
        // 강의자: 강의 시작 시 자막 세션 ID 수신
        if (data.session_id) setSessionId(data.session_id as string)
        break

      case 'lecture_end':
        // 강의 종료
        setLectureStarted(false)
        setPaused(false)
        setCurrentScreen(null)
        // 수강자: 강의 종료 메시지에 포함된 세션 ID 저장
        if (data.session_id) setSessionId(data.session_id as string)
        console.log('[WebSocket] 강의 종료')
        break

      case 'lecture_pause':
        // 강의 일시정지
        setPaused(true)
        console.log('[WebSocket] 강의 일시정지')
        break

      case 'lecture_resume':
        // 강의 재개
        setPaused(false)
        console.log('[WebSocket] 강의 재개')
        break

      case 'presentation_mode':
        // 발표 모드 변경
        if (role === 'student') {
          const mode = data.mode as 'slide' | 'screen'
          setPresentationMode(mode)
          if (mode === 'slide') {
            setCurrentScreen(null)
          }
          console.log('[WebSocket] 발표 모드 변경:', mode)
        }
        break

      case 'screen':
        // 구버전 호환 (사용 안 함 — WebRTC로 대체)
        break

      case 'webrtc_offer':
        if (role === 'student') {
          onWebRtcOfferRef.current?.(data.sdp as RTCSessionDescriptionInit)
        }
        break

      case 'webrtc_answer':
        if (role === 'lecturer') {
          onWebRtcAnswerRef.current?.(
            data.sender as string,
            data.sdp as RTCSessionDescriptionInit,
          )
        }
        break

      case 'webrtc_ice':
        if (role === 'student') {
          onWebRtcIceRef.current?.(null, data.candidate as RTCIceCandidateInit)
        } else if (role === 'lecturer') {
          onWebRtcIceRef.current?.(
            data.sender as string,
            data.candidate as RTCIceCandidateInit,
          )
        }
        break

      case 'ping':
        // 서버 핑 → 퐁 응답
        if (socketRef.current?.readyState === WebSocket.OPEN) {
          socketRef.current.send(JSON.stringify({ type: 'pong' }))
        }
        break

      case 'pong':
        // 핑퐁 응답
        break

      case 'student_count':
        // 현재 접속 중인 수강자 수
        setStudentCount(data.count as number)
        break

      case 'chat_message':
        // 채팅 메시지 수신
        addChatMessage({
          id: (data.id as string) || crypto.randomUUID(),
          sender: data.sender as 'lecturer' | 'student',
          name: data.name as string,
          text: data.text as string,
          timestamp: (data.timestamp as number) || Date.now(),
          studentId: data.student_id as string | undefined,
        })
        break

      case 'participants':
        // 참여자 목록
        setParticipants({
          lecturer: data.lecturer as { name: string; connected: boolean } | null,
          students: (data.students as { id: string; name: string }[]) || [],
        })
        break

      case 'lecture_title':
        // 강의 제목 (강사가 설정)
        setLectureTitle((data.title as string) || '')
        break

      case 'registered':
        // 역할 등록 확인
        console.log('[WebSocket] 역할 등록 완료:', data.role)
        break

      case 'cursor':
        // 강의자 커서 상태 수신 (수강자 전용, callback으로 DOM 직접 업데이트)
        if (role === 'student' && onCursorRef.current) {
          onCursorRef.current({
            x: data.x as number,
            y: data.y as number,
            visible: data.visible as boolean,
            color: data.color as string,
          })
        }
        break

      default:
        console.log('[WebSocket] 알 수 없는 메시지:', data.type)
    }
  }, [role, addSubtitle, setSlideId, setSlideStatus, setCurrentPage, setLectureStarted, setPaused, setPresentationMode, setCurrentScreen, setStudentCount, addChatMessage, setParticipants, setLectureTitle, loadSlidePages])

  const send = useCallback((data: object) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(data))
    } else {
      console.warn('[WebSocket] 연결되지 않음')
    }
  }, [])

  // 화면 공유 등 대용량 송신 시 백프레셔 판단용
  const getBufferedAmount = useCallback(() => {
    return socketRef.current?.bufferedAmount ?? 0
  }, [])

  const sendChat = useCallback((text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'chat_message', text: trimmed }))
    }
  }, [])

  const sendLectureTitle = useCallback((title: string) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'lecture_title', title }))
    }
  }, [])

  const sendLecturerName = useCallback((name: string) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'lecturer_name', name }))
    }
  }, [])

  const connect = useCallback(() => {
    if (socketRef.current?.readyState === WebSocket.OPEN ||
        socketRef.current?.readyState === WebSocket.CONNECTING) {
      return
    }

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = undefined
    }

    console.log('[WebSocket] 재연결 시도...')
    const socket = new WebSocket(url)

    socket.onopen = () => {
      console.log('[WebSocket] 연결됨')
      socket.send(JSON.stringify({ type: 'register', role, name: registerNameRef.current }))
      // 참여자 목록 최신화 요청 (register broadcast를 혹시라도 놓친 경우 대비)
      socket.send(JSON.stringify({ type: 'participants_request' }))
      console.log(`[WebSocket] 역할 등록: ${role} (이름: ${registerNameRef.current || '(기본값)'})`)
      setIsConnected(true)
      setConnected(true)
    }

    socket.onclose = () => {
      console.log('[WebSocket] 연결 종료')
      setIsConnected(false)
      setConnected(false)

      reconnectTimeoutRef.current = setTimeout(() => {
        connect()
      }, 3000)
    }

    socket.onerror = (error) => {
      console.error('[WebSocket] 에러:', error)
    }

    socket.onmessage = (event) => {
      try {
        const data: WebSocketMessage = JSON.parse(event.data)
        handleMessage(data)
      } catch (err) {
        console.error('[WebSocket] 메시지 파싱 실패:', err)
      }
    }

    socketRef.current = socket
  }, [url, role, setConnected, handleMessage])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }
    socketRef.current?.close()
    socketRef.current = null
    setIsConnected(false)
    setConnected(false)
  }, [setConnected])

  useEffect(() => {
    return () => {
      disconnect()
    }
  }, [disconnect])

  return {
    isConnected,
    connect,
    disconnect,
    send,
    sendChat,
    sendLectureTitle,
    sendLecturerName,
    getBufferedAmount,
  }
}
