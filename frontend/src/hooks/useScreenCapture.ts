import { useCallback, useEffect, useRef, useState } from 'react'

interface UseScreenCaptureOptions {
  /** 캡처 해상도 상한 (track constraint) — 0이면 원본 그대로 */
  maxWidth?: number
  /** 캡처가 끝났을 때 호출 (UI 버튼 또는 브라우저 native stop 양쪽 다) */
  onCaptureEnd?: () => void
}

export function useScreenCapture(options: UseScreenCaptureOptions = {}) {
  const { maxWidth = 0, onCaptureEnd } = options

  const [isCapturing, setIsCapturing] = useState(false)
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [pickerSources, setPickerSources] = useState<ScreenSource[] | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const pickerResolveRef = useRef<((id: string | null) => void) | null>(null)

  const onCaptureEndRef = useRef(onCaptureEnd)
  useEffect(() => { onCaptureEndRef.current = onCaptureEnd }, [onCaptureEnd])

  const stopCapture = useCallback(() => {
    const wasCapturing = !!streamRef.current
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    setStream(null)
    setIsCapturing(false)
    if (wasCapturing) onCaptureEndRef.current?.()
  }, [])

  const acquireStream = useCallback(async (): Promise<MediaStream | null> => {
    // Electron: desktopCapturer로 sources 가져온 뒤 picker 모달로 사용자 선택 대기
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

    // 웹: 브라우저 기본 picker
    // surfaceSwitching: 'exclude' — Chrome이 다른 탭에 "이 탭을 대신 공유" 배너를 띄우는 동작 차단
    return await navigator.mediaDevices.getDisplayMedia({
      video: {
        cursor: 'always',
        displaySurface: 'monitor',
      } as MediaTrackConstraints,
      audio: false,
      surfaceSwitching: 'exclude',
    } as DisplayMediaStreamOptions & { surfaceSwitching?: 'include' | 'exclude' })
  }, [])

  const startCapture = useCallback(async () => {
    try {
      const newStream = await acquireStream()
      if (!newStream) return // 사용자가 picker에서 취소

      // 해상도 상한 적용 (인코딩 부담 ↓)
      if (maxWidth > 0) {
        const track = newStream.getVideoTracks()[0]
        if (track) {
          try {
            await track.applyConstraints({ width: { max: maxWidth } })
          } catch {
            // 일부 환경에서 화면 캡처 트랙은 width 제약 미지원 — 무시
          }
        }
      }

      streamRef.current = newStream
      setStream(newStream)

      // 사용자가 브라우저 native UI에서 "공유 중지" 누르면 트랙 ended → 정리
      newStream.getVideoTracks()[0].addEventListener('ended', () => {
        stopCapture()
      })

      setIsCapturing(true)
    } catch (err) {
      console.error('[ScreenCapture] 화면 공유 실패:', err)
      throw err
    }
  }, [acquireStream, maxWidth, stopCapture])

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
    stream,
    startCapture,
    stopCapture,
    pickerSources,
    selectPickerSource,
    cancelPicker,
  }
}
