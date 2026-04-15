import { useCallback, useRef, useState } from 'react'

interface UseScreenCaptureOptions {
  onScreenCapture: (imageData: string) => void
  captureInterval?: number
  quality?: number
}

export function useScreenCapture({
  onScreenCapture,
  captureInterval = 1000,
  quality = 0.7,
}: UseScreenCaptureOptions) {
  const [isSharing, setIsSharing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const streamRef = useRef<MediaStream | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  const startCapture = useCallback(async () => {
    try {
      setError(null)

      // 화면 공유 권한 요청
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: false,
      })

      streamRef.current = stream

      // 비디오 엘리먼트 생성
      const video = document.createElement('video')
      video.srcObject = stream
      video.autoplay = true
      video.muted = true
      videoRef.current = video

      // 캔버스 생성
      const canvas = document.createElement('canvas')
      canvasRef.current = canvas

      // 비디오 로드 후 캡처 시작
      video.onloadedmetadata = () => {
        canvas.width = video.videoWidth
        canvas.height = video.videoHeight

        // 주기적 캡처
        intervalRef.current = setInterval(() => {
          captureFrame()
        }, captureInterval)

        setIsSharing(true)
        console.log('[ScreenCapture] 화면 공유 시작')
      }

      // 사용자가 공유 중지 시
      stream.getVideoTracks()[0].onended = () => {
        stopCapture()
      }

      await video.play()
    } catch (err) {
      console.error('[ScreenCapture] 시작 실패:', err)
      setError('화면 공유 권한이 필요합니다.')
    }
  }, [captureInterval])

  const captureFrame = useCallback(() => {
    const video = videoRef.current
    const canvas = canvasRef.current

    if (!video || !canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // 현재 프레임 캡처
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

    // JPEG로 변환
    const imageData = canvas.toDataURL('image/jpeg', quality)

    // base64 데이터 부분만 추출
    const base64Data = imageData.split(',')[1]
    onScreenCapture(base64Data)
  }, [onScreenCapture, quality])

  const stopCapture = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }

    videoRef.current = null
    canvasRef.current = null

    setIsSharing(false)
    console.log('[ScreenCapture] 화면 공유 중지')
  }, [])

  // 미리보기용 스트림 반환
  const getPreviewStream = useCallback(() => {
    return streamRef.current
  }, [])

  return {
    isSharing,
    error,
    startCapture,
    stopCapture,
    getPreviewStream,
  }
}
