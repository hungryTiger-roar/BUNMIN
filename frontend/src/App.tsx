import { useEffect } from 'react'
import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import Lecturer from './pages/Lecturer'
import LecturerHome from './pages/LecturerHome'
import LecturerSettings from './pages/LecturerSettings'
import Student from './pages/Student'
import Start from './pages/Start'
import Loading from './pages/Loading'
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
    <div className="min-h-screen bg-background">
      <Routes>
        <Route path="/loading" element={<Loading />} />
        <Route path="/" element={<Start />} />
        <Route path="/lecturer" element={<Lecturer />} />
        <Route path="/lecturer/home" element={<LecturerHome />} />
        <Route path="/lecturer/settings" element={<LecturerSettings />} />
        <Route path="/home" element={<Home />} />
        <Route path="/student/start" element={<Start />} />
        <Route path="/student" element={<Student />} />
      </Routes>
    </div>
  )
}

export default App