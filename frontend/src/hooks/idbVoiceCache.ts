/**
 * IndexedDB 기반 piper-tts-web voice 영구 캐시
 *
 * 왜 IndexedDB 인가:
 *   브라우저 HTTP 캐시는 storage pressure / 모바일 Safari ITP (7일) 등으로 evict 가능.
 *   IndexedDB 에 voice 모델 ArrayBuffer (~63MB/voice) 를 영구 저장 → 캐시 evict 후에도
 *   재진입 시 재다운로드 안 함.
 *
 * 저장 구조:
 *   - DB:    aunion-voice-cache
 *   - Store: voices  (keyPath: url)
 *   - Entry: { url, data, contentType, sizeBytes, lastUsed, storedAt }
 *
 * 용량 관리:
 *   - 총 사이즈 cap 300MB (voice 4~5개 분량)
 *   - 초과 시 LRU eviction (lastUsed 가장 오래된 entry 부터 삭제)
 *
 * 안전성:
 *   - QuotaExceededError 등 IDB 실패는 silent — graceful fallback (HTTP 캐시가 받아줌)
 *   - 모든 IDB 호출은 try-catch
 */

const DB_NAME = 'aunion-voice-cache'
const DB_VERSION = 1
const STORE = 'voices'
const MAX_TOTAL_BYTES = 300 * 1024 * 1024  // 300MB

// 캐시 entry 의 두 가지 데이터 형태:
//  - JSON 텍스트 (voice .json config — 작음, ~수 KB)
//  - 바이너리 ArrayBuffer (voice .onnx 모델 — ~63MB)
type CachedData = string | ArrayBuffer

interface CacheEntry {
  url: string
  data: CachedData
  contentType: 'json' | 'binary'
  sizeBytes: number
  lastUsed: number
  storedAt: number
}

let _dbPromise: Promise<IDBDatabase> | null = null

function getDB(): Promise<IDBDatabase> {
  if (_dbPromise) return _dbPromise
  _dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB not supported'))
      return
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'url' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
    req.onblocked = () => reject(new Error('IDB blocked — close other tabs'))
  })
  // 실패 시 다음 호출에서 다시 시도하도록 reset
  _dbPromise.catch(() => { _dbPromise = null })
  return _dbPromise
}

/** url 로 캐시 조회 — 있으면 lastUsed 갱신 후 반환, 없으면 null. 실패해도 throw 안 함. */
export async function getCachedVoice(
  url: string,
): Promise<{ data: CachedData; contentType: 'json' | 'binary' } | null> {
  try {
    const db = await getDB()
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      const store = tx.objectStore(STORE)
      const req = store.get(url)
      req.onsuccess = () => {
        const entry = req.result as CacheEntry | undefined
        if (!entry) {
          resolve(null)
          return
        }
        // LRU 갱신
        entry.lastUsed = Date.now()
        store.put(entry)
        resolve({ data: entry.data, contentType: entry.contentType })
      }
      req.onerror = () => reject(req.error)
    })
  } catch (err) {
    console.warn('[VoiceCache] IDB get 실패 (graceful):', err)
    return null
  }
}

/** url + 데이터를 캐시에 저장. 용량 초과 시 LRU evict 후 저장. 실패해도 throw 안 함. */
export async function putCachedVoice(
  url: string,
  data: CachedData,
  contentType: 'json' | 'binary',
): Promise<void> {
  try {
    const sizeBytes = typeof data === 'string' ? data.length * 2 : data.byteLength
    await ensureCapacity(sizeBytes)

    const db = await getDB()
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      const store = tx.objectStore(STORE)
      const entry: CacheEntry = {
        url,
        data,
        contentType,
        sizeBytes,
        lastUsed: Date.now(),
        storedAt: Date.now(),
      }
      const req = store.put(entry)
      req.onsuccess = () => resolve()
      req.onerror = () => reject(req.error)
    })
    console.log(
      `[VoiceCache] IDB store: ${url.split('/').pop()} ` +
      `(${(sizeBytes / 1024 / 1024).toFixed(2)}MB)`,
    )
  } catch (err) {
    // QuotaExceededError 등 — 그냥 무시. HTTP 캐시가 fallback.
    console.warn('[VoiceCache] IDB put 실패 (graceful):', err)
  }
}

/** 총 사이즈가 cap 을 넘지 않게 LRU evict. 실패 시 throw — caller 가 graceful 처리. */
async function ensureCapacity(needed: number): Promise<void> {
  const db = await getDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    const store = tx.objectStore(STORE)
    const req = store.getAll()
    req.onsuccess = () => {
      const items = req.result as CacheEntry[]
      let total = items.reduce((sum, it) => sum + it.sizeBytes, 0)
      if (total + needed <= MAX_TOTAL_BYTES) {
        resolve()
        return
      }
      // lastUsed 오래된 것부터 evict
      items.sort((a, b) => a.lastUsed - b.lastUsed)
      for (const item of items) {
        if (total + needed <= MAX_TOTAL_BYTES) break
        store.delete(item.url)
        total -= item.sizeBytes
        console.log(
          `[VoiceCache] LRU evict: ${item.url.split('/').pop()} ` +
          `(${(item.sizeBytes / 1024 / 1024).toFixed(2)}MB)`,
        )
      }
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    }
    req.onerror = () => reject(req.error)
  })
}

/** 디버깅 / 사용자 설정 용 — 전체 캐시 비우기. */
export async function clearVoiceCache(): Promise<void> {
  try {
    const db = await getDB()
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      const store = tx.objectStore(STORE)
      const req = store.clear()
      req.onsuccess = () => resolve()
      req.onerror = () => reject(req.error)
    })
    console.log('[VoiceCache] 전체 캐시 삭제됨')
  } catch (err) {
    console.warn('[VoiceCache] clear 실패:', err)
  }
}
