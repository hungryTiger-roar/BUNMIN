// Electron 프로덕션: file:// 로 로드되므로 window.location.host가 빈 문자열
// → 백엔드 주소를 localhost:8000으로 고정해야 함
const isElectron = typeof window !== 'undefined' && !!window.electron
const BACKEND_PORT = 8000

export const API_BASE = isElectron
  ? `http://localhost:${BACKEND_PORT}`
  : '' // 개발 모드: Vite가 /slides, /health 등을 프록시

export const WS_BASE = isElectron
  ? `ws://localhost:${BACKEND_PORT}`
  : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
