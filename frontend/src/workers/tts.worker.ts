/**
 * TTS Web Worker — kokoro-js (onnxruntime-web WASM 기반)
 *
 * 메인 스레드와의 메시지 프로토콜
 *
 * 메인 → Worker
 *   { type: 'init', dtype?: 'q8' | 'fp32' }
 *   { type: 'synthesize', id: string, text: string, voice?: string }
 *
 * Worker → 메인
 *   { type: 'ready' }
 *   { type: 'loading', progress: number }
 *   { type: 'error', message: string }
 *   { type: 'audio', id: string, samples: Float32Array, sampleRate: number }
 */

import { KokoroTTS } from 'kokoro-js'
import type { ProgressInfo } from '@huggingface/transformers'
import type { GenerateOptions } from 'kokoro-js'

type VoiceId = NonNullable<GenerateOptions['voice']>

let tts: KokoroTTS | null = null

self.onmessage = async (e: MessageEvent) => {
  const { type } = e.data

  if (type === 'init') {
    try {
      const dtype = (e.data.dtype as 'q8' | 'fp32') ?? 'q8'
      self.postMessage({ type: 'loading', progress: 0 })

      tts = await KokoroTTS.from_pretrained('onnx-community/Kokoro-82M-v1.0-ONNX', {
        dtype,
        progress_callback: (info: ProgressInfo) => {
          const progress = 'progress' in info ? (info as { progress: number }).progress : undefined
          if (progress !== undefined) {
            self.postMessage({ type: 'loading', progress: Math.round(progress) })
          }
        },
      })

      self.postMessage({ type: 'ready' })
    } catch (err) {
      self.postMessage({ type: 'error', message: String(err) })
    }
    return
  }

  if (type === 'synthesize') {
    const { id, text, voice = 'af_heart' } = e.data as {
      id: string
      text: string
      voice?: VoiceId
    }
    if (!tts) {
      self.postMessage({ type: 'error', message: 'TTS 모델이 아직 로드되지 않았습니다' })
      return
    }
    try {
      const result = await tts.generate(text, { voice })
      // RawAudio: { audio: Float32Array, sampling_rate: number }
      const samples = new Float32Array(result.audio)
      const sampleRate: number = result.sampling_rate
      ;(self as unknown as Worker).postMessage(
        { type: 'audio', id, samples, sampleRate },
        [samples.buffer],
      )
    } catch (err) {
      self.postMessage({ type: 'error', message: String(err) })
    }
    return
  }
}
