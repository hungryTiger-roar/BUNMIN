import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import Lecturer from './pages/Lecturer'
import Student from './pages/Student'
import Loading from './pages/Loading'

function App() {
  return (
    <div className="min-h-screen bg-slate-50">
      <Routes>
        <Route path="/loading" element={<Loading />} />
        <Route path="/" element={<Home />} />
        <Route path="/lecturer" element={<Lecturer />} />
        <Route path="/student" element={<Student />} />
      </Routes>
    </div>
  )
}

export default App
