// Electron 프로덕션: file:// 로 로드되므로 window.location.host가 빈 문자열
// → 백엔드 주소를 localhost:8000으로 고정해야 함
export const isElectron = typeof window !== 'undefined' && !!window.electron
const BACKEND_PORT = 8000

export const API_BASE = isElectron
  ? `http://localhost:${BACKEND_PORT}`
  : '' // 개발 모드: Vite가 /slides, /health 등을 프록시

export const WS_BASE = isElectron
  ? `ws://localhost:${BACKEND_PORT}`
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
