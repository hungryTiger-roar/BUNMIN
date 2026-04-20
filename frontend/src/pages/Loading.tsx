import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { API_BASE } from '@/lib/api'

const MODEL_KEYS = ['asr', 'nmt', 'tts', 'ocr'] as const
type ModelKey = typeof MODEL_KEYS[number]

interface ModelEntry {
  status: 'pending' | 'loading' | 'done' | 'error'
  progress: number
  label: string
  desc: string
}

const DEFAULT_MODELS: Record<ModelKey, ModelEntry> = {
  asr: { status: 'pending', progress: 0, label: 'ASR (음성인식)', desc: import.meta.env.VITE_ASR_MODEL || 'ASR' },
  nmt: { status: 'pending', progress: 0, label: 'NMT (번역)', desc: import.meta.env.VITE_NMT_MODEL || 'NMT' },
  tts: { status: 'pending', progress: 0, label: 'TTS (음성합성)', desc: import.meta.env.VITE_TTS_MODEL || 'TTS' },
  ocr: { status: 'pending', progress: 0, label: 'OCR (문자인식)', desc: import.meta.env.VITE_OCR_MODEL || 'OCR' },
}

function StatusIcon({ status }: { status: ModelEntry['status'] }) {
  if (status === 'done') {
    return (
      <svg className="w-5 h-5 text-emerald-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
      </svg>
    )
  }
  if (status === 'loading') {
    return (
      <svg className="w-5 h-5 text-blue-400 animate-spin shrink-0" fill="none" viewBox="0 0 24 24">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
      </svg>
    )
  }
  if (status === 'error') {
    return (
      <svg className="w-5 h-5 text-red-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
      </svg>
    )
  }
  // pending
  return <div className="w-5 h-5 rounded-full border-2 border-slate-600 shrink-0" />
}

function ModelCard({ entry }: { entry: ModelEntry }) {
  const isDone = entry.status === 'done'
  const isActive = entry.status === 'loading'

  return (
    <div className={`rounded-lg p-3 border transition-colors duration-300 ${
      isDone
        ? 'bg-emerald-900/20 border-emerald-700/40'
        : isActive
        ? 'bg-blue-900/20 border-blue-700/40'
        : 'bg-slate-800/50 border-slate-700/40'
    }`}>
      <div className="flex items-center gap-2 mb-2">
        <StatusIcon status={entry.status} />
        <div className="flex-1 min-w-0">
          <p className={`text-sm font-medium leading-none ${
            isDone ? 'text-emerald-300' : isActive ? 'text-white' : 'text-slate-500'
          }`}>
            {entry.label}
          </p>
          <p className="text-xs text-slate-500 mt-0.5">{entry.desc}</p>
        </div>
        <span className={`text-xs font-mono tabular-nums ${
          isDone ? 'text-emerald-400' : isActive ? 'text-blue-300' : 'text-slate-600'
        }`}>
          {entry.progress}%
        </span>
      </div>

      {/* 개별 progress bar */}
      <div className="w-full bg-slate-700/60 rounded-full h-1.5 overflow-hidden">
        {isActive ? (
          // 다운로드 진행률이 0%면 indeterminate 애니메이션
          entry.progress > 0 ? (
            <div
              className="bg-blue-500 h-1.5 rounded-full transition-all duration-300"
              style={{ width: `${entry.progress}%` }}
            />
          ) : (
            <div className="h-1.5 rounded-full bg-blue-500 animate-[shimmer_1.5s_ease-in-out_infinite] w-1/3" />
          )
        ) : (
          <div
            className={`h-1.5 rounded-full transition-all duration-500 ${
              isDone ? 'bg-emerald-500' : 'bg-slate-600'
            }`}
            style={{ width: `${entry.progress}%` }}
          />
        )}
      </div>
    </div>
  )
}

function Loading() {
  const navigate = useNavigate()
  const [logs, setLogs] = useState<string[]>(['백엔드 시작 중... (최초 실행 시 모델 다운로드로 10~20분 소요)'])
  const [failed, setFailed] = useState(false)
  const [overallProgress, setOverallProgress] = useState(0)
  const [models, setModels] = useState<Record<ModelKey, ModelEntry>>(DEFAULT_MODELS)
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

      window.electron.onBackendProgress((p: number) => {
        setOverallProgress(p)
      })

      window.electron.onBackendModelStatus((m: ModelMap) => {
        setModels((prev) => ({ ...prev, ...m }))
      })

      window.electron.onBackendReady((ready: boolean) => {
        if (ready) {
          navigate('/')
        } else {
          setFailed(true)
        }
      })

      return
    }

    // 웹 환경 (개발 시) - /health 직접 폴링
    let attempts = 0
    const maxAttempts = 600

    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/health`)
        if (res.ok) {
          const json = await res.json()
          if (typeof json.progress === 'number') {
            setOverallProgress(json.progress)
          }
          if (json.models) {
            setModels((prev) => ({ ...prev, ...json.models }))
          }
          if (json.message) {
            setLogs((prev) => {
              const last = prev[prev.length - 1]
              return last === json.message ? prev : [...prev, json.message].slice(-50)
            })
          }
          if (json.status === 'ok') {
            navigate('/')
            return
          }
          if (json.status === 'error') {
            setFailed(true)
            return
          }
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
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold mb-2">Aunion AI</h1>
          <p className="text-slate-400 text-sm">실시간 강의 번역 서비스</p>
        </div>

        {!failed ? (
          <>
            {/* 스피너 + 전체 진행률 */}
            <div className="flex items-center gap-3 mb-5">
              <svg className="animate-spin w-5 h-5 text-blue-400 shrink-0" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              <div className="flex-1">
                <div className="flex justify-between text-xs text-slate-400 mb-1">
                  <span>AI 모델 로딩 중</span>
                  <span className="font-mono tabular-nums">{overallProgress}%</span>
                </div>
                <div className="w-full bg-slate-700 rounded-full h-2 overflow-hidden">
                  <div
                    className="bg-blue-500 h-2 rounded-full transition-all duration-500"
                    style={{ width: `${overallProgress}%` }}
                  />
                </div>
              </div>
            </div>

            {/* 모델별 카드 */}
            <div className="space-y-2 mb-4">
              {MODEL_KEYS.map((key) => (
                <ModelCard key={key} entry={models[key]} />
              ))}
            </div>

            <p className="text-center text-slate-600 text-xs mb-3">
              최초 실행 시 모델 다운로드로 최대 60분 소요될 수 있습니다
            </p>

            {/* 로그 */}
            <div className="bg-slate-800 rounded-lg p-3 h-28 overflow-y-auto text-xs font-mono text-slate-500">
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
            <p className="text-slate-500 text-sm mb-3">앱을 재시작해 주세요</p>
            <div className="bg-slate-800 rounded-lg p-3 text-left text-xs font-mono">
              <p className="text-slate-400 mb-1">오류 로그 파일:</p>
              <p className="text-yellow-400 break-all">
                %LOCALAPPDATA%\Aunion AI\error_log.txt
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default Loading
