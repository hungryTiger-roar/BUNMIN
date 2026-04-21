import { useCallback, useRef, useState } from 'react'

interface UseScreenCaptureOptions {
  onFrame?: (imageData: string) => void
  frameRate?: number
  maxWidth?: number  // 최대 너비 (리사이즈)
  quality?: number   // JPEG 품질 (0.1 ~ 1.0)
}

export function useScreenCapture(options: UseScreenCaptureOptions = {}) {
  const {
    onFrame,
    frameRate = 10,      // 10 FPS (더 부드럽게)
    maxWidth = 0,        // 0 = 리사이즈 안함 (원본 해상도)
    quality = 0.6        // JPEG 품질
  } = options
  const [isCapturing, setIsCapturing] = useState(false)
  const streamRef = useRef<MediaStream | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  const startCapture = useCallback(async () => {
    try {
      // 화면 공유 요청
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          cursor: 'always',
          displaySurface: 'monitor',
        } as MediaTrackConstraints,
        audio: false,
      })

      streamRef.current = stream

      // 비디오 엘리먼트 생성
      const video = document.createElement('video')
      video.srcObject = stream
      video.autoplay = true
      video.muted = true
      video.playsInline = true
      videoRef.current = video

      // 캔버스 생성
      const canvas = document.createElement('canvas')
      canvasRef.current = canvas

      // 비디오 재생 시작
      await video.play()

      // 리사이즈 계산 (maxWidth > 0일 때만)
      let targetWidth = video.videoWidth
      let targetHeight = video.videoHeight

      if (maxWidth > 0 && targetWidth > maxWidth) {
        const scale = maxWidth / targetWidth
        targetWidth = maxWidth
        targetHeight = Math.round(video.videoHeight * scale)
      }

      canvas.width = targetWidth
      canvas.height = targetHeight

      const ctx = canvas.getContext('2d')
      if (!ctx) return

      // 주기적으로 프레임 캡처
      intervalRef.current = setInterval(() => {
        if (video.readyState === video.HAVE_ENOUGH_DATA) {
          // 리사이즈하여 그리기
          ctx.drawImage(video, 0, 0, targetWidth, targetHeight)
          const imageData = canvas.toDataURL('image/jpeg', quality)
          // data:image/jpeg;base64, 부분 제거
          const base64 = imageData.split(',')[1]
          onFrame?.(base64)
        }
      }, 1000 / frameRate)

      // 사용자가 공유 중지했을 때
      stream.getVideoTracks()[0].onended = () => {
        stopCapture()
      }

      setIsCapturing(true)
    } catch (err) {
      console.error('[ScreenCapture] 화면 공유 실패:', err)
      throw err
    }
  }, [onFrame, frameRate])

  const stopCapture = useCallback(() => {
    // 인터벌 정리
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }

    // 스트림 정리
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop())
      streamRef.current = null
    }

    // 비디오 정리
    if (videoRef.current) {
      videoRef.current.srcObject = null
      videoRef.current = null
    }

    setIsCapturing(false)
  }, [])

  return {
    isCapturing,
    startCapture,
    stopCapture,
  }
}
