import { useEffect, lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import Start from './pages/Start'
import Install from './pages/Install'
import Home from './pages/Home'
import LecturerHome from './pages/LecturerHome'
import LecturerSettings from './pages/LecturerSettings'
import { TitleBar } from './components/common/TitleBar'
import { usePreferencesStore } from './stores/preferencesStore'

// 라우트 코드 스플리팅 — Student.tsx 는 piper-tts-web + onnxruntime-web/webgpu 를 끌어와
// 진입 번들을 수십 MB 로 부풀린다. lazy 로 분리하면 /lecturer 등은 이 청크를 받지 않는다.
// Lecturer 도 컴포넌트가 많아 분리. 나머지(Start/Install/Home/LecturerHome·Settings)는
// 작고 Electron 진입/폴백 경로라 eager 유지 (file:// 폴백에서 dynamic import 리스크 회피).
const Lecturer = lazy(() => import('./pages/Lecturer'))
const Student = lazy(() => import('./pages/Student'))

function RouteFallback() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-home-gradient [background-size:800%_800%] animate-gradient-shift">
      <div className="h-10 w-10 rounded-full border-4 border-onPrimary/30 border-t-onPrimary animate-spin" />
    </div>
  )
}

function App() {
  const theme = usePreferencesStore((s) => s.theme)

  useEffect(() => {
    const root = document.documentElement
    root.classList.remove('dark', 'theme-gradient')
    if (theme === 'dark') root.classList.add('dark')
    else if (theme === 'gradient') root.classList.add('theme-gradient')
  }, [theme])

  // 초기 로딩 화면 제거
  useEffect(() => {
    const loader = document.getElementById('initial-loader')
    if (loader) {
      // 1. CSS 클래스를 추가해 투명해지는 애니메이션 시작
      loader.classList.add('hidden')

      // 2. 애니메이션 시간(0.5초) 후에 DOM에서 완전히 제거
      const timer = setTimeout(() => {
        loader.remove()
      }, 500)
      return () => clearTimeout(timer)
    }
  }, [])

  return (
    <>
      <TitleBar />
      {/* 타이틀바(32px) 만큼 콘텐츠 아래로 밀어줌. 각 페이지의 min-h-screen 은 index.css 에서
          calc(100vh - 32px) 로 재정의되어 wrapper 의 pt-8 와 합쳐 정확히 viewport 에 맞음. */}
      <div className="pt-8">
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/install" element={<Install />} />
            <Route path="/" element={<Start />} />
            <Route path="/lecturer" element={<Lecturer />} />
            <Route path="/lecturer/home" element={<LecturerHome />} />
            <Route path="/lecturer/settings" element={<LecturerSettings />} />
            <Route path="/home" element={<Home />} />
            <Route path="/student" element={<Student />} />
          </Routes>
        </Suspense>
      </div>
    </>
  )
}

export default App
