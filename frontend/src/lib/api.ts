import type {
  SlideLibraryResponse,
  SlideLoadResponse,
  SlideDeleteResponse,
  SlideBatchDeleteResponse,
  SlideRenameResponse,
  SortOrder,
} from '@/types/slide'

// Electron 프로덕션: file:// 로 로드되므로 window.location.host가 빈 문자열
// → 백엔드 주소를 127.0.0.1:48000 으로 고정해야 함 (표준 8000 충돌 회피 위해 변경됨)
// Windows에서 'localhost'는 IPv6(::1)로 풀려 uvicorn(IPv4 only)에 닿지 않을 수 있어 IPv4 명시.
//
// Electron dev 모드는 Vite dev 서버에서 로드되므로(127.0.0.1:43000) 프록시 경유 사용.
// 이렇게 하면 same-origin이 되어 Vite의 COEP=require-corp 정책에 걸리지 않음.
// (직접 127.0.0.1:48000을 호출하면 cross-origin → ERR_BLOCKED_BY_RESPONSE.NotSameOrigin...)
export const isElectron = typeof window !== 'undefined' && !!window.electron
const isViteDev = import.meta.env.DEV
const BACKEND_PORT = 48000

export const API_BASE = isElectron && !isViteDev
  ? `http://127.0.0.1:${BACKEND_PORT}` // Electron 프로덕션: 직접 백엔드 호출
  : '' // 그 외: Vite 프록시(/api, /slides, /health 등) 경유

export const WS_BASE = isElectron && !isViteDev
  ? `ws://127.0.0.1:${BACKEND_PORT}`
  : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`

export const WS_PIPELINE_URL = `${WS_BASE}/ws/pipeline`

// 모델 모드 전환 API
export interface ModeResponse {
  mode: string
  message: string
  models_loaded: string[]
}

export async function getCurrentMode(): Promise<ModeResponse> {
  const res = await fetch(`${API_BASE}/api/mode/current`)
  if (!res.ok) throw new Error('Failed to get current mode')
  return res.json()
}

export async function switchToSlideMode(): Promise<ModeResponse> {
  const res = await fetch(`${API_BASE}/api/mode/slide`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to switch to slide mode')
  return res.json()
}

export async function switchToRealtimeMode(): Promise<ModeResponse> {
  const res = await fetch(`${API_BASE}/api/mode/realtime`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to switch to realtime mode')
  return res.json()
}

// 강의자료 라이브러리 API
export async function getSlideLibrary(sort: SortOrder = 'recent'): Promise<SlideLibraryResponse> {
  const res = await fetch(`${API_BASE}/slides/library?sort=${sort}`)
  if (!res.ok) throw new Error('라이브러리 조회 실패')
  return res.json()
}

export async function loadSlide(slideId: string): Promise<SlideLoadResponse> {
  const res = await fetch(`${API_BASE}/slides/load/${slideId}`, {
    method: 'POST',
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || '강의자료 로드 실패')
  }
  return res.json()
}

// 단건 삭제 (호환성 유지용, UI에서는 일괄 삭제만 사용)
export async function deleteSlide(slideId: string): Promise<SlideDeleteResponse> {
  const res = await fetch(`${API_BASE}/slides/delete/${slideId}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error('강의자료 삭제 실패')
  return res.json()
}

export async function deleteSlidesBatch(slideIds: string[]): Promise<SlideBatchDeleteResponse> {
  const res = await fetch(`${API_BASE}/slides/delete-batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slide_ids: slideIds }),
  })
  if (!res.ok) throw new Error('강의자료 일괄 삭제 실패')
  return res.json()
}

export async function renameSlide(slideId: string, filename: string): Promise<SlideRenameResponse> {
  const res = await fetch(`${API_BASE}/slides/${slideId}/rename`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename }),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || '이름 변경 실패')
  }
  return res.json()
}
