import { useCallback, useEffect, useRef, useState } from 'react'
import { useLectureStore } from '@/stores/lectureStore'

interface WebSocketMessage {
  type: string
  [key: string]: unknown
}

type Role = 'lecturer' | 'student'

export function useWebSocket(url: string, role: Role = 'student') {
  const socketRef = useRef<WebSocket | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [isAudioUnlocked, setIsAudioUnlocked] = useState(false)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>()
  const audioContextRef = useRef<AudioContext | null>(null)

  const { addSubtitle, setOverlayItems, setCurrentScreen, setConnected } = useLectureStore()

  const connect = useCallback(() => {
    // 이미 연결 중이거나 연결된 경우 무시
    if (socketRef.current?.readyState === WebSocket.OPEN ||
        socketRef.current?.readyState === WebSocket.CONNECTING) {
      return
    }

    // 기존 재연결 타이머 취소
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = undefined
    }

    const socket = new WebSocket(url)

    socket.onopen = () => {
      console.log('[WebSocket] 연결됨')
      // 역할 등록 메시지 전송
      socket.send(JSON.stringify({ type: 'register', role }))
      console.log(`[WebSocket] 역할 등록: ${role}`)
      setIsConnected(true)
      setConnected(true)
    }

    socket.onclose = () => {
      console.log('[WebSocket] 연결 종료')
      setIsConnected(false)
      setConnected(false)

      // 3초 후 재연결 시도
      reconnectTimeoutRef.current = setTimeout(() => {
        console.log('[WebSocket] 재연결 시도...')
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
  }, [url, role, setConnected])

  const handleMessage = (data: WebSocketMessage) => {
    switch (data.type) {
      case 'transcription':
        // 번역 결과 수신
        addSubtitle({
          original: data.original as string,
          translated: data.translated as string,
          timestamp: Date.now(),
        })

        // 오디오 재생 (잠금 해제된 경우에만)
        if (data.audio && isAudioUnlocked) {
          playAudio(data.audio as string)
        }
        break

      case 'screen':
        // 화면 공유 데이터 수신
        setCurrentScreen(data.data as string)
        break

      case 'overlay':
        // 화면 오버레이 데이터
        setOverlayItems(data.items as never[])
        break

      case 'pong':
        // 핑퐁 응답
        break

      case 'registered':
        // 역할 등록 확인
        console.log('[WebSocket] 역할 등록 완료:', data.role)
        break

      default:
        console.log('[WebSocket] 알 수 없는 메시지:', data.type)
    }
  }

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
    })

    audio.onended = () => {
      URL.revokeObjectURL(audioUrl)
    }
  }

  const send = useCallback((data: object) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(data))
    } else {
      console.warn('[WebSocket] 연결되지 않음')
    }
  }, [])

  // 오디오 재생 잠금 해제 (사용자 상호작용 필요)
  const unlockAudio = useCallback(() => {
    if (!audioContextRef.current) {
      audioContextRef.current = new AudioContext()
    }
    // 무음 재생으로 오디오 잠금 해제
    const buffer = audioContextRef.current.createBuffer(1, 1, 22050)
    const source = audioContextRef.current.createBufferSource()
    source.buffer = buffer
    source.connect(audioContextRef.current.destination)
    source.start()
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
