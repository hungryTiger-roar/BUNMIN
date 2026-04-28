/**
 * useTTS — 브라우저 WASM TTS 훅 (kokoro-js / onnxruntime-web)
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { GenerateOptions } from 'kokoro-js'

type VoiceId = NonNullable<GenerateOptions['voice']>

export type TTSStatus = 'idle' | 'loading' | 'ready' | 'error'

export function useTTS(enabled = true) {
  const workerRef   = useRef<Worker | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const gainRef     = useRef<GainNode | null>(null)
  const gainValueRef = useRef(0.7)   // 0.0 – 1.0, default 70 %
  const pendingRef  = useRef<Map<string, (samples: Float32Array, sr: number) => void>>(new Map())

  // statusRef: synthesize 내부에서 stale closure 없이 최신 상태 참조
  const statusRef = useRef<TTSStatus>('idle')

  const [status, setStatus] = useState<TTSStatus>('idle')
  const [loadingProgress, setLoadingProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const updateStatus = (s: TTSStatus) => {
    statusRef.current = s
    setStatus(s)
  }

  useEffect(() => {
    if (!enabled) return

    const worker = new Worker(
      new URL('../workers/tts.worker.ts', import.meta.url),
      { type: 'module' },
    )

    worker.onmessage = (e: MessageEvent) => {
      const { type } = e.data
      if (type === 'ready') {
        updateStatus('ready')
        setLoadingProgress(100)
        console.log('[TTS] 모델 로드 완료')
      } else if (type === 'loading') {
        updateStatus('loading')
        setLoadingProgress(e.data.progress as number)
      } else if (type === 'error') {
        updateStatus('error')
        setError(e.data.message as string)
        console.error('[TTS Worker]', e.data.message)
      } else if (type === 'audio') {
        const { id, samples, sampleRate } = e.data as {
          id: string; samples: Float32Array; sampleRate: number
        }
        pendingRef.current.get(id)?.(samples, sampleRate)
        pendingRef.current.delete(id)
      }
    }

    workerRef.current = worker
    updateStatus('loading')
    worker.postMessage({ type: 'init', dtype: 'q8' })

    return () => {
      worker.terminate()
      workerRef.current = null
      audioCtxRef.current?.close()
      audioCtxRef.current = null
    }
  }, [enabled])

  const unlockAudio = useCallback(() => {
    if (!audioCtxRef.current) {
      audioCtxRef.current = new AudioContext()
      gainRef.current = audioCtxRef.current.createGain()
      gainRef.current.gain.value = gainValueRef.current
      gainRef.current.connect(audioCtxRef.current.destination)
    }
    if (audioCtxRef.current.state === 'suspended') {
      audioCtxRef.current.resume()
    }
    // 1샘플 재생으로 Chrome 자동재생 잠금 해제
    const buf = audioCtxRef.current.createBuffer(1, 1, 22050)
    const src = audioCtxRef.current.createBufferSource()
    src.buffer = buf
    src.connect(gainRef.current ?? audioCtxRef.current.destination)
    src.start()
    console.log('[TTS] AudioContext unlock 완료')
  }, [])

  // vol: 0–100, muted: boolean
  const setVolume = useCallback((vol: number, muted: boolean) => {
    gainValueRef.current = muted ? 0 : vol / 100
    if (gainRef.current) {
      gainRef.current.gain.value = gainValueRef.current
    }
  }, [])

  // statusRef를 사용해 stale closure 없이 항상 최신 status 참조
  const synthesize = useCallback(async (text: string, voice: VoiceId = 'af_heart') => {
    if (!workerRef.current || statusRef.current !== 'ready') {
      console.warn('[TTS] synthesize 스킵 — status:', statusRef.current)
      return
    }
    if (!audioCtxRef.current) {
      console.warn('[TTS] synthesize 스킵 — AudioContext 없음 (unlockAudio 먼저 호출 필요)')
      return
    }

    const id = crypto.randomUUID()

    const samples = await new Promise<{ data: Float32Array; sr: number }>((resolve) => {
      pendingRef.current.set(id, (data, sr) => resolve({ data, sr }))
      workerRef.current!.postMessage({ type: 'synthesize', id, text, voice })
    })

    const ctx = audioCtxRef.current
    if (ctx.state === 'suspended') await ctx.resume()

    const audioBuffer = ctx.createBuffer(1, samples.data.length, samples.sr)
    audioBuffer.copyToChannel(new Float32Array(samples.data), 0)

    const source = ctx.createBufferSource()
    source.buffer = audioBuffer
    source.connect(gainRef.current ?? ctx.destination)
    source.start()
  }, []) // deps 없음 — statusRef/workerRef/audioCtxRef 모두 ref라 stale closure 없음

  return { status, loadingProgress, error, synthesize, unlockAudio, setVolume }
}
