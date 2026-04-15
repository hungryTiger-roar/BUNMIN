import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

function Loading() {
  const navigate = useNavigate()
  const [logs, setLogs] = useState<string[]>(['백엔드 시작 중... (최초 실행 시 모델 다운로드로 10~20분 소요)'])
  const [failed, setFailed] = useState(false)
  const logsEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  useEffect(() => {
    // Electron 환경
    if (window.electron) {
      window.electron.onBackendLog((log: string) => {
        const lines = log.split('\n').filter((l) => l.trim())
        setLogs((prev) => [...prev, ...lines].slice(-50))
      })

      window.electron.onBackendReady((ready: boolean) => {
        if (ready) {
          navigate('/')
        } else {
          setFailed(true)
        }
      })

      // listener 등록 완료 후 main process에 준비 신호 전송 → 버퍼 flush
      window.electron.notifyReady()
      return
    }

    // 웹 환경 (개발 시) - /health 직접 폴링
    let attempts = 0
    const maxAttempts = 30

    const poll = async () => {
      try {
        const res = await fetch('/health')
        if (res.ok) {
          navigate('/')
          return
        }
      } catch {
        // 아직 준비 안 됨
      }

      attempts++
      if (attempts < maxAttempts) {
        setTimeout(poll, 2000)
      } else {
        setFailed(true)
      }
    }

    setTimeout(poll, 1000)
  }, [navigate])

  return (
    <div className="min-h-screen bg-slate-900 flex flex-col items-center justify-center text-white p-8">
      <div className="w-full max-w-md">
        {/* 로고/타이틀 */}
        <div className="text-center mb-10">
          <h1 className="text-3xl font-bold mb-2">Aunion AI</h1>
          <p className="text-slate-400 text-sm">실시간 강의 번역 서비스</p>
        </div>

        {!failed ? (
          <>
            {/* 스피너 */}
            <div className="flex items-center justify-center mb-6">
              <svg
                className="animate-spin w-10 h-10 text-blue-400"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            </div>

            {/* 상태 메시지 */}
            <p className="text-center text-slate-300 mb-4">
              AI 모델을 불러오는 중입니다...
            </p>
            <p className="text-center text-slate-500 text-xs mb-6">
              최초 실행 시 모델 다운로드로 10~20분 소요될 수 있습니다
            </p>

            {/* 로그 */}
            <div className="bg-slate-800 rounded-lg p-4 h-40 overflow-y-auto text-xs font-mono text-slate-400">
              {logs.map((log, i) => (
                <div key={i} className="leading-5">{log}</div>
              ))}
              <div ref={logsEndRef} />
            </div>
          </>
        ) : (
          <div className="text-center">
            <div className="w-16 h-16 mx-auto mb-4 bg-red-500/20 rounded-full flex items-center justify-center">
              <svg className="w-8 h-8 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <p className="text-red-400 font-medium mb-2">백엔드 시작 실패</p>
            <p className="text-slate-500 text-sm">앱을 재시작해 주세요</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default Loading
