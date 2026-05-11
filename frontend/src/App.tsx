import { useEffect } from 'react'
import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import Lecturer from './pages/Lecturer'
import LecturerHome from './pages/LecturerHome'
import LecturerSettings from './pages/LecturerSettings'
import Student from './pages/Student'
import Start from './pages/Start'
import Install from './pages/Install'
import { TitleBar } from './components/common/TitleBar'
import { usePreferencesStore } from './stores/preferencesStore'

function App() {
  const theme = usePreferencesStore((s) => s.theme)

  useEffect(() => {
    const root = document.documentElement
    root.classList.remove('dark', 'theme-gradient')
    if (theme === 'dark') root.classList.add('dark')
    else if (theme === 'gradient') root.classList.add('theme-gradient')
  }, [theme])

  return (
    <>
      <TitleBar />
      {/* 타이틀바(32px) 만큼 콘텐츠 아래로 밀어줌. 각 페이지의 min-h-screen 은 index.css 에서
          calc(100vh - 32px) 로 재정의되어 wrapper 의 pt-8 와 합쳐 정확히 viewport 에 맞음. */}
      <div className="pt-8">
        <Routes>
          <Route path="/install" element={<Install />} />
          <Route path="/" element={<Start />} />
          <Route path="/lecturer" element={<Lecturer />} />
          <Route path="/lecturer/home" element={<LecturerHome />} />
          <Route path="/lecturer/settings" element={<LecturerSettings />} />
          <Route path="/home" element={<Home />} />
          <Route path="/student/start" element={<Start />} />
          <Route path="/student" element={<Student />} />
        </Routes>
      </div>
    </>
  )
}

export default App