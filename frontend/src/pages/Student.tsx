import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useLectureStore } from '@/stores/lectureStore'
import { useWebSocket } from '@/hooks/useWebSocket'
import SubtitleDisplay from '@/components/common/SubtitleDisplay'
import ConnectionStatus from '@/components/common/ConnectionStatus'
import ScreenOverlay from '@/components/student/ScreenOverlay'
import ViewToggle from '@/components/student/ViewToggle'

const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
const WS_URL = `${wsProtocol}//${window.location.host}/ws/pipeline`

function Student() {
  const navigate = useNavigate()

  const {
    viewMode,
    isAudioOn,
    isSubtitleOn,
    subtitles,
    overlayItems,
    currentScreen,
    setAudioOn,
    setSubtitleOn,
  } = useLectureStore()

  const { isConnected, isAudioUnlocked, connect, unlockAudio } = useWebSocket(WS_URL, 'student')

  // 서버 연결
  useEffect(() => {
    connect()
  }, [connect])

  // 나가기
  const handleExit = () => {
    navigate('/')
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* 헤더 */}
      <header className="flex items-center justify-between p-4 bg-slate-800/50 backdrop-blur-sm fixed top-0 left-0 right-0 z-50">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-medium">Aunion AI</h1>
          <ConnectionStatus isConnected={isConnected} />
        </div>

        <div className="flex items-center gap-3">
          <ViewToggle />
          <button
            onClick={handleExit}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors text-sm"
          >
            나가기
          </button>
        </div>
      </header>

      {/* 메인 컨텐츠 */}
      <main className="pt-16 pb-32 min-h-screen flex items-center justify-center">
        <div className="w-full max-w-6xl mx-auto px-4">
          {/* 화면 표시 영역 */}
          <div className="relative bg-black rounded-xl overflow-hidden aspect-video">
            {currentScreen ? (
              <>
                {/* 원본 화면 */}
                <img
                  src={`data:image/jpeg;base64,${currentScreen}`}
                  alt="강의 화면"
                  className="w-full h-full object-contain"
                />

                {/* 번역 오버레이 (번역 모드일 때만) */}
                {viewMode === 'translated' && (
                  <ScreenOverlay items={overlayItems} />
                )}
              </>
            ) : (
              <div className="absolute inset-0 flex items-center justify-center text-slate-500">
                <div className="text-center">
                  <svg className="w-20 h-20 mx-auto mb-4 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                  <p className="text-lg">강의 시작 대기 중...</p>
                  <p className="text-sm mt-2 opacity-60">강의자가 화면을 공유하면 표시됩니다</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>

      {/* 하단 자막 영역 */}
      <footer className="fixed bottom-0 left-0 right-0 bg-gradient-to-t from-slate-900 via-slate-900/95 to-transparent pt-8 pb-6 px-4">
        <div className="max-w-4xl mx-auto">
          {isSubtitleOn && (
            <SubtitleDisplay
              subtitles={subtitles}
              maxItems={2}
              variant="dark"
            />
          )}

          {/* 컨트롤 */}
          <div className="flex items-center justify-center gap-4 mt-4">
            {/* 음성 토글 */}
            <button
              onClick={() => {
                if (!isAudioUnlocked) {
                  unlockAudio()
                }
                setAudioOn(!isAudioOn)
              }}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                isAudioOn && isAudioUnlocked
                  ? 'bg-blue-500 text-white'
                  : 'bg-slate-700 text-slate-300'
              }`}
            >
              {isAudioOn ? (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" />
                </svg>
              )}
              <span className="text-sm">{isAudioUnlocked ? '음성' : '음성 (클릭하여 활성화)'}</span>
            </button>

            {/* 자막 토글 */}
            <button
              onClick={() => setSubtitleOn(!isSubtitleOn)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                isSubtitleOn
                  ? 'bg-blue-500 text-white'
                  : 'bg-slate-700 text-slate-300'
              }`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z" />
              </svg>
              <span className="text-sm">자막</span>
            </button>
          </div>
        </div>
      </footer>
    </div>
  )
}

export default Student
