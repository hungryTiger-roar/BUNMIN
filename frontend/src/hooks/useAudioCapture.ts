import { useCallback, useEffect, useRef, useState } from 'react'

// ── 에너지 기반 VAD 파라미터 ──────────────────────────────────────────────────
// Silero ML 모델 대신 RMS 에너지 임계값으로 발화 감지.
// 강의 환경(조용한 방, 마이크 근거리)에서 충분히 정확하며 모델 로딩/추론 비용 없음.
const ENERGY_THRESHOLD = 0.01  // RMS 임계값 (float32 정규화 기준) — 낮추면 민감, 높이면 둔감
const SILENCE_FRAMES   = 1     // 연속 묵음 프레임 수 → 발화 종료 (1프레임 = 200ms ≈ redemptionMs 150ms)

interface UseAudioCaptureOptions {
  onAudioData: (audioBlob: Blob) => void
  /** 스트리밍 모드: 발화 중 200ms 프레임마다 호출. 제공 시 onAudioData 대신 사용. */
  onAudioChunk?: (frame: Int16Array, speechStartAt: number) => void
  /** 스트리밍 모드: 발화 종료 시 호출. */
  onStreamEnd?: (sentAt: number) => void
}

export function useAudioCapture({
  onAudioData,
  onAudioChunk,
  onStreamEnd,
}: UseAudioCaptureOptions) {
  const [isCapturing, setIsCapturing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [micStream, setMicStream] = useState<MediaStream | null>(null)
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
  // 자연 종료 없이 한 덩어리 chunk 로 ASR 들어가는 걸 방지.
  const maxDurationTimerRef = useRef<number | null>(null)
  // 워크렛이 캡처한 프레임 누적 버퍼.
  //   prerollRef:    400ms 롤링 윈도우. 발화 시작 직전 음성 보존 (단어 첫 자모 자름 방지).
  //   chunkAccumRef: 현재 발화 누적 프레임. 발화 종료 또는 force-split 시점에 송출 후 리셋.
  const prerollRef = useRef<Int16Array[]>([])
  const chunkAccumRef = useRef<Int16Array[]>([])

  const onAudioDataRef = useRef(onAudioData)
  onAudioDataRef.current = onAudioData
  const onAudioChunkRef = useRef(onAudioChunk)
  onAudioChunkRef.current = onAudioChunk
  const onStreamEndRef = useRef(onStreamEnd)
  onStreamEndRef.current = onStreamEnd
  // 스트리밍 모드: 현재 발화 시작 wall clock
  const streamSpeechStartRef = useRef<number>(0)

  // AudioContext suspend 복구 — Chrome 무음 정책 / 백그라운드 탭 전환 시 자동 resume.
  const startKeepAlive = () => {
    keepAliveRef.current = setInterval(() => {
      const ctx = audioContextRef.current
      if (ctx?.state === 'suspended') {
        ctx.resume().then(() => console.log('[AudioCapture] AudioContext resumed'))
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
      stopKeepAlive()
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
      // 이전 세션 정리
      isSpeakingRef.current = false
      if (maxDurationTimerRef.current !== null) {
        window.clearTimeout(maxDurationTimerRef.current)
        maxDurationTimerRef.current = null
      }
      if (workletNodeRef.current) {
        workletNodeRef.current.disconnect()
        workletNodeRef.current.port.onmessage = null
        workletNodeRef.current = null
      }
      if (audioContextRef.current) {
        audioContextRef.current.close().catch(() => {})
        audioContextRef.current = null
      }
      stopStream()

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })

      // stream 진단 — getUserMedia 가 성공해도 Windows OS 권한 차단 시 track.muted=true 인
      // silent stream 을 반환하는 케이스가 있다. catch 로는 안 잡힘 → 별도 가드 필요.
      const audioTracks = stream.getAudioTracks()
      console.log('[AudioCapture] getUserMedia 성공:', {
        trackCount: audioTracks.length,
        trackLabel: audioTracks[0]?.label,
        trackMuted: audioTracks[0]?.muted,
        trackReadyState: audioTracks[0]?.readyState,
        trackEnabled: audioTracks[0]?.enabled,
      })

      const track = audioTracks[0]
      if (!track) {
        setError('마이크 오디오 트랙을 얻지 못했습니다. 마이크가 연결돼 있는지 확인해 주세요.')
        stream.getTracks().forEach((t) => t.stop())
        return false
      }

      if (track.muted) {
        setError(
          'Windows 마이크 권한이 차단된 것 같습니다. ' +
          '설정 → 개인 정보 및 보안 → 마이크 → "데스크톱 앱이 마이크에 액세스하도록 허용" 을 켜 주세요.'
        )
        stream.getTracks().forEach((t) => t.stop())
        return false
      }

      track.onmute   = () => console.warn('[AudioCapture] 마이크 track muted — OS 권한 차단 또는 silent stream 전환')
      track.onunmute = () => console.log('[AudioCapture] 마이크 track unmuted — 정상 데이터 흐름 복귀')
      track.onended  = () => console.warn('[AudioCapture] 마이크 track ended — 디바이스 제거 또는 OS 종료')

      const audioContext = new AudioContext({ sampleRate: 16000 })
      audioContextRef.current = audioContext

      // 한 발화의 최대 지속 시간 — 이를 넘으면 강제 분할 (chunk 송출).
      // 3초로 단축 — 청크 처리시간(ASR+NMT+TTS)을 줄여 neededDelay 를 8s 이하로 유지.
      const MAX_SPEECH_DURATION_MS = 1500

      // 발동 시 chunk 송출 헬퍼. 발화 도중 호출 시 누적 프레임만 송출, VAD 는 계속 듣는 중.
      const flushChunkAccum = (label: string) => {
        const frames = chunkAccumRef.current
        if (frames.length === 0) return
        chunkAccumRef.current = []
        const totalSamples = frames.reduce((acc, f) => acc + f.length, 0)
        if (totalSamples < 4800) {  // 16kHz × 0.3s = 4800
          console.log(`[EnergyVAD] ${label} → 너무 짧음 (${totalSamples} samples), 스킵`)
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
          console.log(`[EnergyVAD] ${label} → 에너지 너무 낮음 (rms=${rms.toFixed(4)}), 스킵`)
          return
        }
        const wavBlob = float32ToWav(float32, 16000)
        console.log(`[EnergyVAD] ${label} → chunk 송출 (${(totalSamples / 16000).toFixed(2)}s)`)
        onAudioDataRef.current(wavBlob)
      }

      // MAX_SPEECH_DURATION_MS 마다 chunk 강제 송출 (worklet 누적 프레임 사용)
      const scheduleForceSplit = () => {
        maxDurationTimerRef.current = window.setTimeout(() => {
          if (!isSpeakingRef.current) return
          flushChunkAccum(`${MAX_SPEECH_DURATION_MS}ms 초과`)
          if (isSpeakingRef.current) scheduleForceSplit()
        }, MAX_SPEECH_DURATION_MS)
      }

      streamRef.current = stream
      setMicStream(stream)

      // Web Audio API 그래프 구성
      const source = audioContext.createMediaStreamSource(stream)

      const gainNode = audioContext.createGain()
      gainNode.gain.value = gainValueRef.current
      gainNodeRef.current = gainNode
      source.connect(gainNode)

      const analyser = audioContext.createAnalyser()
      analyser.fftSize = 2048
      analyser.smoothingTimeConstant = 0.3
      analyserRef.current = analyser
      gainNode.connect(analyser)

      try {
        const isStreaming = !!onAudioChunk
        await setupStreamingWorklet(
          audioContext,
          gainNode,
          () => {
            if (!isStreaming) {
              // 배치 모드: force-split 타이머 시작
              scheduleForceSplit()
            }
            console.log('[EnergyVAD] 발화 시작')
          },
          () => {
            if (!isStreaming) {
              // 배치 모드: force-split 타이머 정리 + chunk 송출
              if (maxDurationTimerRef.current !== null) {
                window.clearTimeout(maxDurationTimerRef.current)
                maxDurationTimerRef.current = null
              }
              flushChunkAccum('발화 끝')
            }
            console.log('[EnergyVAD] 발화 끝')
          },
        )
        console.log('[AudioCapture] 에너지 기반 VAD 초기화 완료')
      } catch (err) {
        // worklet 실패하면 force-split 작동 안 함 — 에너지 VAD 전체 폴백 불가
        console.error('[AudioCapture] worklet 실패:', err)
      }

      startKeepAlive()
      setIsCapturing(true)
      console.log('[AudioCapture] 에너지 기반 VAD 캡처 시작')
      return true
    } catch (err) {
      console.error('[AudioCapture] 시작 실패:', err)
      setError('마이크 접근 권한이 필요합니다.')
      return false
    }
  }, [])

  // AudioWorklet 셋업 — 200ms PCM int16 frame 추출 + 에너지 기반 발화 감지.
  // prerollRef + chunkAccumRef 에 누적, 발화 종료 / force-split 시점에 chunk 송출.
  const setupStreamingWorklet = useCallback(async (
    audioContext: AudioContext,
    gainNode: GainNode,
    onSpeechStart: () => void,
    onSpeechEnd: () => void,
  ) => {
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
    // 발화 시작 직전 프레임 2개 보관 (400ms) — 단어 첫 자모 잘림 방지.
    const PREROLL_FRAMES_MAX = 2
    // 에너지 기반 VAD 상태 — 로컬 변수로 각 캡처 세션 독립.
    let silenceCount = 0

    workletNode.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
      const pcm = new Int16Array(e.data)

      // preroll 항상 갱신 (롤링 윈도우) — 발화 안 할 때도 직전 400ms 보관.
      prerollRef.current.push(pcm)
      if (prerollRef.current.length > PREROLL_FRAMES_MAX) prerollRef.current.shift()

      // RMS 에너지 계산 (int16 → 정규화 float32)
      let sumSq = 0
      for (let i = 0; i < pcm.length; i++) { const f = pcm[i] / 32768; sumSq += f * f }
      const rms = Math.sqrt(sumSq / pcm.length)

      const isStreaming = !!onAudioChunkRef.current

      if (rms > ENERGY_THRESHOLD) {
        silenceCount = 0
        if (!isSpeakingRef.current) {
          isSpeakingRef.current = true
          if (isStreaming) {
            // 스트리밍 모드: preroll 포함 발화 시작 즉시 전송
            streamSpeechStartRef.current = Date.now() - 200
            for (const prerollFrame of prerollRef.current) {
              onAudioChunkRef.current!(prerollFrame, streamSpeechStartRef.current)
            }
          } else {
            chunkAccumRef.current = [...prerollRef.current]
            onSpeechStart()
          }
        } else {
          if (isStreaming) {
            onAudioChunkRef.current!(pcm, streamSpeechStartRef.current)
          } else {
            chunkAccumRef.current.push(pcm)
          }
        }
      } else {
        if (isSpeakingRef.current) {
          // 묵음 프레임도 끝부분 보존 (자연스러운 발화 종료 음성)
          if (isStreaming) {
            onAudioChunkRef.current!(pcm, streamSpeechStartRef.current)
          } else {
            chunkAccumRef.current.push(pcm)
          }
          silenceCount++
          if (silenceCount >= SILENCE_FRAMES) {
            isSpeakingRef.current = false
            silenceCount = 0
            if (isStreaming) {
              onStreamEndRef.current?.(Date.now())
            } else {
              onSpeechEnd()
            }
          }
        }
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
    // 정리 순서: 만든 역순.
    isSpeakingRef.current = false

    // ① max-duration watchdog 정리
    if (maxDurationTimerRef.current !== null) {
      window.clearTimeout(maxDurationTimerRef.current)
      maxDurationTimerRef.current = null
    }

    // ② Web Audio 노드 disconnect
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

    // ③ AudioContext close
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {})
      audioContextRef.current = null
    }

    // ④ MediaStream tracks 정지
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }

    stopKeepAlive()
    prerollRef.current = []
    chunkAccumRef.current = []

    setIsCapturing(false)
    setMicStream(null)
    console.log('[AudioCapture] 캡처 중지')
  }, [])

  // 게인 설정 — 캡처 중이면 즉시 반영, 중지 상태면 다음 캡처 시작 시점에 적용
  const setGain = useCallback((gain: number) => {
    const clamped = Math.max(0, Math.min(4, gain))
    gainValueRef.current = clamped
    if (gainNodeRef.current && audioContextRef.current) {
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
