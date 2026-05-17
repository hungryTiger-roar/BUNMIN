import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useLectureStore } from '../stores/lectureStore'
import { usePreferencesStore, type AudioLang, type SubtitleLang } from '../stores/preferencesStore'

const STORAGE_KEY = 'student_name'

const TEXT = {
  ko: {
    subtitle: 'AI 기반 실시간 강의 번역 시스템',
    prompt: '강의 참여를 위해 이름을 입력해주세요.',
    nameLabel: '이름',
    namePlaceholder: '이름을 입력.',
    nameError: '이름을 입력하여야 강의에 참여할 수 있습니다.',
    saveInfo: '다음에도 사용하기',
    joinButton: '강의 참여',
    footer: 'Aunion AI X 번역의 민족',
    subtitleLangLabel: '자막 언어',
    audioLangLabel: '음성 언어',
  },
  en: {
    subtitle: 'Real-time AI Lecture Translation',
    prompt: 'Please enter your name to join the lecture.',
    nameLabel: 'Name',
    namePlaceholder: 'Enter your name.',
    nameError: 'Please enter your name to join the lecture.',
    saveInfo: 'Remember me',
    joinButton: 'Join Lecture',
    footer: 'Aunion AI X Bunmin',
    subtitleLangLabel: 'Subtitle language',
    audioLangLabel: 'Audio language',
  },
} as const

// 자막 옵션 — NMT 가 한→영 만 지원하므로 실제 작동하는 값만 노출.
// 'off' 는 Start 화면에선 굳이 노출 안 함 (Student 페이지에서 토글 가능).
const LANG_OPTIONS: { value: SubtitleLang; label: string }[] = [
  { value: 'ko', label: '한국어 (Korean)' },
  { value: 'en', label: '영어 (English)' },
]

// 음성 옵션 — 한국어 원본 (WebRTC) / 영어 TTS 둘만.
const AUDIO_LANG_OPTIONS: { value: AudioLang; label: string }[] = [
  { value: 'original', label: '원본 (Original)' },
  { value: 'en', label: '영어 (English)' },
]

export default function Start() {
  const navigate = useNavigate()
  const setStudentName = useLectureStore((s) => s.setStudentName)

  const lang = usePreferencesStore((s) => s.lang)
  const setLang = usePreferencesStore((s) => s.setLang)

  const subtitleLang = usePreferencesStore((s) => s.subtitleLang)
  const setSubtitleLang = usePreferencesStore((s) => s.setSubtitleLang)
  const audioLang = usePreferencesStore((s) => s.audioLang)
  const setAudioLang = usePreferencesStore((s) => s.setAudioLang)

  const [name, setName] = useState('')
  const [saveInfo, setSaveInfo] = useState(false)
  const [error, setError] = useState('')

  const t = TEXT[lang]
  // AudioLang = 'original' | 'en' 두 값만 → 영어 폴백 안내 불필요 (모든 옵션이 즉시 작동).

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      setName(saved)
      setSaveInfo(true)
    }
    // 이전에 저장된 'off'/'both'/'ko' 등 옵션에 없는 값이 있으면 'en'으로 정리
    if (!AUDIO_LANG_OPTIONS.some((o) => o.value === audioLang)) setAudioLang('en')
    if (!LANG_OPTIONS.some((o) => o.value === subtitleLang)) setSubtitleLang('en')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Student 페이지는 무거운 청크(piper-tts-web / onnxruntime-web)라 lazy 로 분리돼 있다.
  // 이름 입력 화면에 머무는 동안 idle 시점에 미리 받아두면 '강의 참여' 클릭 시 체감 지연 0.
  useEffect(() => {
    const prefetch = () => { void import('./Student') }
    const ric = (window as unknown as { requestIdleCallback?: (cb: () => void) => number }).requestIdleCallback
    if (ric) ric(prefetch)
    else { const id = window.setTimeout(prefetch, 1500); return () => window.clearTimeout(id) }
  }, [])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) {
      setError(t.nameError)
      return
    }

    if (saveInfo) {
      localStorage.setItem(STORAGE_KEY, trimmed)
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }

    setStudentName(trimmed)
    navigate('/student', { state: { autoEnter: true } })
  }

  return (
    <div className="relative min-h-screen bg-white flex flex-col items-center justify-center px-4">
      <button
        type="button"
        role="switch"
        aria-checked={lang === 'en'}
        aria-label="언어 전환 (한국어 / English)"
        onClick={() => setLang(lang === 'ko' ? 'en' : 'ko')}
        className="absolute top-6 right-6 flex items-center border border-gray-200 bg-white rounded-full p-1 hover:bg-gray-50 transition-colors"
      >
        <span
          className={`px-3 py-1 text-sm rounded-full transition-colors ${
            lang === 'ko' ? 'bg-bunmin text-white' : 'text-gray-600'
          }`}
        >
          한
        </span>
        <span
          className={`px-3 py-1 text-sm rounded-full transition-colors ${
            lang === 'en' ? 'bg-bunmin text-white' : 'text-gray-600'
          }`}
        >
          EN
        </span>
      </button>

      {/* 타이틀 — 로고 + '번역의'/'BUN'(보라) + '민족'/'MIN'(검정) */}
      <div className="flex flex-col items-center mb-12">
        <div className="flex items-center justify-center gap-4 mb-4">
          <img src="/bm-logo-cut.png" alt="번역의 민족" className="w-20 h-20 object-contain" />
          <h1 className={`text-7xl leading-none ${lang === 'ko' ? 'font-eland' : 'font-special-gothic'}`}>
            {lang === 'ko' ? (
              <>
                <span className="text-bunmin">번역의</span>
                <span className="text-gray-900"> 민족</span>
              </>
            ) : (
              <>
                <span className="text-bunmin">BUN</span>
                <span className="text-gray-900">MIN</span>
              </>
            )}
          </h1>
        </div>
        {/* 보라색 둥근 테두리 안의 소제목 + 돋보기 */}
        <div className="flex items-center justify-between gap-3 border-2 border-bunmin rounded-full px-5 py-2 w-full max-w-md">
          <p className="text-bunmin font-semibold text-sm tracking-wide">
            {t.subtitle}
          </p>
          <svg className="w-5 h-5 text-bunmin shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M21 21l-4.35-4.35M17 11a6 6 0 11-12 0 6 6 0 0112 0z" />
          </svg>
        </div>
      </div>

      <h2 className="font-a2z text-gray-800 text-2xl mb-8 leading-snug whitespace-nowrap tracking-wide">
        {t.prompt}
      </h2>

      <div className="w-full max-w-sm">
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <div className="relative">
              <input
                type="text"
                value={name}
                onChange={(e) => {
                  setName(e.target.value)
                  setError('')
                }}
                placeholder={t.namePlaceholder}
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

          {/* 음성 / 자막 언어 미리 설정 — 강의중 화면(Audio | Subtitles) 순서와 동일 */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-gray-700 text-sm mb-1.5 block">
                {t.audioLangLabel}
              </label>
              <select
                value={audioLang}
                onChange={(e) => setAudioLang(e.target.value as AudioLang)}
                className="w-full bg-white border border-gray-300 rounded-full px-4 py-2.5 text-gray-900 focus:outline-none focus:ring-2 focus:ring-bunmin focus:border-bunmin appearance-none"
              >
                {AUDIO_LANG_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-gray-700 text-sm mb-1.5 block">
                {t.subtitleLangLabel}
              </label>
              <select
                value={subtitleLang}
                onChange={(e) => setSubtitleLang(e.target.value as SubtitleLang)}
                className="w-full bg-white border border-gray-300 rounded-full px-4 py-2.5 text-gray-900 focus:outline-none focus:ring-2 focus:ring-bunmin focus:border-bunmin appearance-none"
              >
                {LANG_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          </div>
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={saveInfo}
              onChange={(e) => setSaveInfo(e.target.checked)}
              className="w-4 h-4 accent-bunmin"
            />
            <span className="text-gray-700 text-sm">{t.saveInfo}</span>
          </label>

          <button
            type="submit"
            className="w-full bg-bunmin hover:opacity-90 text-white font-medium py-3 rounded-full transition-all shadow-lg shadow-bunmin/20"
          >
            {t.joinButton}
          </button>
        </form>
      </div>

      <p className="absolute bottom-6 right-6 text-sm text-gray-500">
        {t.footer}
      </p>
    </div>
  )
}
