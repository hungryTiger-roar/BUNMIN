import { useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useLectureStore } from '@/stores/lectureStore'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useAudioCapture } from '@/hooks/useAudioCapture'
import { useScreenCapture } from '@/hooks/useScreenCapture'
import SubtitleDisplay from '@/components/common/SubtitleDisplay'
import SlideUpload from '@/components/lecturer/SlideUpload'
import SlideViewer from '@/components/lecturer/SlideViewer'
import ConnectionStatus from '@/components/common/ConnectionStatus'
import { WS_BASE } from '@/lib/api'

const WS_URL = `${WS_BASE}/ws/pipeline`

function Lecturer() {
  const navigate = useNavigate()

  const {
    isMicOn,
    isLectureStarted,
    isPaused,
    presentationMode,
    slideId,
    slideStatus,
    currentPage,
    totalPages,
    subtitles,
    setMicOn,
    setLectureStarted,
    setPaused,
    setPresentationMode,
    reset,
  } = useLectureStore()

  const { isConnected, connect, send } = useWebSocket(WS_URL, 'lecturer')

  // 오디오 데이터 전송
  const handleAudioData = useCallback(async (audioBlob: Blob) => {
    const arrayBuffer = await audioBlob.arrayBuffer()
    const base64 = btoa(
      new Uint8Array(arrayBuffer).reduce((data, byte) => data + String.fromCharCode(byte), '')
    )
    send({ type: 'audio', audio: base64, sample_rate: 16000 })
  }, [send])

  // 화면 캡처 데이터 전송
  const handleScreenData = useCallback((imageData: string) => {
    if (!isPaused && isConnected) {
      send({ type: 'screen', data: imageData })
    }
  }, [send, isPaused, isConnected])

  const {
    startCapture: startAudioCapture,
    stopCapture: stopAudioCapture,
  } = useAudioCapture({ onAudioData: handleAudioData })

  const {
    isCapturing: isScreenSharing,
    startCapture: startScreenCapture,
    stopCapture: stopScreenCapture,
  } = useScreenCapture({ onFrame: handleScreenData, frameRate: 2 })

  // 서버 연결
  useEffect(() => {
    connect()
  }, [connect])

  // 슬라이드 선택 시 서버에 알림
  useEffect(() => {
    if (slideStatus === 'ready' && slideId && isConnected && presentationMode === 'slide') {
      send({ type: 'slide_select', slide_id: slideId })
    }
  }, [slideStatus, slideId, isConnected, send, presentationMode])

  // 페이지 변경 시 서버에 알림
  const handlePageChange = useCallback((page: number) => {
    if (isConnected && slideId && !isPaused) {
      send({ type: 'page_change', slide_id: slideId, page })
    }
  }, [isConnected, slideId, send, isPaused])

  // 마이크 토글
  const toggleMic = async () => {
    if (isMicOn) {
      stopAudioCapture()
      setMicOn(false)
    } else {
      await startAudioCapture()
      setMicOn(true)
    }
  }

  // 화면공유 토글
  const toggleScreenShare = async () => {
    if (isScreenSharing) {
      stopScreenCapture()
    } else {
      await startScreenCapture()
    }
  }

  // 강의 시작
  const startLecture = () => {
    if (presentationMode === 'slide' && slideStatus !== 'ready') {
      alert('강의자료를 먼저 업로드하세요.')
      return
    }
    setLectureStarted(true)
    setPaused(false)
    send({ type: 'lecture_start', slide_id: slideId, mode: presentationMode })
  }

  // 강의 일시정지
  const togglePause = () => {
    const newPaused = !isPaused
    setPaused(newPaused)
    send({ type: newPaused ? 'lecture_pause' : 'lecture_resume' })
  }

  // 강의 종료
  const endLecture = () => {
    stopAudioCapture()
    stopScreenCapture()
    setLectureStarted(false)
    setPaused(false)
    send({ type: 'lecture_end', slide_id: slideId })
  }

  // 페이지 나가기
  const handleExit = () => {
    stopAudioCapture()
    stopScreenCapture()
    reset()
    navigate('/')
  }

  // 강의 시작 가능 여부
  const canStartLecture = isConnected && (
    presentationMode === 'screen' || slideStatus === 'ready'
  )

  return (
    <div className="min-h-screen bg-slate-100 p-6">
      {/* 헤더 */}
      <header className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-bold text-slate-800">강의자 모드</h1>
          <ConnectionStatus isConnected={isConnected} />
          {isLectureStarted && (
            <span className={`px-3 py-1 text-white text-sm font-medium rounded-full ${
              isPaused ? 'bg-yellow-500' : 'bg-red-500 animate-pulse'
            }`}>
              {isPaused ? '일시정지' : 'LIVE'}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          {!isLectureStarted ? (
            <button
              onClick={startLecture}
              disabled={!canStartLecture}
              className="px-4 py-2 bg-green-500 hover:bg-green-600 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              강의 시작
            </button>
          ) : (
            <>
              <button
                onClick={togglePause}
                className={`px-4 py-2 rounded-lg transition-colors ${
                  isPaused
                    ? 'bg-green-500 hover:bg-green-600 text-white'
                    : 'bg-yellow-500 hover:bg-yellow-600 text-white'
                }`}
              >
                {isPaused ? '다시 시작' : '일시정지'}
              </button>
              <button
                onClick={endLecture}
                className="px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg transition-colors"
              >
                강의 종료
              </button>
            </>
          )}
          <button
            onClick={handleExit}
            className="px-4 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-lg transition-colors"
          >
            나가기
          </button>
        </div>
      </header>

      {/* 모드 선택 */}
      <div className="mb-6 flex gap-2">
        <button
          onClick={() => {
            if (presentationMode !== 'slide') {
              // 화면공유 중이면 중지
              if (isScreenSharing) {
                stopScreenCapture()
              }
              setPresentationMode('slide')
              // 강의 중이면 서버에 알림
              if (isLectureStarted) {
                send({ type: 'presentation_mode', mode: 'slide' })
                // 현재 슬라이드 정보 전송
                if (slideId) {
                  send({ type: 'slide_select', slide_id: slideId })
                  send({ type: 'page_change', slide_id: slideId, page: currentPage })
                }
              }
            }
          }}
          className={`px-4 py-2 rounded-lg font-medium transition-colors ${
            presentationMode === 'slide'
              ? 'bg-blue-500 text-white'
              : 'bg-white text-slate-600 hover:bg-slate-50'
          }`}
        >
          강의자료 모드
        </button>
        <button
          onClick={() => {
            if (presentationMode !== 'screen') {
              setPresentationMode('screen')
              // 강의 중이면 서버에 알림
              if (isLectureStarted) {
                send({ type: 'presentation_mode', mode: 'screen' })
              }
            }
          }}
          className={`px-4 py-2 rounded-lg font-medium transition-colors ${
            presentationMode === 'screen'
              ? 'bg-blue-500 text-white'
              : 'bg-white text-slate-600 hover:bg-slate-50'
          }`}
        >
          화면공유 모드
        </button>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* 메인 영역 */}
        <div className="col-span-2 space-y-4">
          {presentationMode === 'slide' ? (
            /* 슬라이드 뷰어 */
            <SlideViewer onPageChange={handlePageChange} />
          ) : (
            /* 화면공유 영역 */
            <div className="bg-slate-900 rounded-xl overflow-hidden aspect-video flex items-center justify-center">
              {isScreenSharing ? (
                <div className="text-center text-white">
                  <div className="w-16 h-16 mx-auto mb-4 bg-red-500 rounded-full flex items-center justify-center animate-pulse">
                    <svg className="w-8 h-8" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M21 3H3c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H3V5h18v14z"/>
                    </svg>
                  </div>
                  <p className="text-lg font-medium">화면 공유 중</p>
                  <p className="text-sm text-slate-400 mt-1">학생들에게 화면이 전송되고 있습니다</p>
                  <button
                    onClick={stopScreenCapture}
                    className="mt-4 px-4 py-2 bg-red-500 hover:bg-red-600 rounded-lg transition-colors"
                  >
                    공유 중지
                  </button>
                </div>
              ) : (
                <div className="text-center text-slate-500">
                  <svg className="w-16 h-16 mx-auto mb-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                  </svg>
                  <p>화면을 공유하세요</p>
                  <button
                    onClick={startScreenCapture}
                    disabled={!isLectureStarted}
                    className="mt-4 px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    화면 공유 시작
                  </button>
                  {!isLectureStarted && (
                    <p className="text-xs text-slate-400 mt-2">강의를 시작하면 화면을 공유할 수 있습니다</p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* 실시간 자막 */}
          <div className="bg-white rounded-xl p-4 shadow-sm">
            <h3 className="text-sm font-medium text-slate-500 mb-3">실시간 자막</h3>
            <SubtitleDisplay subtitles={subtitles} maxItems={3} />
          </div>
        </div>

        {/* 사이드바 - 컨트롤 */}
        <div className="space-y-4">
          {/* 슬라이드 업로드 (강의자료 모드일 때만) */}
          {presentationMode === 'slide' && <SlideUpload />}

          {/* 컨트롤 버튼 */}
          <div className="bg-white rounded-xl p-4 shadow-sm space-y-3">
            <h3 className="text-sm font-medium text-slate-500 mb-3">강의 컨트롤</h3>

            {/* 마이크 */}
            <button
              onClick={toggleMic}
              disabled={!isConnected || !isLectureStarted}
              className={`w-full py-3 px-4 rounded-lg font-medium transition-colors flex items-center justify-center gap-2 ${
                isMicOn
                  ? 'bg-green-500 hover:bg-green-600 text-white'
                  : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
              } disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {isMicOn ? (
                <>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                  </svg>
                  마이크 ON
                </>
              ) : (
                <>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                  </svg>
                  마이크 OFF
                </>
              )}
            </button>

            {/* 안내 메시지 */}
            {!isLectureStarted && (
              <p className="text-xs text-slate-400 text-center">
                강의를 시작하면 마이크를 사용할 수 있습니다
              </p>
            )}
          </div>

          {/* 상태 표시 */}
          <div className="bg-white rounded-xl p-4 shadow-sm">
            <h3 className="text-sm font-medium text-slate-500 mb-3">상태</h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-500">모드</span>
                <span className="text-slate-700">
                  {presentationMode === 'slide' ? '강의자료' : '화면공유'}
                </span>
              </div>
              {presentationMode === 'slide' && (
                <>
                  <div className="flex justify-between">
                    <span className="text-slate-500">강의자료</span>
                    <span className={slideStatus === 'ready' ? 'text-green-600' : 'text-slate-400'}>
                      {slideStatus === 'none' && '업로드 필요'}
                      {slideStatus === 'uploading' && '업로드 중...'}
                      {slideStatus === 'processing' && '처리 중...'}
                      {slideStatus === 'ready' && `준비됨 (${totalPages}페이지)`}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">현재 페이지</span>
                    <span className="text-slate-700 font-medium">
                      {slideStatus === 'ready' ? `${currentPage} / ${totalPages}` : '-'}
                    </span>
                  </div>
                </>
              )}
              {presentationMode === 'screen' && (
                <div className="flex justify-between">
                  <span className="text-slate-500">화면공유</span>
                  <span className={isScreenSharing ? 'text-green-600' : 'text-slate-400'}>
                    {isScreenSharing ? '공유 중' : '대기'}
                  </span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-slate-500">마이크</span>
                <span className={isMicOn ? 'text-green-600' : 'text-slate-400'}>
                  {isMicOn ? 'ON' : 'OFF'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">강의 상태</span>
                <span className={isLectureStarted ? (isPaused ? 'text-yellow-600' : 'text-green-600') : 'text-slate-400'}>
                  {!isLectureStarted ? '대기' : (isPaused ? '일시정지' : '진행 중')}
                </span>
              </div>
            </div>
          </div>

          {/* 단축키 안내 */}
          {presentationMode === 'slide' && (
            <div className="bg-white rounded-xl p-4 shadow-sm">
              <h3 className="text-sm font-medium text-slate-500 mb-3">단축키</h3>
              <div className="space-y-1 text-xs text-slate-500">
                <div className="flex justify-between">
                  <span>다음 슬라이드</span>
                  <kbd className="px-2 py-0.5 bg-slate-100 rounded">→</kbd>
                </div>
                <div className="flex justify-between">
                  <span>이전 슬라이드</span>
                  <kbd className="px-2 py-0.5 bg-slate-100 rounded">←</kbd>
                </div>
                <div className="flex justify-between">
                  <span>다음 슬라이드</span>
                  <kbd className="px-2 py-0.5 bg-slate-100 rounded">Space</kbd>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default Lecturer
