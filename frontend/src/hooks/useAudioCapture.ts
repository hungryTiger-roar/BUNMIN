import { useCallback, useEffect, useRef, useState } from 'react'

// window.vad가 script 태그로 로드된 @ricky0123/vad-web 전역 번들
declare global {
  interface Window {
    vad: { MicVAD: any }
  }
}

interface UseAudioCaptureOptions {
  onAudioData: (audioBlob: Blob) => void
  /** streaming 모드 — backend ASR_STREAMING=true 시 register ack 로 ON.
   *  활성 시 발화 중 200ms 단위 PCM int16 frame 을 onAudioFrame 으로 흘려보내고,
   *  VAD onSpeechEnd 시 onSpeechEndFlush 1회 호출. 비활성 시 기존 onSpeechEnd → onAudioData 동작.
   */
  streamingMode?: boolean
  onAudioFrame?: (pcm: Int16Array, sentAt: number) => void
  onSpeechEndFlush?: () => void
}

export function useAudioCapture({
  onAudioData,
  streamingMode = false,
  onAudioFrame,
  onSpeechEndFlush,
}: UseAudioCaptureOptions) {
  const [isCapturing, setIsCapturing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const vadRef = useRef<any>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const gainNodeRef = useRef<GainNode | null>(null)
  const gainValueRef = useRef<number>(1)  // 0 = mute, 1 = unity, 2 = +6dB
  const keepAliveRef = useRef<NodeJS.Timeout | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  // streaming 모드 전용 — AudioWorklet 으로 PCM frame 을 추출.
  // streamingMode=false 면 worklet 자체를 만들지 않아 비활성과 동일 비용.
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)
  const muteSinkRef = useRef<GainNode | null>(null)
  const isSpeakingRef = useRef(false)

  const onAudioDataRef = useRef(onAudioData)
  onAudioDataRef.current = onAudioData
  const onAudioFrameRef = useRef(onAudioFrame)
  onAudioFrameRef.current = onAudioFrame
  const onSpeechEndFlushRef = useRef(onSpeechEndFlush)
  onSpeechEndFlushRef.current = onSpeechEndFlush
  const streamingModeRef = useRef(streamingMode)
  streamingModeRef.current = streamingMode

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
      if (workletNodeRef.current) {
        workletNodeRef.current.disconnect()
        workletNodeRef.current.port.onmessage = null
        workletNodeRef.current = null
      }
      if (muteSinkRef.current) {
        muteSinkRef.current.disconnect()
        muteSinkRef.current = null
      }
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
          isSpeakingRef.current = true
        },
        onSpeechEnd: (audio: Float32Array) => {
          isSpeakingRef.current = false
          // streaming 모드: blob 합성 안 하고, frame 송신은 worklet 이 isSpeakingRef
          // false 시 자동 중단되므로 여기선 flush 신호만 보내면 됨.
          if (streamingModeRef.current) {
            console.log('[VAD] 발화 끝 (streaming) → flush 신호')
            onSpeechEndFlushRef.current?.()
            return
          }

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
          isSpeakingRef.current = false
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

      // Streaming 모드: 200ms PCM int16 frame 추출용 AudioWorklet.
      // chunk 모드에서는 worklet 자체를 만들지 않아 기존 동작과 비용 동일.
      if (streamingMode) {
        try {
          await setupStreamingWorklet(audioContext, gainNode)
          console.log('[AudioCapture] streaming worklet 초기화 완료')
        } catch (err) {
          // worklet 미지원/실패 시 streaming flag 를 즉시 끔.
          // 안 그러면 onSpeechEnd 가 flush 신호만 보내고 chunk blob 송신 안 해서 자막 0건.
          console.error('[AudioCapture] streaming worklet 실패 → chunk 모드로 폴백:', err)
          streamingModeRef.current = false
        }
      }

      vadRef.current = vad
      vad.start()
      startKeepAlive(vad)
      setIsCapturing(true)
      console.log(`[AudioCapture] Silero VAD 캡처 시작 (mode=${streamingMode ? 'streaming' : 'chunk'})`)
      return true
    } catch (err) {
      console.error('[AudioCapture] 시작 실패:', err)
      setError('마이크 접근 권한이 필요합니다.')
      return false
    }
  }, [])

  // streaming 모드 전용 — AudioWorklet 으로 200ms PCM int16 frame 추출 후
  // isSpeakingRef true 일 때만 onAudioFrame 콜백 호출 (silence 시 GPU/네트워크 절약).
  // useCallback 으로 빼서 외부 useEffect 에서도 호출 가능 — register ack 가 마이크 시작
  // 후 늦게 도착하는 race 케이스 fix 용. ref 만 캡처하므로 deps 빈 배열로 stable.
  const setupStreamingWorklet = useCallback(async (audioContext: AudioContext, gainNode: GainNode) => {
    // worklet processor 인라인 정의 — 별도 파일/Vite 설정 없이 동작.
    // 16kHz mono 입력, 3200 sample(200ms) 마다 Int16 변환 후 main thread 로 postMessage.
    const workletSource = `
class StreamProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.frameSize = 3200  // 200ms @ 16kHz
    this.buffer = new Float32Array(this.frameSize)
    this.idx = 0
  }
  process(inputs) {
    const input = inputs[0] && inputs[0][0]
    if (!input) return true
    for (let i = 0; i < input.length; i++) {
      this.buffer[this.idx++] = input[i]
      if (this.idx >= this.frameSize) {
        const pcm = new Int16Array(this.frameSize)
        for (let j = 0; j < this.frameSize; j++) {
          const s = Math.max(-1, Math.min(1, this.buffer[j]))
          pcm[j] = s < 0 ? s * 0x8000 : s * 0x7fff
        }
        this.port.postMessage(pcm.buffer, [pcm.buffer])
        this.idx = 0
      }
    }
    return true
  }
}
registerProcessor('aunion-stream-processor', StreamProcessor)
    `
    const blob = new Blob([workletSource], { type: 'application/javascript' })
    const url = URL.createObjectURL(blob)
    try {
      await audioContext.audioWorklet.addModule(url)
    } finally {
      URL.revokeObjectURL(url)
    }
    const workletNode = new AudioWorkletNode(audioContext, 'aunion-stream-processor')
    workletNode.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
      // VAD 가 'speaking' 으로 표시한 동안만 backend 로 송신 — silence 절약.
      if (!isSpeakingRef.current) return
      if (!streamingModeRef.current) return
      const pcm = new Int16Array(e.data)
      onAudioFrameRef.current?.(pcm, Date.now())
    }
    // worklet 의 process() 가 audio engine 에 의해 pull 되도록 destination 까지 연결.
    // 단, audio echo 방지를 위해 muted gain sink 경유.
    const muteSink = audioContext.createGain()
    muteSink.gain.value = 0
    gainNode.connect(workletNode)
    workletNode.connect(muteSink)
    muteSink.connect(audioContext.destination)
    workletNodeRef.current = workletNode
    muteSinkRef.current = muteSink
  }, [])

  // race condition fix — startCapture 시점에 streamingMode=false 였다가 register ack
  // 으로 true 로 바뀌는 케이스. capture 가 이미 도는 상태에서 streamingMode 가 true 가
  // 되면 worklet 만 동적으로 add. 첫 mount 에 register ack 늦게 도착해 mode=chunk 로
  // 시작했어도 이 useEffect 가 메꿔줌.
  useEffect(() => {
    if (!isCapturing || !streamingMode) return
    if (workletNodeRef.current) return  // 이미 add 됨
    if (!audioContextRef.current || !gainNodeRef.current) return
    setupStreamingWorklet(audioContextRef.current, gainNodeRef.current)
      .then(() => console.log('[AudioCapture] streaming worklet 동적 add (race fix)'))
      .catch((err) => {
        console.error('[AudioCapture] streaming worklet 동적 add 실패 → chunk 모드 유지:', err)
        streamingModeRef.current = false
      })
  }, [streamingMode, isCapturing, setupStreamingWorklet])

  const stopCapture = useCallback(() => {
    if (workletNodeRef.current) {
      workletNodeRef.current.disconnect()
      workletNodeRef.current.port.onmessage = null
      workletNodeRef.current = null
    }
    if (muteSinkRef.current) {
      muteSinkRef.current.disconnect()
      muteSinkRef.current = null
    }
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
    isSpeakingRef.current = false
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