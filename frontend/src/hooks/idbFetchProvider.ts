/**
 * piper-tts-web 의 default FetchProvider 를 대체하는 IDB 캐시 layer.
 *
 * piper-tts-web RemoteVoiceProvider.fetch(voice) 는 내부적으로 provider.fetch(jsonUrl) +
 * provider.fetch(onnxUrl) 호출. 그 provider 가 default 면 매번 HTTP fetch — HTTP 캐시
 * evict 시 ~63MB 재다운로드. 우리는 그 자리에 IDB 우선 lookup 을 끼워넣음.
 *
 * default FetchProvider 와의 contract:
 *   - fetch(url): .json 이면 parsed object, 아니면 blob URL (Object URL) 반환
 *   - destroy(): 생성한 blob URL revoke
 *   - 결과는 메모리 cache (같은 url 재호출 시 즉시 반환)
 */

import { getCachedVoice, putCachedVoice } from './idbVoiceCache'

/** piper-tts-web 의 FetchProvider 와 동일한 인터페이스 */
export class IndexedDBFetchProvider {
  // 메모리 cache — 같은 url 다회 호출 시 IDB 도 안 뒤짐 (default FetchProvider 와 동일)
  private memCache = new Map<string, Promise<unknown>>()
  // destroy 시 revoke 해야 하는 blob URL 들 (binary 응답)
  private blobUrls: string[] = []

  fetch(url: string): Promise<unknown> {
    // 1. 메모리 cache 적중 — 즉시 반환
    const cached = this.memCache.get(url)
    if (cached) return cached

    // 2. IDB → 네트워크 폴백 흐름을 Promise 로 묶어 메모리 cache 에 등록
    const promise = this.fetchWithIDB(url)
    this.memCache.set(url, promise)
    return promise
  }

  private async fetchWithIDB(url: string): Promise<unknown> {
    const isJson = url.endsWith('.json')
    const contentType: 'json' | 'binary' = isJson ? 'json' : 'binary'

    // IDB 우선 시도
    const idbHit = await getCachedVoice(url)
    if (idbHit && idbHit.contentType === contentType) {
      console.log(`[VoiceProvider] IDB hit: ${url.split('/').pop()}`)
      if (isJson) {
        return JSON.parse(idbHit.data as string)
      } else {
        // binary → blob URL 생성 (piper 가 ort 에 전달할 형태)
        const blob = new Blob([idbHit.data as ArrayBuffer], { type: 'application/octet-stream' })
        const blobUrl = URL.createObjectURL(blob)
        this.blobUrls.push(blobUrl)
        return blobUrl
      }
    }

    // IDB miss — 네트워크 fetch
    console.log(`[VoiceProvider] IDB miss → fetch: ${url.split('/').pop()}`)
    const res = await fetch(url)
    if (!res.ok) {
      throw new Error(`Voice fetch 실패 (${res.status}): ${url}`)
    }

    if (isJson) {
      const text = await res.text()
      // IDB 저장 (best-effort, 실패해도 진행)
      void putCachedVoice(url, text, 'json')
      return JSON.parse(text)
    } else {
      const buf = await res.arrayBuffer()
      void putCachedVoice(url, buf, 'binary')
      const blob = new Blob([buf], { type: 'application/octet-stream' })
      const blobUrl = URL.createObjectURL(blob)
      this.blobUrls.push(blobUrl)
      return blobUrl
    }
  }

  /** piper engine.destroy() 가 voice provider 까지 destroy 호출 — blob URL 정리. */
  destroy(): void {
    for (const url of this.blobUrls) {
      try { URL.revokeObjectURL(url) } catch { /* ignore */ }
    }
    this.blobUrls = []
    this.memCache.clear()
  }
}
