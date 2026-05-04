import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePreferencesStore } from '@/stores/preferencesStore'

export default function LecturerHome() {
  const navigate = useNavigate()
  const lecturerName = usePreferencesStore((s) => s.lecturerName)
  const setLecturerName = usePreferencesStore((s) => s.setLecturerName)

  const [name, setName] = useState(lecturerName)
  const [error, setError] = useState('')

  const handleStart = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) {
      setError('이름을 입력해주세요.')
      return
    }
    setLecturerName(trimmed)
    navigate('/lecturer')
  }

  return (
    <div className="relative min-h-screen bg-home-gradient [background-size:800%_800%] animate-gradient-shift flex flex-col items-center justify-center px-4">
      {/* 우측 상단 개인설정 버튼 */}
      <button
        type="button"
        onClick={() => navigate('/lecturer/settings')}
        aria-label="개인설정"
        className="absolute top-6 right-6 flex items-center gap-2 px-4 py-2 bg-white/20 backdrop-blur-sm rounded-full text-white text-sm hover:bg-white/30 transition-colors"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        개인설정
      </button>

      {/* 타이틀 */}
      <div className="text-center mb-16">
        <h1 className="text-6xl font-special-gothic text-white mb-3">
          Aunion AI LECTURE
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
