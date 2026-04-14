import { useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useLectureStore } from '@/stores/lectureStore'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useAudioCapture } from '@/hooks/useAudioCapture'
import { useScreenCapture } from '@/hooks/useScreenCapture'
import SubtitleDisplay from '@/components/common/SubtitleDisplay'
import SlideUpload from '@/components/lecturer/SlideUpload'
import ConnectionStatus from '@/components/common/ConnectionStatus'

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws/pipeline'

function Lecturer() {
  const navigate = useNavigate()
  const previewRef = useRef<HTMLVideoElement>(null)

  const {
    isMicOn,
    isScreenSharing,
    slideId,
    slideStatus,
    subtitles,
    setMicOn,
    setScreenSharing,
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

  // 화면 캡처 전송
  const handleScreenCapture = useCallback((imageData: string) => {
    send({ type: 'screen', data: imageData, slide_id: slideId })
  }, [send, slideId])

  const {
    isCapturing: isAudioCapturing,
    startCapture: startAudioCapture,
    stopCapture: stopAudioCapture,
  } = useAudioCapture({ onAudioData: handleAudioData })

  const {
    isSharing,
    startCapture: startScreenCapture,
    stopCapture: stopScreenCapture,
    getPreviewStream,
  } = useScreenCapture({ onScreenCapture: handleScreenCapture })

  // 서버 연결
  useEffect(() => {
    connect()
  }, [connect])

  // 슬라이드 선택 시 서버에 알림
  useEffect(() => {
    if (slideStatus === 'ready' && slideId && isConnected) {
      send({ type: 'slide_select', slide_id: slideId })
      console.log('[Lecturer] 슬라이드 선택:', slideId)
    }
  }, [slideStatus, slideId, isConnected, send])

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

  // 화면 공유 토글
  const toggleScreenShare = async () => {
    if (isScreenSharing) {
      stopScreenCapture()
      setScreenSharing(false)
    } else {
      await startScreenCapture()
      setScreenSharing(true)
    }
  }

  // 화면 공유 미리보기 업데이트
  useEffect(() => {
    const video = previewRef.current
    if (isSharing && video) {
      const stream = getPreviewStream()
      if (stream) {
        video.srcObject = stream
        // 탭 전환 후에도 재생 보장
        video.play().catch(() => {})
      }
    } else if (video) {
      video.srcObject = null
    }
  }, [isSharing, getPreviewStream])

  // 탭이 다시 보일 때 비디오 재생
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (!document.hidden && isSharing && previewRef.current) {
        previewRef.current.play().catch(() => {})
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [isSharing])

  // 강의 종료
  const handleEnd = () => {
    stopAudioCapture()
    stopScreenCapture()
    navigate('/')
  }

  return (
    <div className="min-h-screen bg-slate-100 p-6">
      {/* 헤더 */}
      <header className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-bold text-slate-800">강의자 모드</h1>
          <ConnectionStatus isConnected={isConnected} />
        </div>

        <button
          onClick={handleEnd}
          className="px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg transition-colors"
        >
          강의 종료
        </button>
      </header>

      <div className="grid grid-cols-3 gap-6">
        {/* 메인 영역 - 화면 미리보기 */}
        <div className="col-span-2 space-y-4">
          {/* 화면 공유 미리보기 */}
          <div className="bg-slate-900 rounded-xl overflow-hidden aspect-video flex items-center justify-center">
            {isScreenSharing ? (
              <video
                ref={previewRef}
                autoPlay
                muted
                className="w-full h-full object-contain"
              />
            ) : (
              <div className="text-slate-500 text-center">
                <svg className="w-16 h-16 mx-auto mb-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
                <p>화면 공유를 시작하세요</p>
              </div>
            )}
          </div>

          {/* 실시간 자막 */}
          <div className="bg-white rounded-xl p-4 shadow-sm">
            <h3 className="text-sm font-medium text-slate-500 mb-3">실시간 자막</h3>
            <SubtitleDisplay subtitles={subtitles} maxItems={3} />
          </div>
        </div>

        {/* 사이드바 - 컨트롤 */}
        <div className="space-y-4">
          {/* 슬라이드 업로드 */}
          <SlideUpload />

          {/* 컨트롤 버튼 */}
          <div className="bg-white rounded-xl p-4 shadow-sm space-y-3">
            <h3 className="text-sm font-medium text-slate-500 mb-3">강의 컨트롤</h3>

            {/* 마이크 */}
            <button
              onClick={toggleMic}
              disabled={!isConnected}
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
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                  </svg>
                  마이크 OFF
                </>
              )}
            </button>

            {/* 화면 공유 */}
            <button
              onClick={toggleScreenShare}
              disabled={!isConnected}
              className={`w-full py-3 px-4 rounded-lg font-medium transition-colors flex items-center justify-center gap-2 ${
                isScreenSharing
                  ? 'bg-blue-500 hover:bg-blue-600 text-white'
                  : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
              } disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {isScreenSharing ? (
                <>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                  </svg>
                  화면 공유 중
                </>
              ) : (
                <>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                  </svg>
                  화면 공유
                </>
              )}
            </button>
          </div>

          {/* 상태 표시 */}
          <div className="bg-white rounded-xl p-4 shadow-sm">
            <h3 className="text-sm font-medium text-slate-500 mb-3">상태</h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-500">슬라이드</span>
                <span className={slideStatus === 'ready' ? 'text-green-600' : 'text-slate-400'}>
                  {slideStatus === 'none' && '업로드 필요'}
                  {slideStatus === 'uploading' && '업로드 중...'}
                  {slideStatus === 'processing' && '처리 중...'}
                  {slideStatus === 'ready' && '준비됨'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">마이크</span>
                <span className={isMicOn ? 'text-green-600' : 'text-slate-400'}>
                  {isMicOn ? 'ON' : 'OFF'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">화면 공유</span>
                <span className={isScreenSharing ? 'text-green-600' : 'text-slate-400'}>
                  {isScreenSharing ? 'ON' : 'OFF'}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Lecturer
