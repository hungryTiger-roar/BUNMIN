import { useCallback, useEffect, useRef, useState } from 'react'

// window.vad가 script 태그로 로드된 @ricky0123/vad-web 전역 번들
declare global {
  interface Window {
    vad: { MicVAD: any }
  }
}

interface UseAudioCaptureOptions {
  onAudioData: (audioBlob: Blob) => void
}

export function useAudioCapture({ onAudioData }: UseAudioCaptureOptions) {
  const [isCapturing, setIsCapturing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const vadRef = useRef<any>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const gainNodeRef = useRef<GainNode | null>(null)
  const gainValueRef = useRef<number>(1)  // 0 = mute, 1 = unity, 2 = +6dB
  const keepAliveRef = useRef<NodeJS.Timeout | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)

  const onAudioDataRef = useRef(onAudioData)
  onAudioDataRef.current = onAudioData

  // AudioContext가 suspend되면 자동 resume (Chrome 무음 정책 대응)
  const startKeepAlive = (vad: any) => {
    keepAliveRef.current = setInterval(() => {
      const ctx = vad?.audioContext
      if (ctx?.state === 'suspended') {
        ctx.resume().then(() => console.log('[VAD] AudioContext resumed'))
      }
    }, 5000)
  }

  const stopKeepAlive = () => {
    if (keepAliveRef.current) {
      clearInterval(keepAliveRef.current)
      keepAliveRef.current = null
    }
  }

  const stopStream = () => {
    streamRef.current?.getTracks().forEach(track => track.stop())
    streamRef.current = null
  }

  useEffect(() => {
    return () => {
      // 언마운트 시 모든 오디오 리소스 완전 정리 — AudioContext 누수 방지
      // (강의 종료 → 새 강의 시작 사이클에서 마이크 재초기화 실패하는 문제 해결)
      stopKeepAlive()
      vadRef.current?.destroy()
      vadRef.current = null
      stopStream()
      if (analyserRef.current) {
        analyserRef.current.disconnect()
        analyserRef.current = null
      }
      if (gainNodeRef.current) {
        gainNodeRef.current.disconnect()
        gainNodeRef.current = null
      }
      if (audioContextRef.current) {
        audioContextRef.current.close().catch(() => {})
        audioContextRef.current = null
      }
    }
  }, [])

  const startCapture = useCallback(async (): Promise<boolean> => {
    try {
      setError(null)
      vadRef.current?.destroy()
      vadRef.current = null
      stopStream()

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })

      const { MicVAD } = window.vad
      const vad = await MicVAD.new({
        stream,
        baseAssetPath: '/',
        onnxWASMBasePath: '/',
        ortConfig: (ort: any) => {
          ort.env.wasm.numThreads = 1
        },
        // 묵음 0.3초 지속 시 발화 종료 판정 — 600/400 모두 빠른 호흡 화자에서 번들링 발생
        // 종결어미("~습니다.") 잘릴 위험 ↑ 하지만 빠른 분리 우선
        redemptionMs: 300,
        // 발화 감지 직전 프레임 2개 포함 (발화 시작 잘림 방지, 1프레임 ≈ 96ms)
        preSpeechPadFrames: 2,
        submitUserSpeechOnPause: false,
        onSpeechStart: () => {
          console.log('[VAD] 발화 시작')
        },
        onSpeechEnd: (audio: Float32Array) => {

          // 최소 발화 길이: 0.3초 미만은 노이즈 버스트 (16000Hz * 0.3s = 4800)
          if (audio.length < 4800) {
            console.log('[VAD] 발화 너무 짧음 → 노이즈로 판단, 스킵')
            return
          }

          // RMS 에너지: 너무 조용하면 빈 구간이 VAD를 통과한 것
          const rms = Math.sqrt(audio.reduce((sum: number, s: number) => sum + s * s, 0) / audio.length)
          if (rms < 0.005) {
            console.log(`[VAD] 에너지 너무 낮음 (rms=${rms.toFixed(4)}) → 스킵`)
            return
          }

          const wavBlob = float32ToWav(audio, 16000)
          onAudioDataRef.current(wavBlob)
        },
        onVADMisfire: () => {
          console.log('[VAD] 오발화 감지 — 무시')
        },
      })

      streamRef.current = stream

      // Web Audio API 설정
      const audioContext = new AudioContext({ sampleRate: 16000 })
      audioContextRef.current = audioContext

      const source = audioContext.createMediaStreamSource(stream)

      // 입력 게인 제어 — 사용자가 조절하는 볼륨이 analyser + ASR 양쪽에 모두 반영됨
      const gainNode = audioContext.createGain()
      gainNode.gain.value = gainValueRef.current
      gainNodeRef.current = gainNode
      source.connect(gainNode)

      // 실시간 레벨 측정용 analyser (게인 적용 후 기준)
      const analyser = audioContext.createAnalyser()
      analyser.fftSize = 2048
      analyser.smoothingTimeConstant = 0.3
      analyserRef.current = analyser
      gainNode.connect(analyser)

      vadRef.current = vad
      vad.start()
      startKeepAlive(vad)
      setIsCapturing(true)
      console.log('[AudioCapture] Silero VAD 캡처 시작')
      return true
    } catch (err) {
      console.error('[AudioCapture] 시작 실패:', err)
      setError('마이크 접근 권한이 필요합니다.')
      return false
    }
  }, [])

  const stopCapture = useCallback(() => {
    if (analyserRef.current) {
      analyserRef.current.disconnect()
      analyserRef.current = null
    }

    if (gainNodeRef.current) {
      gainNodeRef.current.disconnect()
      gainNodeRef.current = null
    }

    if (audioContextRef.current) {
      audioContextRef.current.close()
      audioContextRef.current = null
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }

    stopKeepAlive()
    // pause가 아닌 destroy로 완전 정리 — 발화 중에도 즉시 마이크 OFF 보장
    vadRef.current?.destroy()
    vadRef.current = null
    setIsCapturing(false)
    console.log('[AudioCapture] 캡처 중지')
  }, [])

  // 게인 설정 — 캡처 중이면 즉시 반영, 중지 상태면 다음 캡처 시작 시점에 적용
  const setGain = useCallback((gain: number) => {
    const clamped = Math.max(0, Math.min(4, gain))  // 0 ~ 4x 범위 안전하게 클램프
    gainValueRef.current = clamped
    if (gainNodeRef.current && audioContextRef.current) {
      // 부드러운 전환으로 클릭/팝 잡음 방지
      gainNodeRef.current.gain.setTargetAtTime(
        clamped,
        audioContextRef.current.currentTime,
        0.02,
      )
    }
  }, [])

  return {
    isCapturing,
    error,
    startCapture,
    stopCapture,
    analyserRef,
    setGain,
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