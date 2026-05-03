import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { updateTokens } from '@/lib/api'

type SaveState = 'idle' | 'saving' | 'success' | 'error'

export default function LecturerSettings() {
  const navigate = useNavigate()

  const [hfToken, setHfToken] = useState('')
  const [openaiKey, setOpenaiKey] = useState('')
  const [showHf, setShowHf] = useState(false)
  const [showOpenai, setShowOpenai] = useState(false)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [message, setMessage] = useState('')

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    const hf = hfToken.trim()
    const oa = openaiKey.trim()
    if (!hf && !oa) {
      setSaveState('error')
      setMessage('변경할 토큰을 하나 이상 입력해주세요.')
      return
    }

    setSaveState('saving')
    setMessage('')
    try {
      const res = await updateTokens({
        ...(hf ? { hf_token: hf } : {}),
        ...(oa ? { openai_api_key: oa } : {}),
      })
      setSaveState('success')
      setMessage(res.message || '저장 완료')
      setHfToken('')
      setOpenaiKey('')
    } catch (err) {
      setSaveState('error')
      setMessage(err instanceof Error ? err.message : '저장 실패')
    }
  }

  return (
    <div className="min-h-screen bg-background text-onSurface">
      {/* 헤더 */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-primaryContainer">
        <button
          type="button"
          onClick={() => navigate('/lecturer/home')}
          className="flex items-center gap-2 text-sm text-onSurface/70 hover:text-onSurface transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          홈으로
        </button>
        <h1 className="text-lg font-semibold">개인설정</h1>
        <div className="w-16" />
      </header>

      <main className="max-w-2xl mx-auto px-6 py-8">
        <section className="mb-6">
          <h2 className="text-xl font-semibold mb-2">성능 향상을 위한 토큰 입력</h2>
          <p className="text-sm text-onSurface/70">
            아래 토큰을 등록하면 모델 다운로드 속도와 슬라이드 번역 품질이 향상됩니다.
            토큰은 로컬 <code className="bg-primaryContainer/40 px-1 rounded">.env</code> 파일에만 저장되며 외부로 전송되지 않습니다.
          </p>
        </section>

        <form onSubmit={handleSave} className="space-y-6">
          {/* HuggingFace 토큰 */}
          <div className="bg-surface rounded-xl p-5 border border-primaryContainer">
            <label className="block">
              <div className="flex items-baseline justify-between mb-1">
                <span className="text-base font-medium">HuggingFace 토큰</span>
                <span className="text-xs text-onSurface/60">다운로드 속도 향상에 도움</span>
              </div>
              <p className="text-xs text-onSurface/60 mb-2">
                <a
                  href="https://huggingface.co/settings/tokens"
                  target="_blank"
                  rel="noreferrer"
                  className="text-primary underline hover:opacity-80"
                >
                  https://huggingface.co/settings/tokens
                </a>
                {' '}에서 발급
              </p>
              <div className="relative">
                <input
                  type={showHf ? 'text' : 'password'}
                  value={hfToken}
                  onChange={(e) => setHfToken(e.target.value)}
                  placeholder="HF_TOKEN"
                  autoComplete="off"
                  className="w-full bg-white rounded-lg px-3 py-2.5 pr-12 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary border border-primaryContainer"
                />
                <button
                  type="button"
                  onClick={() => setShowHf((v) => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-500 hover:text-gray-700 px-2 py-1"
                >
                  {showHf ? '숨김' : '표시'}
                </button>
              </div>
            </label>
          </div>

          {/* OpenAI API 키 */}
          <div className="bg-surface rounded-xl p-5 border border-primaryContainer">
            <label className="block">
              <div className="flex items-baseline justify-between mb-1">
                <span className="text-base font-medium">OpenAI API 키</span>
                <span className="text-xs text-onSurface/60">번역 품질에 영향 있음</span>
              </div>
              <p className="text-xs text-onSurface/60 mb-2">
                번역 시 용어집 자동 생성에 사용
                <br />
                <a
                  href="https://platform.openai.com/api-keys"
                  target="_blank"
                  rel="noreferrer"
                  className="text-primary underline hover:opacity-80"
                >
                  https://platform.openai.com/api-keys
                </a>
                {' '}에서 발급
              </p>
              <div className="relative">
                <input
                  type={showOpenai ? 'text' : 'password'}
                  value={openaiKey}
                  onChange={(e) => setOpenaiKey(e.target.value)}
                  placeholder="OPENAI_API_KEY"
                  autoComplete="off"
                  className="w-full bg-white rounded-lg px-3 py-2.5 pr-12 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary border border-primaryContainer"
                />
                <button
                  type="button"
                  onClick={() => setShowOpenai((v) => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-500 hover:text-gray-700 px-2 py-1"
                >
                  {showOpenai ? '숨김' : '표시'}
                </button>
              </div>
            </label>
          </div>

          {/* 메시지 */}
          {message && (
            <p
              className={`text-sm ${
                saveState === 'error'
                  ? 'text-error'
                  : saveState === 'success'
                    ? 'text-emerald-600'
                    : 'text-onSurface/70'
              }`}
            >
              {message}
            </p>
          )}

          {/* 안내 — 두 줄, 왼쪽 정렬 */}
          <div className="text-xs text-onSurface/50">
            <p className="whitespace-nowrap">
              ⚠️ 이미 로드된 모델은 변경 사항을 적용하려면 앱 재시작이 필요할 수 있습니다.
            </p>
            <p className="whitespace-nowrap">
              <span className="invisible" aria-hidden="true">⚠️</span> HuggingFace 토큰은 다음 모델 다운로드부터, OpenAI 키는 다음 슬라이드 업로드부터 적용됩니다.
            </p>
          </div>

          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={() => navigate('/lecturer/home')}
              className="px-5 py-2.5 rounded-lg border border-primaryContainer text-onSurface hover:bg-primaryContainer/40 transition-colors"
            >
              취소
            </button>
            <button
              type="submit"
              disabled={saveState === 'saving'}
              className="px-5 py-2.5 rounded-lg bg-primary text-onPrimary font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {saveState === 'saving' ? '저장 중...' : '저장'}
            </button>
          </div>
        </form>
      </main>
    </div>
  )
}
