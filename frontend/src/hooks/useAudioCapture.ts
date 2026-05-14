import { useCallback, useEffect, useRef, useState } from 'react'

// window.vad가 script 태그로 로드된 @ricky0123/vad-web 전역 번들
declare global {
  interface Window {
    vad: { MicVAD: any }
  }
}

/** 전역(window.vad 등)이 준비될 때까지 짧게 폴링. timeout(ms) 초과 시 undefined 반환. */
async function waitForGlobal<T>(get: () => T | undefined, timeoutMs: number): Promise<T | undefined> {
  const deadline = Date.now() + timeoutMs
  let v = get()
  while (!v && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 50))
    v = get()
  }
  return v || undefined
}

interface UseAudioCaptureOptions {
  onAudioData: (audioBlob: Blob) => void
}

export function useAudioCapture({
  onAudioData,
}: UseAudioCaptureOptions) {
  const [isCapturing, setIsCapturing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [micStream, setMicStream] = useState<MediaStream | null>(null)
  const vadRef = useRef<any>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const gainNodeRef = useRef<GainNode | null>(null)
  const gainValueRef = useRef<number>(1)  // 0 = mute, 1 = unity, 2 = +6dB
  const keepAliveRef = useRef<NodeJS.Timeout | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  // AudioWorklet — 200ms PCM int16 frame 추출. force-split 시 누적 프레임을 chunk 로 송출.
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)
  const muteSinkRef = useRef<GainNode | null>(null)
  const isSpeakingRef = useRef(false)
  // 한 발화의 최대 지속 시간 watchdog. 호흡 없이 길게 말하는 화자가
  // VAD 의 자연 onSpeechEnd 트리거 없이 한 덩어리 chunk 로 ASR 들어가는 걸 방지.
  const maxDurationTimerRef = useRef<number | null>(null)
  // 워크렛이 캡처한 프레임 누적 버퍼들. VAD 의 pause/start 가 발화 중간을 끊으면
  // 그 이후 음성을 놓치는 문제 (force-split 후 새 onSpeechStart 가 안 트리거되는 경우)
  // 를 우회하기 위해 워크렛 PCM 프레임을 우리가 직접 누적해 chunk 송출.
  //   prerollRef:    400ms 롤링 윈도우. 발화 시작 직전 음성 보존 (단어 첫 자모 자름 방지).
  //   chunkAccumRef: 현재 발화 누적 프레임. VAD onSpeechEnd 또는 force-split 시점에 송출 후 리셋.
  const prerollRef = useRef<Int16Array[]>([])
  const chunkAccumRef = useRef<Int16Array[]>([])

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

      // vad-bundle.min.js 는 index.html 에서 defer 로 로드되므로 (초기 렌더 차단 방지)
      // 마이크 시작이 아주 빠르면 아직 window.vad 가 없을 수 있다 — 짧게 폴링 대기.
      const vadGlobal = await waitForGlobal(() => window.vad, 5000)
      if (!vadGlobal) {
        setError('음성 인식 모듈 로드에 실패했습니다. 페이지를 새로고침해 주세요.')
        stream.getTracks().forEach((t) => t.stop())
        return false
      }
      const { MicVAD } = vadGlobal
      // 한 발화의 최대 지속 시간 — 이를 넘으면 강제 분할 (chunk 송출).
      // 강사가 호흡 없이 길게 말해도 worklet 누적 프레임을 직접 chunk 로 송출
      // (VAD 는 그대로 둠 → pause/start 사이 음성 손실 차단).
      // 8초로 짧게 — 긴 발화를 잘게 나눠 ASR/NMT/TTS 처리시간 분산을 줄이고
      // wall-clock delay (VITE_SYNC_DELAY_MS) 를 그만큼 짧게 잡을 수 있게 함.
      // trade-off: 문장 중간에서 끊기면 한→영 어순 차이로 약간의 오역 가능
      // (한국어 동사/부정/시제가 문장 끝). 대부분 발화는 8초 안에 자연 종료되어 영향 작음.
      const MAX_SPEECH_DURATION_MS = 8000
      // 발동 시 chunk 송출 헬퍼. 발화 도중 호출 시 누적 프레임만 송출, VAD 는 계속 듣는 중.
      const flushChunkAccum = (label: string) => {
        const frames = chunkAccumRef.current
        if (frames.length === 0) return
        chunkAccumRef.current = []  // 다음 chunk 누적 시작
        // 프레임 합산 — 너무 짧으면 노이즈 버스트 가드
        const totalSamples = frames.reduce((acc, f) => acc + f.length, 0)
        if (totalSamples < 4800) {  // 16kHz × 0.3s = 4800
          console.log(`[VAD] ${label} → 너무 짧음 (${totalSamples} samples), 스킵`)
          return
        }
        const float32 = new Float32Array(totalSamples)
        let off = 0
        for (const frame of frames) {
          for (let i = 0; i < frame.length; i++) {
            const s = frame[i]
            float32[off + i] = s < 0 ? s / 0x8000 : s / 0x7fff
          }
          off += frame.length
        }
        // RMS 에너지 가드 — 빈 구간이 흘러들어왔으면 스킵
        const rms = Math.sqrt(float32.reduce((sum: number, s: number) => sum + s * s, 0) / float32.length)
        if (rms < 0.005) {
          console.log(`[VAD] ${label} → 에너지 너무 낮음 (rms=${rms.toFixed(4)}), 스킵`)
          return
        }
        const wavBlob = float32ToWav(float32, 16000)
        console.log(`[VAD] ${label} → chunk 송출 (${(totalSamples / 16000).toFixed(2)}s)`)
        onAudioDataRef.current(wavBlob)
      }
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
        // false: 우리는 vad.pause() 안 부름. force-split 은 worklet 누적 프레임 직접 송출.
        // VAD 는 발화 중에도 끊김 없이 계속 들음 → 강제 분할 후 음성 손실 없음.
        submitUserSpeechOnPause: false,
        onSpeechStart: () => {
          console.log('[VAD] 발화 시작')
          isSpeakingRef.current = true
          // 발화 시작 직전 preroll 을 chunk 누적에 미리 넣음 — 단어 첫 자모 잘림 방지
          chunkAccumRef.current = [...prerollRef.current]
          // MAX_SPEECH_DURATION_MS 마다 chunk 강제 송출 (worklet 누적 프레임 사용, VAD 는 그대로 둠)
          const scheduleForceSplit = () => {
            maxDurationTimerRef.current = window.setTimeout(() => {
              if (!isSpeakingRef.current) return
              flushChunkAccum(`${MAX_SPEECH_DURATION_MS}ms 초과`)
              if (isSpeakingRef.current) scheduleForceSplit()  // 다음 chunk 도 같은 주기로
            }, MAX_SPEECH_DURATION_MS)
          }
          if (maxDurationTimerRef.current !== null) {
            window.clearTimeout(maxDurationTimerRef.current)
          }
          scheduleForceSplit()
        },
        onSpeechEnd: (_audio: Float32Array) => {
          isSpeakingRef.current = false
          // max-duration timer 정리
          if (maxDurationTimerRef.current !== null) {
            window.clearTimeout(maxDurationTimerRef.current)
            maxDurationTimerRef.current = null
          }
          // 누적 worklet 프레임을 chunk 로 송출. VAD 의 _audio 는 무시
          // (force-split 으로 이미 일부 전송됐을 수 있어 중복 위험). 가드는 flushChunkAccum 안에서 처리.
          flushChunkAccum('발화 끝')
        },
        onVADMisfire: () => {
          console.log('[VAD] 오발화 감지 — 무시')
          isSpeakingRef.current = false
        },
      })

      streamRef.current = stream
      setMicStream(stream)

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

      // AudioWorklet 셋업 — force-split 시 누적 프레임 송출에 사용.
      try {
        await setupStreamingWorklet(audioContext, gainNode)
        console.log('[AudioCapture] worklet 초기화 완료')
      } catch (err) {
        // worklet 실패하면 force-split 작동 안 함 — VAD 자연 onSpeechEnd 로 폴백.
        console.error('[AudioCapture] worklet 실패:', err)
      }

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

  // AudioWorklet 셋업 — 200ms PCM int16 frame 추출. prerollRef + chunkAccumRef 에 누적,
  // force-split / VAD onSpeechEnd 시점에 chunk 송출. ref 만 캡처하므로 deps 빈 배열로 stable.
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
    // force-split 발동 시 즉시 송출할 수 있도록 preroll 윈도우 크기.
    // 2 * 200ms = 400ms — 발화 시작 직전 음성 보존 (VAD preSpeechPadFrames 보완).
    const PREROLL_FRAMES_MAX = 2
    workletNode.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
      const pcm = new Int16Array(e.data)
      // preroll 항상 갱신 (롤링 윈도우) — 발화 안 할 때도 직전 200~400ms 보관.
      prerollRef.current.push(pcm)
      if (prerollRef.current.length > PREROLL_FRAMES_MAX) {
        prerollRef.current.shift()
      }
      // 발화 중이면 chunk 누적 — onSpeechEnd 또는 force-split 시점에 일괄 송출.
      if (isSpeakingRef.current) {
        chunkAccumRef.current.push(pcm)
      }
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
    // max-duration watchdog 정리 — leftover timer 가 destroy 후 발동 방지.
    if (maxDurationTimerRef.current !== null) {
      window.clearTimeout(maxDurationTimerRef.current)
      maxDurationTimerRef.current = null
    }
    // worklet 누적 / preroll 버퍼 비움 — 다음 캡처 세션에 leftover 영향 없음.
    prerollRef.current = []
    chunkAccumRef.current = []
    // pause가 아닌 destroy로 완전 정리 — 발화 중에도 즉시 마이크 OFF 보장
    vadRef.current?.destroy()
    vadRef.current = null
    isSpeakingRef.current = false
    setIsCapturing(false)
    setMicStream(null)
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
    micStream,
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