/**
 * useTTS — piper-tts-web (메인 스레드, 내부 Worker로 비동기 처리)
 *
 * piper-tts-web은 내부적으로 OnnxWebWorker / PhonemizeWebWorker를 spawn하므로
 * 별도의 tts.worker.ts 없이 메인 스레드에서 직접 사용해야 한다.
 * (Worker 안에서 사용하면 pthread nested-worker 문제로 WASM init 실패)
 *
 * OOM 방지 전략:
 *   - audioLang 변경 시 이전 엔진 참조 해제 → 내부 Worker GC → WASM 메모리 해제
 *   - 새 엔진은 현재 언어 모델 하나만 warm-up → 메모리에 모델 1개만 유지
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { PiperWebEngine, OnnxWebRuntime, PhonemizeWebRuntime } from 'piper-tts-web'
import type { TranslationLang } from '@/stores/preferencesStore'

export type TTSMode   = 'piper' | null
export type TTSStatus = 'idle' | 'loading' | 'ready' | 'error'

// TranslationLang → Piper voice ID (https://huggingface.co/rhasspy/piper-voices)
// ko, both, off 는 Piper 미지원 → undefined (TTS 스킵)
const VOICE_MAP: Partial<Record<TranslationLang, string>> = {
  en: 'en_US-lessac-medium',
  de: 'de_DE-thorsten-medium',
  es: 'es_MX-ald-medium',
  ru: 'ru_RU-irina-medium',
}

export function useTTS(enabled = true, audioLang: TranslationLang = 'en') {
  const engineRef        = useRef<PiperWebEngine | null>(null)
  const audioCtxRef      = useRef<AudioContext | null>(null)
  const gainRef          = useRef<GainNode | null>(null)
  const gainValueRef     = useRef(0.7)
  const statusRef        = useRef<TTSStatus>('idle')
  const nextPlayTimeRef  = useRef(0)
  const activeSourcesRef = useRef<AudioBufferSourceNode[]>([])

  // 직렬 큐 — generate() 동시 호출 방지
  const busyRef            = useRef(false)
  const synthesizeQueueRef = useRef<Array<{ text: string; voice: string }>>([])
  const preloadQueueRef    = useRef<Array<{ lang: string; voice: string }>>([])
  const processNextRef     = useRef<() => void>(() => {})

  const [status,          setStatus]          = useState<TTSStatus>('idle')
  const [loadingProgress, setLoadingProgress] = useState(0)
  const [error,           setError]           = useState<string | null>(null)
  const [mode,            setMode]            = useState<TTSMode>(null)

  const updateStatus = useCallback((s: TTSStatus) => {
    statusRef.current = s
    setStatus(s)
  }, [])

  // audioLang 이 deps에 포함 → 언어 변경 시 cleanup → 새 엔진 생성 → WASM 메모리 초기화
  useEffect(() => {
    async function processNext() {
      if (busyRef.current || !engineRef.current) return

      const synTask = synthesizeQueueRef.current.shift()
      if (synTask) {
        busyRef.current = true
        try {
          const response = await engineRef.current.generate(synTask.text, synTask.voice, 0)
          const arrayBuffer = await response.file.arrayBuffer()

          const ctx = audioCtxRef.current
          if (ctx && ctx.state !== 'closed') {
            if (ctx.state === 'suspended') await ctx.resume()
            const audioBuffer = await ctx.decodeAudioData(arrayBuffer)
            const now = ctx.currentTime
            const startTime = nextPlayTimeRef.current < now + 0.05
              ? now + 0.05
              : nextPlayTimeRef.current
            nextPlayTimeRef.current = startTime + audioBuffer.duration

            const source = ctx.createBufferSource()
            source.buffer = audioBuffer
            source.connect(gainRef.current ?? ctx.destination)
            source.start(startTime)
            source.onended = () => {
              activeSourcesRef.current = activeSourcesRef.current.filter(s => s !== source)
            }
            activeSourcesRef.current.push(source)
          }
        } catch (err) {
          console.error('[TTS] synthesize 실패:', err)
        }
        busyRef.current = false
        processNext()
        return
      }

      const preTask = preloadQueueRef.current.shift()
      if (preTask) {
        busyRef.current = true
        try {
          await engineRef.current.generate('Hello.', preTask.voice, 0)
          console.log(`[TTS] ${preTask.lang} 모델 warm-up 완료`)
        } catch (err) {
          console.warn(`[TTS] ${preTask.lang} 모델 warm-up 실패:`, err)
        }
        busyRef.current = false
        processNext()
      }
    }

    processNextRef.current = processNext

    if (!enabled) return

    // 큐 초기화 (이전 언어 작업 제거)
    busyRef.current = false
    synthesizeQueueRef.current = []
    preloadQueueRef.current = []

    updateStatus('loading')

    const init = async () => {
      try {
        const engine = new PiperWebEngine({
          onnxRuntime: new OnnxWebRuntime(),
          phonemizeRuntime: new PhonemizeWebRuntime(),
        })
        engineRef.current = engine
        updateStatus('ready')
        setLoadingProgress(100)
        setMode('piper')

        // 현재 언어 모델만 warm-up (메모리에 모델 1개만 유지)
        const voice = VOICE_MAP[audioLang]
        if (voice) {
          preloadQueueRef.current.push({ lang: audioLang, voice })
          processNext()
          console.log(`[TTS] piper 초기화 완료, ${audioLang} 모델 warm-up 시작`)
        }
      } catch (err) {
        setError(String(err))
        updateStatus('error')
        console.error('[TTS] 초기화 실패:', err)
      }
    }

    init()

    return () => {
      // 이전 엔진 참조 해제 → 내부 OnnxWebWorker / PhonemizeWebWorker GC 대상
      // → WASM 힙 메모리 해제 → 새 언어 모델 로드 시 OOM 방지
      engineRef.current = null
      // AudioContext 는 세션 내내 유지 (unlockAudio에서 생성, 언어 변경과 무관)
    }
  }, [enabled, audioLang, updateStatus])

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
    const buf = audioCtxRef.current.createBuffer(1, 1, 22050)
    const src = audioCtxRef.current.createBufferSource()
    src.buffer = buf
    src.connect(gainRef.current ?? audioCtxRef.current.destination)
    src.start()
    console.log('[TTS] AudioContext unlock 완료')
  }, [])

  const setVolume = useCallback((vol: number, muted: boolean) => {
    const v = muted ? 0 : vol / 100
    gainValueRef.current = v
    if (gainRef.current) gainRef.current.gain.value = v
  }, [])

  const synthesize = useCallback((text: string, lang: TranslationLang = 'en') => {
    const voice = VOICE_MAP[lang]
    if (!voice) {
      console.warn('[TTS] 미지원 언어 스킵 — lang:', lang)
      return
    }
    if (!engineRef.current || statusRef.current !== 'ready') {
      console.warn('[TTS] synthesize 스킵 — status:', statusRef.current)
      return
    }
    if (!audioCtxRef.current) {
      console.warn('[TTS] synthesize 스킵 — AudioContext 없음 (unlockAudio 먼저 호출 필요)')
      return
    }
    nextPlayTimeRef.current = 0
    synthesizeQueueRef.current.push({ text, voice })
    processNextRef.current()
    console.log('[TTS] synthesize 요청:', lang, text.slice(0, 40))
  }, [])

  return { status, loadingProgress, error, mode, synthesize, unlockAudio, setVolume }
}
