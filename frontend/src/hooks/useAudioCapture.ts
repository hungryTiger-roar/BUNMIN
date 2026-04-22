import { useCallback, useEffect, useRef, useState } from 'react'

// window.vad가 script 태그로 로드된 @ricky0123/vad-web 전역 번들
declare global {
  interface Window {
    vad: { MicVAD: any }
  }
}

// 발화가 이 시간(ms)을 초과하면 강제로 잘라서 전송
const MAX_SPEECH_MS = 15000

interface UseAudioCaptureOptions {
  onAudioData: (audioBlob: Blob) => void
}

export function useAudioCapture({ onAudioData }: UseAudioCaptureOptions) {
  const [isCapturing, setIsCapturing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const vadRef = useRef<any>(null)
  const maxTimerRef = useRef<NodeJS.Timeout | null>(null)
  const onAudioDataRef = useRef(onAudioData)
  onAudioDataRef.current = onAudioData

  const clearMaxTimer = () => {
    if (maxTimerRef.current) {
      clearTimeout(maxTimerRef.current)
      maxTimerRef.current = null
    }
  }

  useEffect(() => {
    return () => {
      clearMaxTimer()
      vadRef.current?.destroy()
    }
  }, [])

  const startCapture = useCallback(async () => {
    try {
      setError(null)
      vadRef.current?.destroy()

      const { MicVAD } = window.vad
      const vad = await MicVAD.new({
        baseAssetPath: '/',
        onnxWASMBasePath: '/',
        // 묵음 1.2초 지속 시 발화 종료 판정 (기본 1.4초 → 강의 환경에 맞게 조정)
        redemptionMs: 1200,
        // pause() 시 현재 발화 오디오를 onSpeechEnd로 제출 (최대 길이 강제 전송에 사용)
        submitUserSpeechOnPause: true,
        onSpeechStart: () => {
          // 발화 시작 시 최대 길이 타이머 설정
          clearMaxTimer()
          maxTimerRef.current = setTimeout(() => {
            // MAX_SPEECH_MS 초과 시 pause → onSpeechEnd 트리거 → start 재개
            vadRef.current?.pause()
            vadRef.current?.start()
            console.log('[VAD] 최대 발화 길이 초과 → 강제 전송 후 재개')
          }, MAX_SPEECH_MS)
        },
        onSpeechEnd: (audio: Float32Array) => {
          clearMaxTimer()
          const wavBlob = float32ToWav(audio, 16000)
          onAudioDataRef.current(wavBlob)
        },
        onVADMisfire: () => {
          clearMaxTimer()
          console.log('[VAD] 오발화 감지 — 무시')
        },
      })

      vadRef.current = vad
      vad.start()
      setIsCapturing(true)
      console.log('[AudioCapture] Silero VAD 캡처 시작')
    } catch (err) {
      console.error('[AudioCapture] 시작 실패:', err)
      setError('마이크 접근 권한이 필요합니다.')
    }
  }, [])

  const stopCapture = useCallback(() => {
    clearMaxTimer()
    vadRef.current?.pause()
    setIsCapturing(false)
    console.log('[AudioCapture] 캡처 중지')
  }, [])

  return {
    isCapturing,
    error,
    startCapture,
    stopCapture,
  }
}

function float32ToWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)

  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeString(view, 8, 'WAVE')
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeString(view, 36, 'data')
  view.setUint32(40, samples.length * 2, true)

  let offset = 44
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true)
    offset += 2
  }

  return new Blob([buffer], { type: 'audio/wav' })
}

function writeString(view: DataView, offset: number, string: string) {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i))
  }
}
