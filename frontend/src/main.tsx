import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter, BrowserRouter } from 'react-router-dom'
import App from './App'
import { isElectron } from './lib/api'
import './styles/index.css'

// Hakgyoansim Allimjang 폰트 preload — 큰 타이틀("번역의 민족") 에 쓰이는 폰트.
// Vite 가 import 한 자산을 해싱된 URL 로 변환해주므로 ?url 로 가져와 동적 link rel=preload 주입.
// React 첫 렌더 직전에 폰트 다운로드를 병렬로 시작 → 첫 진입 시 paybooc fallback 깜빡임 최소화.
import allimjangRegularUrl from './assets/fonts/Hakgyoansim Allimjang OTF R.otf?url'
import allimjangBoldUrl from './assets/fonts/Hakgyoansim Allimjang OTF B.otf?url'
;[allimjangRegularUrl, allimjangBoldUrl].forEach((href) => {
  const link = document.createElement('link')
  link.rel = 'preload'
  link.as = 'font'
  link.type = 'font/otf'
  link.crossOrigin = 'anonymous'
  link.href = href
  document.head.appendChild(link)
})

// Electron 환경: HashRouter — file:// 로드 시 history API 가 동작하지 않아 # 라우팅 필수.
// 웹 환경 (수강자 등): BrowserRouter — `/student` 같은 깨끗한 URL 사용. Vite dev server
// 와 프로덕션 SPA fallback 이 어떤 path 로 접근해도 index.html 반환하면 동작.
const Router = isElectron ? HashRouter : BrowserRouter

// [Sync Debug] 진단 로그 ([L→S] / [S←L] / [Diag]) 항상 활성화.
// 끄고 싶으면 콘솔에서 window.__SYNC_DEBUG = false.
if (typeof window !== 'undefined') {
  ;(window as unknown as { __SYNC_DEBUG?: boolean }).__SYNC_DEBUG = true
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Router>
      <App />
    </Router>
  </React.StrictMode>,
)
