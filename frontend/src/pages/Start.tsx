import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useLectureStore } from '../stores/lectureStore'

const STORAGE_KEY = 'student_name'

export default function Start() {
  const navigate = useNavigate()
  const setStudentName = useLectureStore((s) => s.setStudentName)

  const [name, setName] = useState('')
  const [saveInfo, setSaveInfo] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      setName(saved)
      setSaveInfo(true)
    }
  }, [])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) {
      setError('이름을 입력해주세요.')
      return
    }

    if (saveInfo) {
      localStorage.setItem(STORAGE_KEY, trimmed)
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }

    setStudentName(trimmed)
    navigate('/student')
  }

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <h1 className="text-white text-2xl font-semibold mb-8 leading-snug">
          이름을 입력해주세요.
        </h1>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="text-slate-300 text-sm mb-1.5 flex items-center gap-1">
              이름
              <span className="text-red-400">*</span>
            </label>
            <div className="relative">
              <input
                type="text"
                value={name}
                onChange={(e) => {
                  setName(e.target.value)
                  setError('')
                }}
                placeholder="이름을 입력하세요"
                className="w-full bg-transparent border border-slate-600 rounded-full px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:border-slate-400 pr-10"
              />
              {name && (
                <button
                  type="button"
                  onClick={() => setName('')}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                >
                  ✕
                </button>
              )}
            </div>
            {error && <p className="text-red-400 text-xs mt-1.5">{error}</p>}
          </div>

          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={saveInfo}
              onChange={(e) => setSaveInfo(e.target.checked)}
              className="w-4 h-4 accent-blue-500"
            />
            <span className="text-slate-300 text-sm">내 정보 저장</span>
          </label>

          <button
            type="submit"
            className="w-full bg-[#6b8f71] hover:bg-[#5a7a60] active:bg-[#4a6a50] text-white font-semibold py-3 rounded-full transition-colors"
          >
            강의 참여
          </button>
        </form>
      </div>
    </div>
  )
}
