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
    <div className="relative min-h-screen bg-white flex flex-col items-center justify-center px-4">
      {/* 우측 상단 개인설정 버튼 — TODO: /lecturer/settings 라우트 미구현 상태 (dev 디자인이 선반영) */}
      <button
        type="button"
        onClick={() => navigate('/lecturer/settings')}
        aria-label="개인설정"
        className="absolute top-6 right-6 flex items-center gap-2 px-4 py-2 border border-gray-200 bg-white rounded-full text-gray-700 text-sm hover:bg-gray-50 transition-colors"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        개인설정
      </button>

      {/* 타이틀 — 로고 + '번역의'(보라) '민족'(검정) */}
      <div className="flex flex-col items-center mb-12">
        <div className="flex items-center justify-center gap-4 mb-4">
          <img src="/bm-logo-cut.png" alt="번역의 민족" className="w-20 h-20 object-contain" />
          <h1 className="text-7xl font-eland leading-none">
            <span className="text-bunmin">번역의</span>
            <span className="text-gray-900"> 민족</span>
          </h1>
        </div>
        {/* 보라색 둥근 테두리 안의 소제목 + 돋보기 */}
        <div className="flex items-center justify-between gap-3 border-2 border-bunmin rounded-full px-5 py-2 w-full max-w-md">
          <p className="text-bunmin font-semibold text-sm tracking-wide">
            AI 기반 실시간 강의 번역 시스템
          </p>
          <svg className="w-5 h-5 text-bunmin shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M21 21l-4.35-4.35M17 11a6 6 0 11-12 0 6 6 0 0112 0z" />
          </svg>
        </div>
      </div>

      <h2 className="font-a2z text-gray-800 text-2xl mb-8 leading-snug whitespace-nowrap tracking-wide">
        강의자 이름을 입력해주세요.
      </h2>

      <div className="w-full max-w-sm">
        <form onSubmit={handleStart} className="space-y-5">
          <div>
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
                className="w-full bg-white border border-gray-300 rounded-full px-4 py-2.5 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-bunmin focus:border-bunmin pr-10"
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
              className="w-4 h-4 accent-bunmin"
            />
            <span className="text-gray-700 text-sm">다음에도 이름 사용하기</span>
          </label>

          <button
            type="submit"
            className="w-full bg-bunmin hover:opacity-90 text-white font-medium py-3 rounded-full transition-all shadow-lg shadow-bunmin/20"
          >
            강의 준비
          </button>
        </form>
      </div>

      <p className="absolute bottom-6 right-6 text-sm text-gray-500">
        Aunion AI X 번역의 민족
      </p>
    </div>
  )
}
