import { useNavigate } from 'react-router-dom'
import { usePreferencesStore } from '../stores/preferencesStore'

function Home() {
  const navigate = useNavigate()
  const lang = usePreferencesStore((s) => s.lang)

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-home-gradient [background-size:800%_800%] animate-gradient-shift">
      <div className="text-center mb-12">
        <h1 className={`text-4xl mb-3 text-onPrimary ${lang === 'ko' ? 'font-bold' : 'font-special-gothic'}`}>
          {lang === 'ko' ? '번역의 민족' : 'BUNMIN'}
        </h1>
        <p className="text-onPrimary/80 text-lg">
          실시간 AI 강의 번역 시스템
        </p>
      </div>

      <div className="flex flex-col gap-4 w-80">
        <button
          onClick={() => navigate('/lecturer')}
          className="w-full py-4 px-6 bg-primary hover:opacity-90 text-onPrimary font-medium rounded-xl transition-all shadow-lg shadow-primary/20"
        >
          <div className="flex items-center justify-center gap-3">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            <span>강의자로 시작</span>
          </div>
        </button>

        <button
          onClick={() => navigate('/student')}
          className="w-full py-4 px-6 bg-surface hover:bg-primaryContainer text-onSurface font-medium rounded-xl transition-colors border border-tertiary/20 shadow-sm"
        >
          <div className="flex items-center justify-center gap-3">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
            </svg>
            <span>수강자로 참여</span>
          </div>
        </button>
      </div>

      <p className="mt-12 text-sm text-onPrimary/70">
        Aunion AI X 번역의 민족
      </p>
    </div>
  )
}

export default Home
