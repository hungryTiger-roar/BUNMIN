import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import Lecturer from './pages/Lecturer'
import Student from './pages/Student'

function App() {
  return (
    <div className="min-h-screen bg-slate-50">
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/lecturer" element={<Lecturer />} />
        <Route path="/student" element={<Student />} />
      </Routes>
    </div>
  )
}

export default App
