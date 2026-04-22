import { useCallback, useEffect, useRef, useState } from 'react'
import { useLectureStore } from '@/stores/lectureStore'
import { API_BASE } from '@/lib/api'

interface WebSocketMessage {
  type: string
  [key: string]: unknown
}

type Role = 'lecturer' | 'student'

export function useWebSocket(url: string, role: Role = 'student') {
  const socketRef = useRef<WebSocket | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [isAudioUnlocked, setIsAudioUnlocked] = useState(false)
  const isAudioUnlockedRef = useRef(false)  // stale closure 방지
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>()
  const audioContextRef = useRef<AudioContext | null>(null)

  const {
    addSubtitle,
    setConnected,
    setSlideId,
    setSlideStatus,
    setSlidePages,
    setCurrentPage,
    setLectureStarted,
    setPaused,
    setPresentationMode,
    setCurrentScreen,
    setStudentCount,
    studentName,
  } = useLectureStore()

  const studentNameRef = useRef(studentName)
  useEffect(() => { studentNameRef.current = studentName }, [studentName])

  // 슬라이드 페이지 로드
  const loadSlidePages = useCallback(async (slideId: string) => {
    try {
      const response = await fetch(`${API_BASE}/slides/pages/${slideId}`)
      if (!response.ok) throw new Error('Failed to load slides')

      const data = await response.json()
      setSlidePages(data.pages)
      setSlideStatus('ready')
    } catch (err) {
      console.error('[WebSocket] 슬라이드 로드 실패:', err)
    }
  }, [setSlidePages, setSlideStatus])

  const handleMessage = useCallback((data: WebSocketMessage) => {
    switch (data.type) {
      case 'transcription': {
        // 번역 결과 수신
        const outputTime = Date.now()
        const inputTime = data.sentAt as number | undefined
        addSubtitle({
          original: data.original as string,
          translated: data.translated as string,
          timestamp: outputTime,
          inputTime,
        })

        // 오디오 재생 (잠금 해제된 경우에만)
        if (data.audio && isAudioUnlockedRef.current) {
          playAudio(data.audio as string)
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

      case 'lecture_end':
        // 강의 종료
        setLectureStarted(false)
        setPaused(false)
        setCurrentScreen(null)
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
        // 화면 공유 프레임 수신
        if (role === 'student') {
          const imageData = data.image as string
          setCurrentScreen(imageData)
          setPresentationMode('screen')
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

      case 'registered':
        // 역할 등록 확인
        console.log('[WebSocket] 역할 등록 완료:', data.role)
        break

      default:
        console.log('[WebSocket] 알 수 없는 메시지:', data.type)
    }
  }, [role, addSubtitle, setSlideId, setSlideStatus, setCurrentPage, setLectureStarted, setPaused, setPresentationMode, setCurrentScreen, loadSlidePages])

  const send = useCallback((data: object) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(data))
    } else {
      console.warn('[WebSocket] 연결되지 않음')
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
      socket.send(JSON.stringify({ type: 'register', role, name: studentNameRef.current }))
      console.log(`[WebSocket] 역할 등록: ${role}`)
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

  const playAudio = (base64Audio: string) => {
    const audioData = atob(base64Audio)
    const arrayBuffer = new ArrayBuffer(audioData.length)
    const view = new Uint8Array(arrayBuffer)

    for (let i = 0; i < audioData.length; i++) {
      view[i] = audioData.charCodeAt(i)
    }

    const blob = new Blob([arrayBuffer], { type: 'audio/wav' })
    const audioUrl = URL.createObjectURL(blob)
    const audio = new Audio(audioUrl)

    audio.play().catch((err) => {
      console.error('[Audio] 재생 실패:', err)
      URL.revokeObjectURL(audioUrl)
    })

    audio.onended = () => URL.revokeObjectURL(audioUrl)
    audio.onerror = () => URL.revokeObjectURL(audioUrl)
  }

  const unlockAudio = useCallback(() => {
    if (!audioContextRef.current) {
      audioContextRef.current = new AudioContext()
    }
    const buffer = audioContextRef.current.createBuffer(1, 1, 22050)
    const source = audioContextRef.current.createBufferSource()
    source.buffer = buffer
    source.connect(audioContextRef.current.destination)
    source.start()
    isAudioUnlockedRef.current = true
    setIsAudioUnlocked(true)
    console.log('[Audio] 재생 잠금 해제됨')
  }, [])

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
      audioContextRef.current?.close()
      audioContextRef.current = null
    }
  }, [disconnect])

  return {
    isConnected,
    isAudioUnlocked,
    connect,
    disconnect,
    send,
    unlockAudio,
  }
}
