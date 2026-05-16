import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePreferencesStore } from '@/stores/preferencesStore'
import { useLectureStore } from '@/stores/lectureStore'

// 학생 측 'student_name' 과 동일한 별도 키 패턴. preferencesStore.lecturerName 은
// 강의 진행 중 인메모리 상태로만 쓰고, "다음에도 사용하기" 저장은 localStorage 에 분리.
const STORAGE_KEY = 'lecturer_name'

export default function LecturerHome() {
  const navigate = useNavigate()
  const setLecturerName = usePreferencesStore((s) => s.setLecturerName)
  const resetLecture = useLectureStore((s) => s.reset)

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

  const handleStart = (e: React.FormEvent) => {
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

    setLecturerName(trimmed)
    // 새 강의 진입: 이전 세션의 slideId/slideStatus 등을 깨끗하게 비움.
    // (이렇게 안 하면 자료 미선택 상태에서도 이전에 띄웠던 자료가 강의 시작 시 학생 화면에 노출됨)
    resetLecture()
    navigate('/lecturer')
  }

  return (
    <div className="relative min-h-screen bg-home-gradient [background-size:800%_800%] animate-gradient-shift flex flex-col items-center justify-center px-4">
      {/* 타이틀 */}
      <div className="text-center mb-16">
        <h1 className="text-7xl font-allimjang font-bold text-white mb-5 [filter:drop-shadow(0_4px_8px_rgba(0,0,0,0.18))_drop-shadow(0_12px_24px_rgba(0,0,0,0.12))]">
          번역의 민족
        </h1>
        <p className="font-a2z text-white text-lg tracking-wide">
          실시간 AI 강의 번역 시스템
        </p>
      </div>

      <h2 className="font-a2z text-white text-2xl mb-8 leading-snug whitespace-nowrap tracking-wide">
        강의자 이름을 입력해주세요.
      </h2>

      <div className="w-full max-w-sm">
        <form onSubmit={handleStart} className="space-y-5">
          <div>
            <label className="text-white/80 text-sm mb-1.5 flex items-center gap-1">
              이름
              <span className="text-error">*</span>
            </label>
            <div className="relative">
              <input
                type="text"
                value={name}
                onChange={(e) => {
                  setName(e.target.value)
                  setError('')
                }}
                placeholder="이름을 입력."
                maxLength={40}
                className="w-full bg-white rounded-full px-4 py-2.5 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-onPrimary pr-10"
              />
              {name && (
                <button
                  type="button"
                  onClick={() => setName('')}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  ✕
                </button>
              )}
            </div>
            {error && <p className="text-error text-xs mt-1.5">{error}</p>}
          </div>

          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={saveInfo}
              onChange={(e) => setSaveInfo(e.target.checked)}
              className="w-4 h-4 accent-primary"
            />
            <span className="text-white/80 text-sm">다음에도 이름 사용하기</span>
          </label>

          <button
            type="submit"
            className="w-full bg-primary hover:opacity-90 text-onPrimary font-medium py-3 rounded-full transition-all shadow-lg shadow-primary/20"
          >
            강의 준비
          </button>
        </form>
      </div>

      <p className="absolute bottom-6 right-6 text-sm text-white/70">
        Aunion AI X 번역의 민족
      </p>
    </div>
  )
}
