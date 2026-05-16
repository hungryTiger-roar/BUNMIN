import { useEffect, lazy, Suspense, useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import Start from './pages/Start'
import Install from './pages/Install'
import LecturerHome from './pages/LecturerHome'
import { TitleBar } from './components/common/TitleBar'
import { usePreferencesStore } from './stores/preferencesStore'
import { useLectureStore } from './stores/lectureStore'
import { isElectron } from './lib/api'

// 라우트 코드 스플리팅 — Student.tsx 는 piper-tts-web + onnxruntime-web/webgpu 를 끌어와
// 진입 번들을 수십 MB 로 부풀린다. lazy 로 분리하면 /lecturer 등은 이 청크를 받지 않는다.
// Lecturer 도 컴포넌트가 많아 분리. 나머지(Start/Install/LecturerHome·Settings)는
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

function GlobalToast() {
  // 글로벌 토스트 — alert() 대체 (Electron native dialog 회피).
  // lectureStore.toastMessage 가 set 되면 표시되고 4초 후 자동 dismiss.
  // 모든 페이지에서 공통 사용 — 강의 시작 거부, 슬라이드 삭제 실패 등.
  const message = useLectureStore((s) => s.toastMessage)
  const setMessage = useLectureStore((s) => s.setToastMessage)
  useEffect(() => {
    if (!message) return
    const id = window.setTimeout(() => setMessage(null), 4000)
    return () => window.clearTimeout(id)
  }, [message, setMessage])
  if (!message) return null
  return (
    <div className="fixed top-12 left-1/2 -translate-x-1/2 z-[100] px-4 py-2.5 bg-error/90 text-white text-sm rounded-lg shadow-lg backdrop-blur-sm max-w-md whitespace-pre-line text-center">
      {message}
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

  // Electron frame-less 윈도우에서만 자체 타이틀바(32px)를 깐다.
  // 브라우저 접속(학생이 강의자 링크로 들어오는 경로)에서는 html.is-electron 클래스를 빼서
  // index.css 의 calc(100vh - 32px) 보정이 적용되지 않게 한다.
  useEffect(() => {
    if (isElectron) document.documentElement.classList.add('is-electron')
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
      {isElectron && <TitleBar />}
      <GlobalToast />
      {/* 타이틀바(32px) 만큼 콘텐츠 아래로 밀어줌. 각 페이지의 min-h-screen 은 index.css 에서
          calc(100vh - 32px) 로 재정의되어 wrapper 의 pt-8 와 합쳐 정확히 viewport 에 맞음.
          브라우저 접속 시에는 타이틀바가 없으므로 pt-8 도 빼서 빈 32px 공간이 안 생기게 한다. */}
      <div className={isElectron ? 'pt-8' : ''}>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/install" element={<Install />} />
            <Route path="/" element={<Start />} />
            <Route path="/student/start" element={<Start />} />
            <Route path="/lecturer" element={<Suspense fallback={<LecturerFallback />}><Lecturer /></Suspense>} />
            <Route path="/lecturer/home" element={<LecturerHome />} /> {/* LecturerHome은 lazy가 아니므로 Suspense 불필요 */}
            <Route path="/student" element={<Student />} />
          </Routes>
        </Suspense>
      </div>
    </>
  )
}

export default App
