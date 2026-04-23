import { useCallback, useRef, useState } from 'react'

interface UseAudioCaptureOptions {
  onAudioData: (audioBlob: Blob) => void
  chunkInterval?: number
}

export function useAudioCapture({ onAudioData, chunkInterval = 2000 }: UseAudioCaptureOptions) {
  const [isCapturing, setIsCapturing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const audioContextRef = useRef<AudioContext | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Float32Array[]>([])
  const intervalRef = useRef<NodeJS.Timeout | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const gainNodeRef = useRef<GainNode | null>(null)
  const gainValueRef = useRef<number>(1)  // 0 = mute, 1 = unity, 2 = +6dB

  const startCapture = useCallback(async () => {
    try {
      setError(null)

      // 마이크 권한 요청
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 16000,
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

      const processor = audioContext.createScriptProcessor(4096, 1, 1)
      processorRef.current = processor

      // 실시간 레벨 측정용 analyser (게인 적용 후 기준)
      const analyser = audioContext.createAnalyser()
      analyser.fftSize = 2048
      analyser.smoothingTimeConstant = 0.3
      analyserRef.current = analyser
      gainNode.connect(analyser)

      // 오디오 데이터 수집 (게인 적용 후 기준)
      processor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0)
        chunksRef.current.push(new Float32Array(inputData))
      }

      gainNode.connect(processor)
      processor.connect(audioContext.destination)

      // 주기적으로 오디오 전송
      intervalRef.current = setInterval(() => {
        if (chunksRef.current.length > 0) {
          const audioData = mergeChunks(chunksRef.current)
          const wavBlob = createWavBlob(audioData, 16000)
          onAudioData(wavBlob)
          chunksRef.current = []
        }
      }, chunkInterval)

      setIsCapturing(true)
      console.log('[AudioCapture] 캡처 시작 (PCM/WAV)')
    } catch (err) {
      console.error('[AudioCapture] 시작 실패:', err)
      setError('마이크 접근 권한이 필요합니다.')
    }
  }, [onAudioData, chunkInterval])

  const stopCapture = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }

    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current = null
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

    chunksRef.current = []
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

// Float32Array 청크들을 하나로 합치기
function mergeChunks(chunks: Float32Array[]): Float32Array {
  const totalLength = chunks.reduce((acc, chunk) => acc + chunk.length, 0)
  const result = new Float32Array(totalLength)
  let offset = 0
  for (const chunk of chunks) {
    result.set(chunk, offset)
    offset += chunk.length
  }
  return result
}

// Float32Array를 WAV Blob으로 변환
function createWavBlob(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)

  // WAV 헤더 작성
  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeString(view, 8, 'WAVE')
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true) // fmt chunk size
  view.setUint16(20, 1, true) // audio format (PCM)
  view.setUint16(22, 1, true) // num channels
  view.setUint32(24, sampleRate, true) // sample rate
  view.setUint32(28, sampleRate * 2, true) // byte rate
  view.setUint16(32, 2, true) // block align
  view.setUint16(34, 16, true) // bits per sample
  writeString(view, 36, 'data')
  view.setUint32(40, samples.length * 2, true)

  // PCM 데이터 작성 (Float32 -> Int16)
  let offset = 44
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true)
    offset += 2
  }

  return new Blob([buffer], { type: 'audio/wav' })
}

function writeString(view: DataView, offset: number, string: string) {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i))
  }
}
