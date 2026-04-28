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
  const [pickerSources, setPickerSources] = useState<ScreenSource[] | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)
  // Electron picker가 사용자 선택을 기다리는 동안 startCapture의 Promise를 보류시키는 resolver.
  const pickerResolveRef = useRef<((id: string | null) => void) | null>(null)

  const stopCapture = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null
      videoRef.current = null
    }
    setIsCapturing(false)
  }, [])

  const acquireStream = useCallback(async (): Promise<MediaStream | null> => {
    // Electron: desktopCapturer로 sources 가져온 뒤 picker 모달로 사용자 선택 대기.
    // 선택된 ID로 getUserMedia(chromeMediaSource: 'desktop')로 stream 획득.
    if (window.electron) {
      const sources = await window.electron.getScreenSources()
      const sourceId = await new Promise<string | null>((resolve) => {
        pickerResolveRef.current = resolve
        setPickerSources(sources)
      })
      if (!sourceId) return null
      return await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          mandatory: {
            chromeMediaSource: 'desktop',
            chromeMediaSourceId: sourceId,
          },
        } as unknown as MediaTrackConstraints,
      })
    }

    // 웹: 브라우저 기본 picker.
    return await navigator.mediaDevices.getDisplayMedia({
      video: {
        cursor: 'always',
        displaySurface: 'monitor',
      } as MediaTrackConstraints,
      audio: false,
    })
  }, [])

  const startCapture = useCallback(async () => {
    try {
      const stream = await acquireStream()
      if (!stream) return // 사용자가 picker에서 취소

      streamRef.current = stream

      const video = document.createElement('video')
      video.srcObject = stream
      video.autoplay = true
      video.muted = true
      video.playsInline = true
      videoRef.current = video

      const canvas = document.createElement('canvas')
      canvasRef.current = canvas

      await video.play()

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

      intervalRef.current = setInterval(() => {
        if (video.readyState === video.HAVE_ENOUGH_DATA) {
          ctx.drawImage(video, 0, 0, targetWidth, targetHeight)
          const imageData = canvas.toDataURL('image/jpeg', quality)
          const base64 = imageData.split(',')[1]
          onFrame?.(base64)
        }
      }, 1000 / frameRate)

      stream.getVideoTracks()[0].onended = () => {
        stopCapture()
      }

      setIsCapturing(true)
    } catch (err) {
      console.error('[ScreenCapture] 화면 공유 실패:', err)
      throw err
    }
  }, [acquireStream, onFrame, frameRate, maxWidth, quality, stopCapture])

  const selectPickerSource = useCallback((sourceId: string) => {
    setPickerSources(null)
    pickerResolveRef.current?.(sourceId)
    pickerResolveRef.current = null
  }, [])

  const cancelPicker = useCallback(() => {
    setPickerSources(null)
    pickerResolveRef.current?.(null)
    pickerResolveRef.current = null
  }, [])

  return {
    isCapturing,
    startCapture,
    stopCapture,
    pickerSources,
    selectPickerSource,
    cancelPicker,
  }
}
