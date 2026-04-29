/**
 * TTS Web Worker — piper-tts-web (CPU WASM)
 *
 * 메인 → Worker
 *   { type: 'init' }
 *   { type: 'synthesize', text: string, voice?: string }
 *
 * Worker → 메인
 *   { type: 'ready' }
 *   { type: 'preloaded', voice: string }
 *   { type: 'error', message: string }
 *   { type: 'audio', arrayBuffer: ArrayBuffer }
 */

import { PiperWebEngine, OnnxWebRuntime, PhonemizeWebRuntime } from 'piper-tts-web'

// 지원 언어 → Piper voice ID (useTTS.ts의 VOICE_MAP과 동일하게 유지)
const VOICE_MAP: Record<string, string> = {
  en: 'en_US-lessac-medium',
  de: 'de_DE-thorsten-medium',
  es: 'es_MX-ald-medium',
  ru: 'ru_RU-irina-medium',
}

const DEFAULT_VOICE = VOICE_MAP.en

let engine: PiperWebEngine | null = null

// 우선순위 직렬 큐 — engine.generate() 동시 호출 방지
// synthesize 요청이 preload보다 항상 먼저 처리됨
let busy = false
const synthesizeQueue: Array<{ text: string; voice: string }> = []
const preloadQueue: Array<{ lang: string; voice: string }> = []

async function processNext() {
  if (busy || !engine) return

  // synthesize 우선, 없으면 preload
  const synTask = synthesizeQueue.shift()
  if (synTask) {
    busy = true
    try {
      const response = await engine.generate(synTask.text, synTask.voice, 0)
      const arrayBuffer = await response.file.arrayBuffer()
      ;(self as unknown as Worker).postMessage(
        { type: 'audio', arrayBuffer },
        [arrayBuffer],
      )
    } catch (err) {
      self.postMessage({ type: 'error', message: String(err) })
    }
    busy = false
    processNext()
    return
  }

  const preTask = preloadQueue.shift()
  if (preTask) {
    busy = true
    try {
      await engine.generate('Hello.', preTask.voice, 0)
      self.postMessage({ type: 'preloaded', voice: preTask.lang })
      console.log(`[TTS Worker] ${preTask.lang} 모델 프리로드 완료`)
    } catch (err) {
      console.warn(`[TTS Worker] ${preTask.lang} 모델 프리로드 실패:`, err)
    }
    busy = false
    processNext()
  }
}

self.onmessage = async (e: MessageEvent) => {
  const { type } = e.data

  if (type === 'init') {
    try {
      engine = new PiperWebEngine({
        onnxRuntime: new OnnxWebRuntime(),
        phonemizeRuntime: new PhonemizeWebRuntime(),
      })
      self.postMessage({ type: 'ready' })
      console.log('[TTS Worker] piper 초기화 완료, 음성 모델 프리로드 시작')

      // 모든 음성 모델을 preloadQueue에 등록 후 백그라운드 처리
      for (const [lang, voice] of Object.entries(VOICE_MAP)) {
        preloadQueue.push({ lang, voice })
      }
      processNext()
    } catch (err) {
      self.postMessage({ type: 'error', message: String(err) })
    }
    return
  }

  if (type === 'synthesize') {
    const { text, voice = DEFAULT_VOICE } = e.data as { text: string; voice?: string }
    if (!engine) {
      self.postMessage({ type: 'error', message: 'TTS 엔진이 아직 초기화되지 않았습니다' })
      return
    }
    // synthesizeQueue에 push → processNext()가 preload보다 먼저 처리
    synthesizeQueue.push({ text, voice })
    processNext()
    return
  }
}
