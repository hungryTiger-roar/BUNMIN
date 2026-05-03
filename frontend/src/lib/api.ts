// Electron 프로덕션: file:// 로 로드되므로 window.location.host가 빈 문자열
// → 백엔드 주소를 127.0.0.1:8000으로 고정해야 함
// Windows에서 'localhost'는 IPv6(::1)로 풀려 uvicorn(IPv4 only)에 닿지 않을 수 있어 IPv4 명시.
//
// Electron dev 모드는 Vite dev 서버에서 로드되므로(127.0.0.1:3000) 프록시 경유 사용.
// 이렇게 하면 same-origin이 되어 Vite의 COEP=require-corp 정책에 걸리지 않음.
// (직접 127.0.0.1:8000을 호출하면 cross-origin → ERR_BLOCKED_BY_RESPONSE.NotSameOrigin...)
export const isElectron = typeof window !== 'undefined' && !!window.electron
const isViteDev = import.meta.env.DEV
const BACKEND_PORT = 8000

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

// 토큰 설정 API
export interface TokenStatusResponse {
  hf_token_set: boolean
  openai_api_key_set: boolean
  hf_token_masked: string
  openai_api_key_masked: string
}

export interface UpdateTokensRequest {
  hf_token?: string
  openai_api_key?: string
}

export interface UpdateTokensResponse {
  updated: string[]
  message: string
}

export async function getTokenStatus(): Promise<TokenStatusResponse> {
  const res = await fetch(`${API_BASE}/api/settings/tokens`)
  if (!res.ok) throw new Error('토큰 상태 조회 실패')
  return res.json()
}

export async function updateTokens(payload: UpdateTokensRequest): Promise<UpdateTokensResponse> {
  const res = await fetch(`${API_BASE}/api/settings/tokens`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || '토큰 저장 실패')
  }
  return res.json()
}
