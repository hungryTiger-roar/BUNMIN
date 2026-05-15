import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useLectureStore } from '../stores/lectureStore'
import { usePreferencesStore, type TranslationLang } from '../stores/preferencesStore'

const STORAGE_KEY = 'student_name'

// TTS(Piper)로 실제 음성을 낼 수 있는 언어
const TTS_SUPPORTED: TranslationLang[] = ['en', 'de', 'es', 'ru']

const TEXT = {
  ko: {
    subtitle: '실시간 AI 강의 번역 시스템',
    prompt: '강의 참여를 위해 이름을 입력해주세요.',
    nameLabel: '이름',
    namePlaceholder: '이름을 입력.',
    nameError: '이름을 입력하여야 강의에 참여할 수 있습니다.',
    saveInfo: '다음에도 사용하기',
    joinButton: '강의 참여',
    footer: 'Aunion AI X 번역의 민족',
    subtitleLangLabel: '자막 언어',
    audioLangLabel: '음성 언어',
    ttsFallbackNotice: '선택한 언어는 음성 지원이 준비 중입니다. 음성은 영어로 출력됩니다.',
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
    ttsFallbackNotice: 'Voice for this language is coming soon. Audio will be played in English.',
  },
} as const

// 자막 옵션
const LANG_OPTIONS: { value: TranslationLang; label: string }[] = [
  { value: 'ko', label: '한국어 (Korean)' },
  { value: 'en', label: '영어 (English)' },
  { value: 'de', label: '독일어 (Deutsch)' },
  { value: 'es', label: '스페인어 (Español)' },
  { value: 'ru', label: '러시아어 (Русский)' },
]

// 음성 옵션 — 강의실에서 한국어는 직접 들리므로 제외.
// 'original' 은 강의자 원본 목소리 (WebRTC), 그 외는 TTS 음성.
const AUDIO_LANG_OPTIONS: { value: TranslationLang; label: string }[] = [
  { value: 'original', label: '원본 (Original)' },
  ...LANG_OPTIONS.filter((o) => o.value !== 'ko'),
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
  // 'original' 은 강의자 원본 음성을 직접 재생 (TTS 미사용) → 폴백 안내 대상 아님.
  const audioNeedsFallback = audioLang !== 'original' && !TTS_SUPPORTED.includes(audioLang)

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
    <div className="relative min-h-screen bg-home-gradient [background-size:800%_800%] animate-gradient-shift flex flex-col items-center justify-center px-4">
      <button
        type="button"
        role="switch"
        aria-checked={lang === 'en'}
        aria-label="언어 전환 (한국어 / English)"
        onClick={() => setLang(lang === 'ko' ? 'en' : 'ko')}
        className="absolute top-6 right-6 flex items-center bg-white/20 backdrop-blur-sm rounded-full p-1 hover:bg-white/30 transition-colors"
      >
        <span
          className={`px-3 py-1 text-sm rounded-full transition-colors ${
            lang === 'ko' ? 'bg-white text-gray-900' : 'text-onPrimary'
          }`}
        >
          한
        </span>
        <span
          className={`px-3 py-1 text-sm rounded-full transition-colors ${
            lang === 'en' ? 'bg-white text-gray-900' : 'text-onPrimary'
          }`}
        >
          EN
        </span>
      </button>

      <div className="text-center mb-16">
        <h1 className={`text-6xl mb-3 text-white ${lang === 'ko' ? 'font-bold' : 'font-special-gothic'}`}>
          {lang === 'ko' ? '번역의 민족' : 'BUNMIN'}
        </h1>
        <p className="font-a2z text-white text-lg tracking-wide">
          {t.subtitle}
        </p>
      </div>

      <h2 className="font-a2z text-white text-2xl mb-8 leading-snug whitespace-nowrap tracking-wide">
        {t.prompt}
      </h2>

      <div className="w-full max-w-sm">
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="text-white/80 text-sm mb-1.5 flex items-center gap-1">
              {t.nameLabel}
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
                placeholder={t.namePlaceholder}
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

          {/* 음성 / 자막 언어 미리 설정 — 강의중 화면(Audio | Subtitles) 순서와 동일 */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-white/80 text-sm mb-1.5 block">
                {t.audioLangLabel}
              </label>
              <select
                value={audioLang}
                onChange={(e) => setAudioLang(e.target.value as TranslationLang)}
                className="w-full bg-white rounded-full px-4 py-2.5 text-gray-900 focus:outline-none focus:ring-2 focus:ring-onPrimary appearance-none"
              >
                {AUDIO_LANG_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-white/80 text-sm mb-1.5 block">
                {t.subtitleLangLabel}
              </label>
              <select
                value={subtitleLang}
                onChange={(e) => setSubtitleLang(e.target.value as TranslationLang)}
                className="w-full bg-white rounded-full px-4 py-2.5 text-gray-900 focus:outline-none focus:ring-2 focus:ring-onPrimary appearance-none"
              >
                {LANG_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          </div>
          {audioNeedsFallback && (
            <p className="text-xs text-white/80 -mt-2">
              ⚠️ {t.ttsFallbackNotice}
            </p>
          )}

          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={saveInfo}
              onChange={(e) => setSaveInfo(e.target.checked)}
              className="w-4 h-4 accent-primary"
            />
            <span className="text-white/80 text-sm">{t.saveInfo}</span>
          </label>

          <button
            type="submit"
            className="w-full bg-primary hover:opacity-90 text-onPrimary font-medium py-3 rounded-full transition-all shadow-lg shadow-primary/20"
          >
            {t.joinButton}
          </button>
        </form>
      </div>

      <p className="absolute bottom-6 right-6 text-sm text-white/70">
        {t.footer}
      </p>
    </div>
  )
}
