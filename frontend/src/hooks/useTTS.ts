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
 *
 * 재생 정책 — 가속+선점 하이브리드:
 *   새 발화가 도착했을 때 현재 재생 중인 발화의 남은 시간을 보고:
 *     - 0.5초 미만 남음            → 자연 종료 후 새거 큐잉 (방해 없음)
 *     - 1.2x 가속해서 1.5초 이내 종료 가능 → 가속 적용 후 큐잉 (학습 청취에 부담 없는 속도)
 *     - 가속해도 안 됨             → 8ms fade-out + 즉시 새거 시작 (실시간성 보장)
 *   직렬 큐가 generate() 만 직렬화하므로, generate 진행 중에 새 발화가 오면
 *   seqRef 비교로 stale 결과를 drop 한다. (선점 시 진행 중 generate 도 무효화)
 *
 * 로딩/캐시 최적화:
 *   1) WebGPU 'high-performance' 명시 — dGPU+iGPU 동시 보유 시 dGPU 우선
 *   2) 엔진 초기화와 병행해 voice 파일 prefetch — 첫 발화 latency ↓
 *   3) numThreads = hardwareConcurrency (piper 기본) + crossOriginIsolated 검증
 *   4) HTTP cache: 'force-cache' — 강의 재진입 시 voice 재다운로드 0
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { PiperWebEngine, OnnxWebRuntime, OnnxWebGPURuntime, PhonemizeWebRuntime } from 'piper-tts-web'
import * as ortWebGPU from 'onnxruntime-web/webgpu'
import type { TranslationLang } from '@/stores/preferencesStore'

// piper-tts-web v1.1.2 의 .d.ts 에 OnnxWebGPURuntime / destroy() 가 누락 (런타임엔 존재).
// 모듈 augmentation 으로 타입 보강.
declare module 'piper-tts-web' {
  export class OnnxWebGPURuntime extends OnnxWebRuntime {
    constructor(options?: { ort?: unknown; basePath?: string; numThreads?: number })
  }
  // PiperWebEngine.destroy() — 내부 OnnxWebWorker / PhonemizeWebWorker terminate +
  // FetchProvider 의 blob URL revoke. 언어 전환 시 명시적으로 호출해 WASM heap 누수 방지.
  interface PiperWebEngine {
    destroy(): void
  }
}

// WebGPU 지원 환경 감지 — 지원 시 GPU 가속(iGPU/dGPU 활용), 미지원 시 WASM 폴백.
// 'high-performance' 명시 → dGPU+iGPU 동시 보유 시 dGPU 우선 선택, dGPU 없으면 iGPU 폴백.
// navigator.gpu 존재만 보면 false positive 가능성이 있어 requestAdapter() 결과까지 확인.
async function detectWebGPU(): Promise<boolean> {
  try {
    type GPUOpts = { powerPreference?: 'low-power' | 'high-performance' }
    const nav = navigator as Navigator & { gpu?: { requestAdapter: (opts?: GPUOpts) => Promise<unknown> } }
    if (!nav.gpu) return false
    const adapter = await nav.gpu.requestAdapter({ powerPreference: 'high-performance' })
    return adapter != null
  } catch {
    return false
  }
}

// piper-tts-web HuggingFaceVoiceProvider 의 URL 패턴 미러:
//   voice = "en_US-lessac-medium" → en/en_US/lessac/medium/en_US-lessac-medium.{onnx,onnx.json}
const PIPER_BASE_URL = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/'
function voiceUrls(voice: string): { json: string; onnx: string } {
  const parts = voice.split('-')
  const lang = parts[0].split('_')[0]
  const path = `${PIPER_BASE_URL}${lang}/${parts.join('/')}/${parts.join('-')}`
  return { json: `${path}.onnx.json`, onnx: `${path}.onnx` }
}

// 엔진 초기화와 병행해 voice 파일을 백그라운드 프리페치.
// cache: 'force-cache' → HTTP 캐시 적중 시 네트워크 0, 미스 시 다운로드 후 캐시 적재.
// piper-tts-web 의 FetchProvider 가 곧이어 fetch 하면 같은 URL 이라 캐시 적중 → 첫 발화 latency ↓.
async function prefetchVoice(voice: string): Promise<void> {
  try {
    const { json, onnx } = voiceUrls(voice)
    await Promise.all([
      fetch(json, { cache: 'force-cache' }),
      fetch(onnx, { cache: 'force-cache' }),
    ])
    console.log(`[TTS] ${voice} 프리페치 완료 (HTTP 캐시 적재)`)
  } catch (err) {
    console.warn(`[TTS] ${voice} 프리페치 실패 (정상 경로로 진행):`, err)
  }
}

export type TTSMode   = 'piper' | null
export type TTSStatus = 'idle' | 'loading' | 'ready' | 'error'

// TranslationLang → Piper voice ID (https://huggingface.co/rhasspy/piper-voices)
// ko, both 등 미지원 언어는 영어로 fallback. off만 명시적 끄기.
const VOICE_MAP: Partial<Record<TranslationLang, string>> = {
  en: 'en_US-lessac-medium',
  de: 'de_DE-thorsten-medium',
  es: 'es_MX-ald-medium',
  ru: 'ru_RU-irina-medium',
}

const FALLBACK_VOICE = VOICE_MAP.en!

// off는 명시적 끄기 → null 반환. 그 외 미지원 언어는 영어로 fallback.
function resolveVoice(lang: TranslationLang): string | null {
  if (lang === 'off') return null
  return VOICE_MAP[lang] ?? FALLBACK_VOICE
}

// 가속+선점 하이브리드 정책 상수
// 학습 컨텐츠(비원어민 수강자 영어 청취) 기준 — 1.4x 는 빠르게 들려 이해도 저하.
// 오디오북 가이드라인상 1.2x 가 "이해하면서 들을 수 있는" 일반적 상한.
const PLAYBACK_RATE_MAX     = 1.2   // pitch/속도 변형이 학습에 거슬리지 않는 가속 상한
const ACCEL_MULTIPLIER      = 1.2   // 가속 시 곱하는 배수 (PLAYBACK_RATE_MAX 와 일치 유지)
const FADE_MS               = 8     // 선점 시 fade-out 길이 — abrupt cut 의 click 노이즈 제거
const NATURAL_END_THRESHOLD = 0.5   // 남은 재생 0.5초 미만이면 굳이 안 끊고 자연 종료
const ACCEL_TARGET          = 1.5   // 가속 후 1.5초 이내 종료 가능하면 가속, 아니면 선점

type CurrentTask = {
  source:  AudioBufferSourceNode
  gain:    GainNode              // 선점 fade-out 시 다른 source 영향 없게 source 별 gain
  endTime: number                 // ctx.currentTime 기준 재생 종료 예정 시각
}

export function useTTS(enabled = true, audioLang: TranslationLang = 'en') {
  const engineRef        = useRef<PiperWebEngine | null>(null)
  const audioCtxRef      = useRef<AudioContext | null>(null)
  const gainRef          = useRef<GainNode | null>(null)
  const gainValueRef     = useRef(0.7)
  const statusRef        = useRef<TTSStatus>('idle')
  const currentTaskRef   = useRef<CurrentTask | null>(null)
  const seqRef           = useRef(0)  // synthesize 호출마다 ++ — 진행 중 generate 의 stale 결과 drop 시그널

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
        const taskSeq = seqRef.current  // 이 작업 시작 시점의 seq
        try {
          const response = await engineRef.current.generate(synTask.text, synTask.voice, 0)

          // generate 진행 중에 synthesize 가 호출됐으면 결과 drop (선점됨)
          if (taskSeq !== seqRef.current) {
            console.log('[TTS] 선점됨 — generate 결과 drop:', synTask.text.slice(0, 30))
          } else {
            const arrayBuffer = await response.file.arrayBuffer()
            const ctx = audioCtxRef.current
            if (ctx && ctx.state !== 'closed') {
              if (ctx.state === 'suspended') await ctx.resume()
              const audioBuffer = await ctx.decodeAudioData(arrayBuffer)

              // === 가속+선점 하이브리드 의사결정 ===
              const now = ctx.currentTime
              let startTime = now + 0.05
              const current = currentTaskRef.current

              if (current && current.endTime > now) {
                const remaining = current.endTime - now
                const currentRate = current.source.playbackRate.value
                const acceleratedRate = Math.min(currentRate * ACCEL_MULTIPLIER, PLAYBACK_RATE_MAX)
                const acceleratedRemaining = remaining * (currentRate / acceleratedRate)

                if (remaining < NATURAL_END_THRESHOLD) {
                  // ① 자연 종료 — 거의 끝났으니 그대로 두고 큐잉
                  startTime = current.endTime
                } else if (acceleratedRemaining < ACCEL_TARGET && acceleratedRate > currentRate) {
                  // ② 가속 가능 — 1.2x 로 끝까지 빠르게 + 큐잉
                  current.source.playbackRate.cancelScheduledValues(now)
                  current.source.playbackRate.setValueAtTime(currentRate, now)
                  current.source.playbackRate.linearRampToValueAtTime(acceleratedRate, now + 0.05)
                  current.endTime = now + acceleratedRemaining
                  startTime = current.endTime
                  console.log(`[TTS] 가속: ${currentRate.toFixed(2)}x → ${acceleratedRate.toFixed(2)}x (잔여 ${remaining.toFixed(2)}s → ${acceleratedRemaining.toFixed(2)}s)`)
                } else {
                  // ③ 선점 — fade-out 후 즉시 새 발화 시작
                  const fadeEnd = now + FADE_MS / 1000
                  current.gain.gain.cancelScheduledValues(now)
                  current.gain.gain.setValueAtTime(current.gain.gain.value, now)
                  current.gain.gain.linearRampToValueAtTime(0, fadeEnd)
                  const sourceToStop = current.source
                  setTimeout(() => { try { sourceToStop.stop() } catch { /* ignore */ } }, FADE_MS + 2)
                  currentTaskRef.current = null
                  startTime = fadeEnd + 0.005
                  console.log(`[TTS] 선점 — fade-out (잔여 ${remaining.toFixed(2)}s, 가속 후도 ${acceleratedRemaining.toFixed(2)}s)`)
                }
              }

              // 새 source + 전용 gain (per-source 페이드 처리용)
              const source = ctx.createBufferSource()
              const sourceGain = ctx.createGain()
              sourceGain.gain.value = 1
              source.buffer = audioBuffer
              source.connect(sourceGain)
              sourceGain.connect(gainRef.current ?? ctx.destination)
              source.start(startTime)

              const newTask: CurrentTask = {
                source,
                gain: sourceGain,
                endTime: startTime + audioBuffer.duration,
              }
              source.onended = () => {
                if (currentTaskRef.current === newTask) {
                  currentTaskRef.current = null
                }
              }
              currentTaskRef.current = newTask
            }
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

    // 빈번한 언어 전환 race 방어 — 엔진 생성 await 도중에 cleanup 이 실행되면
    // 이 flag 가 true 가 되고, 늦게 도착한 엔진은 즉시 destroy 후 폐기됨.
    // (없으면 좀비 엔진 + Worker 가 누적되어 WASM heap OOM 유발)
    let aborted = false

    const init = async () => {
      try {
        // (2) 엔진 초기화와 병행해 voice 파일을 백그라운드 프리페치 — 의도적으로 await 안 함.
        //     piper 가 곧 fetch 할 때 HTTP 캐시 적중 → 첫 발화까지 latency ↓.
        const voice = resolveVoice(audioLang)
        if (voice) prefetchVoice(voice)

        // (1) WebGPU 지원 환경이면 GPU 가속(iGPU/dGPU) 사용 → CPU 부담 ↓.
        //     미지원 환경 (구형 브라우저 / WebGPU 비활성화) 은 WASM 으로 자동 폴백.
        const useWebGPU = await detectWebGPU()
        let onnxRuntime: OnnxWebRuntime
        if (useWebGPU) {
          // ort.env.webgpu.powerPreference 를 InferenceSession.create 전에 설정 →
          // ort 가 dGPU 우선으로 GPU adapter 잡음. 외부에서 주입한 ort 만 영향 받으므로
          // OnnxWebGPURuntime 에 동일 ort 인스턴스를 명시 전달.
          ;(ortWebGPU.env as { webgpu?: { powerPreference?: string } }).webgpu = {
            ...((ortWebGPU.env as { webgpu?: object }).webgpu ?? {}),
            powerPreference: 'high-performance',
          }
          onnxRuntime = new OnnxWebGPURuntime({ ort: ortWebGPU })
        } else {
          onnxRuntime = new OnnxWebRuntime()
          // (3) numThreads 는 piper 기본값(navigator.hardwareConcurrency) 사용 → 추가 인자 불필요.
          //     단 crossOriginIsolated=false 면 ort 내부에서 1 으로 강제됨 → 가시성 위해 경고만.
          if (!self.crossOriginIsolated) {
            console.warn('[TTS] crossOriginIsolated=false → WASM 멀티스레드 비활성. COOP/COEP 헤더 필요')
          }
        }
        console.log(
          `[TTS] ONNX 백엔드: ${useWebGPU ? 'WebGPU (high-performance)' : `WASM (${navigator.hardwareConcurrency} threads, COI=${self.crossOriginIsolated})`}`
        )

        const engine = new PiperWebEngine({
          onnxRuntime,
          phonemizeRuntime: new PhonemizeWebRuntime(),
        })

        // 엔진 생성 await 가 끝났는데 그 사이 cleanup 이 실행됐으면 (audioLang 빠르게 전환 등)
        // 이 엔진은 이미 폐기 대상 — 즉시 destroy 후 return 으로 ref 에 안 올림.
        // (안 그러면 새 엔진과 동시에 살아있어 Worker 2벌이 누적)
        if (aborted) {
          try { engine.destroy() } catch { /* ignore */ }
          return
        }

        engineRef.current = engine
        updateStatus('ready')
        setLoadingProgress(100)
        setMode('piper')

        // 현재 언어 모델만 warm-up (메모리에 모델 1개만 유지).
        // 미지원 언어는 영어 음성으로 fallback (off만 스킵).
        if (voice) {
          preloadQueueRef.current.push({ lang: audioLang, voice })
          processNext()
          console.log(`[TTS] piper 초기화 완료, ${audioLang} → ${voice} warm-up 시작`)
        }
      } catch (err) {
        setError(String(err))
        updateStatus('error')
        console.error('[TTS] 초기화 실패:', err)
      }
    }

    init()

    return () => {
      // race 차단 — init 아직 await 중이면 늦게 도착한 엔진이 즉시 폐기됨
      aborted = true

      // 이전 엔진 명시적 destroy — 내부 OnnxWebWorker / PhonemizeWebWorker terminate +
      // FetchProvider 의 voice blob URL revoke. 단순 ref=null 로는 Worker 가 살아남아
      // WASM heap 누수 (특히 빈번한 언어 전환 시 좀비 엔진 누적 → OOM).
      const prevEngine = engineRef.current
      if (prevEngine) {
        try { prevEngine.destroy() } catch { /* ignore */ }
      }
      engineRef.current = null

      // 언어 변경 시 진행 중 task 도 정리 (이전 언어로 재생 안 되게)
      if (currentTaskRef.current) {
        try { currentTaskRef.current.source.stop() } catch { /* ignore */ }
        currentTaskRef.current = null
      }
      // AudioContext 는 세션 내내 유지 (unlockAudio에서 생성, 언어 변경과 무관)
    }
  }, [enabled, audioLang, updateStatus])

  // 컴포넌트 언마운트 시 AudioContext 완전 정리 — 페이지 재진입 시 누수 방지
  useEffect(() => {
    return () => {
      if (currentTaskRef.current) {
        try { currentTaskRef.current.source.stop() } catch { /* ignore */ }
        try { currentTaskRef.current.gain.disconnect() } catch { /* ignore */ }
        currentTaskRef.current = null
      }
      if (gainRef.current) {
        try { gainRef.current.disconnect() } catch { /* ignore */ }
        gainRef.current = null
      }
      if (audioCtxRef.current) {
        audioCtxRef.current.close().catch(() => {})
        audioCtxRef.current = null
      }
    }
  }, [])

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
    const voice = resolveVoice(lang)
    if (!voice) {
      console.warn('[TTS] 음성 끄기 상태 — lang:', lang)
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

    // seq 증가 → 진행 중인 generate 의 결과는 도착해도 drop 됨 (processNext 안에서 비교)
    seqRef.current++
    // 이전 큐에 쌓인 미처리 작업 drop — 가장 최신 발화만 의미 있음
    synthesizeQueueRef.current = []

    synthesizeQueueRef.current.push({ text, voice })
    processNextRef.current()
    console.log('[TTS] synthesize 요청:', lang, text.slice(0, 40))
  }, [])

  return { status, loadingProgress, error, mode, synthesize, unlockAudio, setVolume }
}
