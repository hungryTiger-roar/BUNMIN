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
  const isAudioUnlockedRef = useRef(false)  // stale closure 방지
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>()
  const audioContextRef = useRef<AudioContext | null>(null)

  const { addSubtitle, setOverlayItems, setCurrentScreen, setConnected } = useLectureStore()

  const send = useCallback((data: object) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(data))
    } else {
      console.warn('[WebSocket] 연결되지 않음')
    }
  }, [])

  const handleMessage = useCallback((data: WebSocketMessage) => {
    switch (data.type) {
      case 'transcription':
        addSubtitle({
          original: data.original as string,
          translated: data.translated as string,
          timestamp: Date.now(),
        })
        if (data.audio && isAudioUnlockedRef.current) {
          playAudio(data.audio as string)
        }
        break

      case 'screen':
        setCurrentScreen(data.data as string)
        break

      case 'overlay':
        setOverlayItems(data.items as never[])
        break

      case 'ping':
        send({ type: 'pong' })
        break

      case 'slide_state':
        console.log('[WebSocket] 슬라이드 상태:', data.slide_id, 'page:', data.page)
        break

      case 'pong':
        break

      case 'registered':
        console.log('[WebSocket] 역할 등록 완료:', data.role)
        break

      default:
        console.log('[WebSocket] 알 수 없는 메시지:', data.type)
    }
  }, [addSubtitle, setOverlayItems, setCurrentScreen, send])

  const connect = useCallback(() => {
    if (socketRef.current?.readyState === WebSocket.OPEN ||
        socketRef.current?.readyState === WebSocket.CONNECTING) {
      return
    }

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = undefined
    }

    const socket = new WebSocket(url)

    socket.onopen = () => {
      console.log('[WebSocket] 연결됨')
      socket.send(JSON.stringify({ type: 'register', role }))
      console.log(`[WebSocket] 역할 등록: ${role}`)
      setIsConnected(true)
      setConnected(true)
    }

    socket.onclose = () => {
      console.log('[WebSocket] 연결 종료')
      setIsConnected(false)
      setConnected(false)

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
    })

    audio.onended = () => {
      URL.revokeObjectURL(audioUrl)
    }
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
