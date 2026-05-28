import type {
  SlideLibraryResponse,
  SlideLoadResponse,
  SlideDeleteResponse,
  SlideBatchDeleteResponse,
  SlideRenameResponse,
  SortOrder,
} from '@/types/slide'

// 백엔드 주소 결정 — 환경별 분기:
//   1. Electron 운영판: main.cjs 가 http://127.0.0.1:48000 으로 frontend 로드 → window.location.host 가 곧 백엔드.
//      그래도 API_BASE 를 절대주소로 박는 이유는 file:// 폴백(waitForHealth 실패 시) 호환 — host 빈 문자열 회피.
//   2. Electron dev: Vite dev 서버(127.0.0.1:43000)에서 로드 → 프록시(/api ...)로 백엔드 위임 → same-origin.
//      직접 127.0.0.1:48000 호출하면 cross-origin → ERR_BLOCKED_BY_RESPONSE.NotSameOrigin 막힘.
//   3. 학생 웹: 강사 LAN IP 에서 서빙 → 상대경로(공백)로 같은 origin 사용.
// 'localhost' 대신 '127.0.0.1' 명시: Windows Node 가 'localhost' 를 IPv6 우선 해석해 uvicorn(IPv4 only) 못 잡는 케이스 회피.
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

// ============================================================
// Glossary (용어집) API
// ============================================================
export interface GlossaryEntry {
  id: number
  korean: string
  english: string
  category: string
}

export interface GlossaryResponse {
  entries: GlossaryEntry[]
  categories: string[]
  total: number
}

export async function getGlossary(): Promise<GlossaryResponse> {
  const res = await fetch(`${API_BASE}/api/glossary`)
  if (!res.ok) throw new Error('용어집 조회 실패')
  return res.json()
}

export async function addGlossaryEntry(entry: { korean: string; english: string; category?: string }): Promise<{ success: boolean; entry: GlossaryEntry }> {
  const res = await fetch(`${API_BASE}/api/glossary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(entry),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || '용어 추가 실패')
  }
  return res.json()
}

export async function updateGlossaryEntry(korean: string, update: { korean: string; english: string; category?: string }): Promise<{ success: boolean }> {
  const res = await fetch(`${API_BASE}/api/glossary/${encodeURIComponent(korean)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || '용어 수정 실패')
  }
  return res.json()
}

export async function deleteGlossaryEntry(korean: string): Promise<{ success: boolean }> {
  const res = await fetch(`${API_BASE}/api/glossary/${encodeURIComponent(korean)}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || '용어 삭제 실패')
  }
  return res.json()
}
