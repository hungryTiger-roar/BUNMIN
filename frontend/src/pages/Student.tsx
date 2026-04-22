import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useLectureStore } from '@/stores/lectureStore'
import { useWebSocket } from '@/hooks/useWebSocket'
import SubtitleDisplay from '@/components/common/SubtitleDisplay'
import ConnectionStatus from '@/components/common/ConnectionStatus'
import ViewToggle from '@/components/student/ViewToggle'
import { WS_PIPELINE_URL, API_BASE } from '@/lib/api'

function Student() {
  const navigate = useNavigate()
  const [toast, setToast] = useState<string | null>(null)

  const {
    slideId,
    slideStatus,
    currentPage,
    totalPages,
    slidePages,
    isLectureStarted,
    isPaused,
    presentationMode,
    currentScreen,
    isAudioOn,
    isSubtitleOn,
    subtitles,
    viewMode,
    setAudioOn,
    setSubtitleOn,
  } = useLectureStore()

  const { isConnected, isAudioUnlocked, connect, unlockAudio } = useWebSocket(WS_PIPELINE_URL, 'student')

  // 서버 연결
  useEffect(() => {
    connect()
  }, [connect])

  // 토스트 자동 숨김
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 2000)
      return () => clearTimeout(timer)
    }
  }, [toast])

  // 나가기
  const handleExit = () => {
    navigate('/')
  }

  // PDF 다운로드
  const handleDownload = (type: 'original' | 'translated') => {
    if (!slideId) return
    const url = `${API_BASE}/slides/download/${slideId}?type=${type}`
    window.open(url, '_blank')
  }

  // 현재 슬라이드 이미지 URL (원본/번역 모드에 따라)
  const currentSlideImage = slidePages[currentPage - 1]?.imageUrl
  const slideImageUrl = currentSlideImage
    ? `${API_BASE}${currentSlideImage}${viewMode === 'translated' ? '?translated=true' : ''}`
    : null

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* 토스트 알림 */}
      {toast && (
        <div className="fixed top-20 left-1/2 -translate-x-1/2 z-[100] animate-fade-in">
          <div className="px-4 py-2 bg-slate-700 text-white rounded-lg shadow-lg text-sm">
            {toast}
          </div>
        </div>
      )}

      {/* 헤더 */}
      <header className="flex items-center justify-between p-4 bg-slate-800/50 backdrop-blur-sm fixed top-0 left-0 right-0 z-50">
        {/* 왼쪽: 로고, 연결상태, LIVE */}
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-medium">Aunion AI</h1>
          <ConnectionStatus isConnected={isConnected} />
          {isLectureStarted && (
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600 text-white text-sm font-semibold rounded-lg shadow-lg shadow-red-500/30">
                <span className="w-2 h-2 bg-white rounded-full animate-pulse" />
                LIVE
              </span>
              {isPaused && (
                <span className="px-3 py-1.5 bg-yellow-600 text-white text-sm font-semibold rounded-lg">
                  일시정지
                </span>
              )}
              {presentationMode === 'screen' && (
                <span className="px-3 py-1.5 bg-purple-600 text-white text-sm rounded-lg">
                  화면공유
                </span>
              )}
            </div>
          )}
        </div>

        {/* 가운데: 페이지 번호 */}
        {slideStatus === 'ready' && totalPages > 0 && (
          <div className="absolute left-1/2 -translate-x-1/2 flex items-center gap-2 px-4 py-1.5 bg-slate-700 rounded-full">
            <span className="text-white font-medium">{currentPage}</span>
            <span className="text-slate-400">/</span>
            <span className="text-slate-400">{totalPages}</span>
          </div>
        )}

        {/* 오른쪽: 버튼들 */}
        <div className="flex items-center gap-3">
          {/* 원본/번역 토글 */}
          <ViewToggle />

          {/* PDF 다운로드 버튼 */}
          {slideStatus === 'ready' && (
            <>
              <button
                onClick={() => handleDownload('original')}
                className="flex items-center gap-2 px-3 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors text-sm"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                원본 PDF
              </button>
              <button
                onClick={() => handleDownload('translated')}
                className="flex items-center gap-2 px-3 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors text-sm"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                번역본 PDF
              </button>
            </>
          )}
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
          {/* 슬라이드/화면공유 표시 영역 */}
          <div className="relative bg-black rounded-xl overflow-hidden aspect-video">
            {/* 일시정지 오버레이 */}
            {isPaused && isLectureStarted && (
              <div className="absolute inset-0 bg-slate-900/90 flex items-center justify-center z-20">
                <div className="text-center">
                  <svg className="w-16 h-16 mx-auto mb-4 text-yellow-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <p className="text-xl font-medium text-white">잠시 후 계속됩니다</p>
                  <p className="text-sm mt-2 text-slate-400">강의자가 강의를 일시정지했습니다</p>
                </div>
              </div>
            )}

            {/* 화면공유 모드 */}
            {presentationMode === 'screen' && currentScreen ? (
              <img
                src={`data:image/jpeg;base64,${currentScreen}`}
                alt="화면 공유"
                className="w-full h-full object-contain"
              />
            ) : slideStatus === 'ready' && slideImageUrl ? (
              <img
                key={`${currentPage}-${viewMode}`}
                src={slideImageUrl}
                alt={`슬라이드 ${currentPage}`}
                className="w-full h-full object-contain"
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center text-slate-500">
                <div className="text-center">
                  {!isConnected ? (
                    <>
                      <svg className="w-20 h-20 mx-auto mb-4 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M18.364 5.636a9 9 0 010 12.728m0 0l-2.829-2.829m2.829 2.829L21 21M15.536 8.464a5 5 0 010 7.072m0 0l-2.829-2.829m-4.243 2.829a4.978 4.978 0 01-1.414-2.83m-1.414 5.658a9 9 0 01-2.167-9.238m7.824 2.167a1 1 0 111.414 1.414m-1.414-1.414L3 3m8.293 8.293l1.414 1.414" />
                      </svg>
                      <p className="text-lg">서버 연결 중...</p>
                      <p className="text-sm mt-2 opacity-60">잠시만 기다려주세요</p>
                    </>
                  ) : !isLectureStarted ? (
                    <>
                      <svg className="w-20 h-20 mx-auto mb-4 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      <p className="text-lg">강의 시작 대기 중...</p>
                      <p className="text-sm mt-2 opacity-60">강의자가 강의를 시작하면 표시됩니다</p>
                    </>
                  ) : presentationMode === 'screen' ? (
                    <>
                      <svg className="w-20 h-20 mx-auto mb-4 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                      </svg>
                      <p className="text-lg">화면 공유 대기 중...</p>
                      <p className="text-sm mt-2 opacity-60">강의자가 화면을 공유하면 표시됩니다</p>
                    </>
                  ) : (
                    <>
                      <svg className="w-20 h-20 mx-auto mb-4 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      <p className="text-lg">강의자료 로딩 중...</p>
                      <p className="text-sm mt-2 opacity-60">강의 자료를 불러오고 있습니다</p>
                    </>
                  )}
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
