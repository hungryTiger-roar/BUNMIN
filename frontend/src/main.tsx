import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter, BrowserRouter } from 'react-router-dom'
import App from './App'
import { isElectron } from './lib/api'
import './styles/index.css'

// Electron 환경: HashRouter — file:// 로드 시 history API 가 동작하지 않아 # 라우팅 필수.
// 웹 환경 (수강자 등): BrowserRouter — `/student` 같은 깨끗한 URL 사용. Vite dev server
// 와 프로덕션 SPA fallback 이 어떤 path 로 접근해도 index.html 반환하면 동작.
const Router = isElectron ? HashRouter : BrowserRouter

// [Sync Debug] .env 의 VITE_SYNC_DEBUG=true 면 페이지 로드 시 자동 활성화.
// 콘솔에서 수동 토글: window.__SYNC_DEBUG = true / false
if (typeof window !== 'undefined' && import.meta.env.VITE_SYNC_DEBUG === 'true') {
  ;(window as unknown as { __SYNC_DEBUG?: boolean }).__SYNC_DEBUG = true
  console.log('[Sync Debug] VITE_SYNC_DEBUG=true — 진단 로그 자동 활성화 ([L→S] / [S←L] / [Diag])')
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Router>
      <App />
    </Router>
  </React.StrictMode>,
)
