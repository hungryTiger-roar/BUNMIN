import { useEffect, lazy, Suspense, useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import Start from './pages/Start'
import Install from './pages/Install'
import Home from './pages/Home'
import LecturerHome from './pages/LecturerHome'
import { TitleBar } from './components/common/TitleBar'
import { usePreferencesStore } from './stores/preferencesStore'
import { isElectron } from './lib/api'

// 라우트 코드 스플리팅 — Student.tsx 는 piper-tts-web + onnxruntime-web/webgpu 를 끌어와
// 진입 번들을 수십 MB 로 부풀린다. lazy 로 분리하면 /lecturer 등은 이 청크를 받지 않는다.
// Lecturer 도 컴포넌트가 많아 분리. 나머지(Start/Install/Home/LecturerHome·Settings)는
// 작고 Electron 진입/폴백 경로라 eager 유지 (file:// 폴백에서 dynamic import 리스크 회피).
const Lecturer = lazy(() => import('./pages/Lecturer'))
const Student = lazy(() => import('./pages/Student'))

function RouteFallback() {
  // 페이지가 로드되는 동안 잠시 표시될 로딩 애니메이션입니다.
  // Suspense의 fallback으로 사용되며, 로딩이 끝나면 실제 페이지 컴포넌트로 교체됩니다.
  const [videoSrc] = useState(() => (Math.random() > 0.5 ? '/animation_white.webm' : '/animation_black.webm'))
  return (
    <div className="min-h-screen flex items-center justify-center bg-home-gradient [background-size:800%_800%] animate-gradient-shift">
      <div className="flex flex-col items-center">
        <video src={videoSrc} autoPlay loop muted playsInline style={{ width: '200px', height: 'auto' }} />
        <div className="loader --4"></div>
      </div>
    </div>
  )
}

function LecturerFallback() {
  // Lecturer.tsx는 캐릭터 애니메이션 없이 기본 로딩바만 표시합니다.
  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="h-10 w-10 rounded-full border-4 border-primaryContainer/30 border-t-primary animate-spin" />
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

  // Electron 자체 타이틀바(32px)가 적용되는 환경 마킹 — index.css 의
  // min-h-screen / h-screen 재정의가 이 클래스 안에서만 동작하도록.
  // 웹 학생 화면은 브라우저 native 크롬을 쓰므로 차감 불필요.
  useEffect(() => {
    if (isElectron) document.body.classList.add('electron')
  }, [])

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
      {/* TitleBar 는 Electron 의 frame: false 윈도우 전용 (드래그 핸들 + 윈도우 컨트롤).
          웹 학생 화면(브라우저)에서는 native 크롬이 있어 불필요 + pt-8 도 미적용 →
          빈 32px 띠가 안 생김. */}
      {isElectron && <TitleBar />}
      <div className={isElectron ? 'pt-8' : ''}>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/install" element={<Install />} />
            <Route path="/" element={<Start />} />
            <Route path="/student/start" element={<Start />} />
            <Route path="/lecturer" element={<Suspense fallback={<LecturerFallback />}><Lecturer /></Suspense>} />
            <Route path="/lecturer/home" element={<LecturerHome />} /> {/* LecturerHome은 lazy가 아니므로 Suspense 불필요 */}
            <Route path="/home" element={<Home />} />
            <Route path="/student" element={<Student />} />
          </Routes>
        </Suspense>
      </div>
    </>
  )
}

export default App
