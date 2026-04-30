/**
 * Install — Aunion AI 첫 실행 시 VLM 모델 다운로드 마법사
 *
 * 3단계 흐름:
 *   1. intro       — 다운로드 안내 + "다운로드 시작"
 *   2. downloading — 진행률/속도/ETA + 검증 단계
 *   3. complete    — 완료 안내 + "확인" → /lecturer
 *
 * 디자인: 모던 인스톨러 톤. 흰 배경 + 미세한 그림자 + indigo 강조.
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { API_BASE } from '@/lib/api'

type Phase = 'intro' | 'downloading' | 'complete' | 'error'

interface DownloadInfo {
  phase: 'downloading' | 'finalizing' | 'verifying'
  current_bytes: number
  total_bytes: number
  speed_bps: number
}

interface BackendHealth {
  status: 'starting' | 'wait_user_action' | 'loading' | 'ready' | 'ok' | 'error'
  message?: string
  progress?: number
  download?: DownloadInfo | null
}

// ─── 포맷 유틸 ───────────────────────────────────────────────────────────────
function formatBytes(bytes: number): string {
  if (bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  const n = bytes / Math.pow(1024, i)
  const decimals = i >= 3 ? 2 : i >= 2 ? 1 : 0
  return `${n.toFixed(decimals)} ${units[i]}`
}

function formatSpeed(bps: number): string {
  if (bps <= 0) return '— '
  return `${formatBytes(bps)}/s`
}

function formatEta(remainingBytes: number, bps: number): string {
  if (bps <= 0 || remainingBytes <= 0) return '계산 중'
  const sec = Math.round(remainingBytes / bps)
  if (sec < 60) return `약 ${sec}초 남음`
  const min = Math.round(sec / 60)
  if (min < 60) return `약 ${min}분 남음`
  const hr = Math.floor(min / 60)
  const remMin = min % 60
  return `약 ${hr}시간 ${remMin}분 남음`
}

// ─── 메인 ───────────────────────────────────────────────────────────────────
function Install() {
  const navigate = useNavigate()
  const [phase, setPhase] = useState<Phase>('intro')
  const [download, setDownload] = useState<DownloadInfo | null>(null)
  const [errorMsg, setErrorMsg] = useState<string>('')
  const [starting, setStarting] = useState(false)
  const pollTimerRef = useRef<number | null>(null)

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/health`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data: BackendHealth = await res.json()
        if (cancelled) return
        if (data.download) setDownload(data.download)

        switch (data.status) {
          case 'wait_user_action':
            setPhase('intro')
            break
          case 'loading':
          case 'starting':
            if (data.download) setPhase('downloading')
            break
          case 'ready':
          case 'ok':
            setPhase('complete')
            break
          case 'error':
            setErrorMsg(data.message || '알 수 없는 오류가 발생했습니다.')
            setPhase('error')
            return
        }
      } catch {
        // 다음 폴 재시도
      }
      if (!cancelled) pollTimerRef.current = window.setTimeout(poll, 1000)
    }
    poll()
    return () => {
      cancelled = true
      if (pollTimerRef.current !== null) window.clearTimeout(pollTimerRef.current)
    }
  }, [])

  const handleStartDownload = async () => {
    if (starting) return
    setStarting(true)
    try {
      await fetch(`${API_BASE}/api/install/start-download`, { method: 'POST' })
      setPhase('downloading')
    } catch (e) {
      setErrorMsg(`다운로드 시작 요청 실패: ${e}`)
      setPhase('error')
    } finally {
      setStarting(false)
    }
  }

  const handleConfirm = () => navigate('/lecturer')

  const handleCancel = () => {
    if (window.electron?.quitApp) window.electron.quitApp()
    else window.close()
  }

  return (
    <div className="min-h-screen bg-stone-100 flex items-center justify-center p-6 antialiased">
      <Card>
        {phase === 'intro' && (
          <IntroPanel onStart={handleStartDownload} starting={starting} />
        )}
        {phase === 'downloading' && (
          <DownloadPanel download={download} onCancel={handleCancel} />
        )}
        {phase === 'complete' && <CompletePanel onConfirm={handleConfirm} />}
        {phase === 'error' && <ErrorPanel message={errorMsg} onClose={handleCancel} />}
      </Card>
    </div>
  )
}

// ─── 카드 셸 ────────────────────────────────────────────────────────────────
function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="w-full max-w-2xl">
      <div className="bg-white rounded-2xl shadow-[0_24px_48px_-12px_rgba(0,0,0,0.12)] border border-stone-200/80 overflow-hidden">
        {children}
      </div>
    </div>
  )
}

// ─── 헤더 (모든 단계 공통) ──────────────────────────────────────────────────
function StepHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="px-12 pt-12 pb-6 border-b border-stone-100">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-1.5 h-1.5 rounded-full bg-indigo-500" />
        <span className="text-[11px] font-semibold tracking-[0.18em] uppercase text-stone-500">
          Aunion AI · 초기 설정
        </span>
      </div>
      <h1 className="text-[26px] font-semibold text-stone-900 leading-tight tracking-tight">
        {title}
      </h1>
      <p className="mt-2.5 text-sm text-stone-500 leading-relaxed">
        {description}
      </p>
    </div>
  )
}

// ─── 푸터 (액션 영역) ───────────────────────────────────────────────────────
function StepFooter({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-12 py-5 bg-stone-50/60 border-t border-stone-100 flex justify-end items-center gap-3">
      {children}
    </div>
  )
}

// ─── Step 1: Intro ──────────────────────────────────────────────────────────
function IntroPanel({ onStart, starting }: { onStart: () => void; starting: boolean }) {
  return (
    <>
      <StepHeader
        title="AI 모델 설치"
        description="Aunion AI를 처음 실행합니다. 강의 자료 번역 기능을 사용하기 위해 AI 모델을 한 번 다운로드해야 합니다."
      />

      <div className="px-12 py-8">
        {/* 모델 카드 */}
        <div className="border border-stone-200 rounded-xl p-6 bg-stone-50/40">
          <div className="flex items-start gap-5">
            <div className="w-11 h-11 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center shrink-0">
              <svg className="w-5 h-5 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline justify-between gap-3 mb-1.5">
                <h3 className="text-[15px] font-semibold text-stone-900">슬라이드 번역 모델</h3>
                <span className="text-sm text-stone-500 font-mono tabular-nums shrink-0">약 16 GB</span>
              </div>
              <p className="text-[13.5px] text-stone-600 leading-relaxed">
                강의 자료(PDF)의 한국어 텍스트를 영어로 자동 번역합니다. 슬라이드 내 그림과 표에 포함된 글자도 인식하여 번역에 반영됩니다.
              </p>
            </div>
          </div>
        </div>

        {/* 메타 정보 */}
        <div className="grid grid-cols-3 gap-3 mt-6">
          <Meta icon={<IconClock />} label="소요 시간" value="30~60분" />
          <Meta icon={<IconNetwork />} label="인터넷 연결" value="필요" />
          <Meta icon={<IconLightning />} label="다음 실행" value="즉시 시작" />
        </div>

        <p className="mt-6 text-xs text-stone-400 leading-relaxed">
          다운로드는 최초 1회만 진행되며, 이후 실행에서는 이 화면이 표시되지 않습니다. 다운로드된 모델은 사용자의 로컬 디스크에 저장됩니다.
        </p>
      </div>

      <StepFooter>
        <button
          type="button"
          onClick={onStart}
          disabled={starting}
          className="px-7 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 disabled:bg-stone-300 disabled:cursor-not-allowed transition-colors text-white text-sm font-medium shadow-sm"
        >
          {starting ? '시작 중...' : '다운로드 시작'}
        </button>
      </StepFooter>
    </>
  )
}

// ─── Step 2: Downloading ────────────────────────────────────────────────────
function DownloadPanel({
  download,
  onCancel,
}: {
  download: DownloadInfo | null
  onCancel: () => void
}) {
  const phaseKind = download?.phase ?? 'downloading'
  const isFinalizing = phaseKind === 'finalizing'
  const isVerifying = phaseKind === 'verifying'
  const isPostDownload = isFinalizing || isVerifying  // 다운로드 100% 이후 단계

  const total = download?.total_bytes ?? 0
  const current = download?.current_bytes ?? 0
  const speed = download?.speed_bps ?? 0
  const dlPct = total > 0 ? Math.min(100, (current / total) * 100) : 0
  const remaining = Math.max(0, total - current)

  // 단계별 헤더 메시지
  const headerTitle = isVerifying
    ? '모델을 검증하고 있습니다'
    : isFinalizing
    ? '다운로드를 마무리하고 있습니다'
    : '잠시만 기다려 주세요'

  const headerDesc = isVerifying
    ? '다운로드된 파일이 정상적으로 저장되었는지 확인하고 있습니다.'
    : isFinalizing
    ? '받은 파일을 정리하는 중입니다. 사용자 PC 환경에 따라 수 분 정도 걸릴 수 있습니다.'
    : '슬라이드 번역에 필요한 AI 모델을 다운로드하는 중입니다.'

  // 보조 바 라벨
  const subLabel = isVerifying ? '검증 진행 중' : isFinalizing ? '정리 진행 중' : '대기 중'

  return (
    <>
      <StepHeader title={headerTitle} description={headerDesc} />

      <div className="px-12 py-8">
        {/* 다운로드 바 */}
        <div className="mb-7">
          <div className="flex items-baseline justify-between mb-2.5">
            <span className="text-[13px] font-medium text-stone-700">다운로드</span>
            <span className="text-xs text-stone-500 font-mono tabular-nums">
              {total > 0 ? (
                <>
                  <span className="text-stone-700">{formatBytes(Math.min(current, total))}</span>
                  <span className="mx-1.5 text-stone-300">/</span>
                  <span>{formatBytes(total)}</span>
                  {!isPostDownload && speed > 0 && (
                    <span className="ml-3 text-stone-400">{formatSpeed(speed)}</span>
                  )}
                </>
              ) : (
                <span className="text-stone-400">준비 중</span>
              )}
            </span>
          </div>
          <ProgressBar
            percent={isPostDownload ? 100 : dlPct}
            done={isPostDownload || dlPct >= 100}
            color="indigo"
          />
          {!isPostDownload && (
            <div className="mt-2 flex justify-between text-[11px] text-stone-400 font-mono tabular-nums">
              <span>{dlPct >= 1 ? `${dlPct.toFixed(1)}%` : '연결 중...'}</span>
              {speed > 0 && total > 0 && (
                <span>{formatEta(remaining, speed)}</span>
              )}
            </div>
          )}
          {isPostDownload && (
            <div className="mt-2 text-[11px] text-emerald-600 font-medium">
              다운로드 완료 ({formatBytes(total)})
            </div>
          )}
        </div>

        {/* 보조 바 — 정리/검증 진행 표시 */}
        <div>
          <div className="flex items-baseline justify-between mb-2.5">
            <span className="text-[13px] font-medium text-stone-700">
              {isVerifying ? '검증' : '준비'}
            </span>
            <span className="text-xs text-stone-400">{subLabel}</span>
          </div>
          <ProgressBar
            percent={isPostDownload ? 60 : 0}
            done={false}
            color="indigo"
            indeterminate={isPostDownload}
          />
          {isFinalizing && (
            <p className="mt-3 text-[11px] text-stone-400 leading-relaxed">
              파일을 사용 가능한 위치로 옮기는 중입니다. 디스크 속도에 따라 시간이 다소 걸릴 수 있습니다.
            </p>
          )}
        </div>
      </div>

      <StepFooter>
        <button
          type="button"
          onClick={onCancel}
          className="px-5 py-2 rounded-lg border border-stone-300 hover:bg-stone-100 text-stone-600 text-sm transition-colors"
        >
          취소
        </button>
      </StepFooter>
    </>
  )
}

// ─── Step 3: Complete ───────────────────────────────────────────────────────
function CompletePanel({ onConfirm }: { onConfirm: () => void }) {
  return (
    <>
      <div className="px-12 pt-14 pb-10 text-center">
        <div className="mx-auto w-16 h-16 rounded-full bg-emerald-50 border border-emerald-100 flex items-center justify-center mb-6">
          <svg className="w-8 h-8 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 className="text-[26px] font-semibold text-stone-900 mb-3 tracking-tight">설치 완료</h1>
        <p className="text-stone-600 mb-1">AI 모델 다운로드가 완료되었습니다.</p>
        <p className="text-sm text-stone-400">
          다음 실행부터는 이 화면이 표시되지 않으며, 즉시 강의를 시작할 수 있습니다.
        </p>
      </div>

      <StepFooter>
        <button
          type="button"
          onClick={onConfirm}
          className="px-7 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800 transition-colors text-white text-sm font-medium shadow-sm"
        >
          확인
        </button>
      </StepFooter>
    </>
  )
}

// ─── Error ──────────────────────────────────────────────────────────────────
function ErrorPanel({ message, onClose }: { message: string; onClose: () => void }) {
  return (
    <>
      <div className="px-12 pt-12 pb-6 border-b border-stone-100">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-10 h-10 rounded-full bg-red-50 border border-red-100 flex items-center justify-center">
            <svg className="w-5 h-5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <h1 className="text-xl font-semibold text-stone-900">설치 실패</h1>
        </div>
      </div>
      <div className="px-12 py-7">
        <p className="text-sm text-stone-600 mb-5 leading-relaxed">{message}</p>
        <p className="text-xs text-stone-400 leading-relaxed">
          인터넷 연결 상태를 확인한 뒤 앱을 재시작해 주세요. 문제가 계속되면{' '}
          <code className="px-1.5 py-0.5 bg-stone-100 rounded text-stone-600 font-mono text-[10.5px]">
            %LOCALAPPDATA%\Aunion AI\error_log.txt
          </code>{' '}
          파일을 첨부해 문의해 주세요.
        </p>
      </div>
      <StepFooter>
        <button
          type="button"
          onClick={onClose}
          className="px-5 py-2 rounded-lg border border-stone-300 hover:bg-stone-100 text-stone-600 text-sm transition-colors"
        >
          앱 종료
        </button>
      </StepFooter>
    </>
  )
}

// ─── Atoms ──────────────────────────────────────────────────────────────────
function Meta({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2.5 py-2 px-3 bg-white border border-stone-200/60 rounded-lg">
      <span className="text-stone-400 shrink-0">{icon}</span>
      <div className="min-w-0">
        <div className="text-[10.5px] uppercase tracking-wider text-stone-400 font-medium">{label}</div>
        <div className="text-[13px] text-stone-700 font-medium">{value}</div>
      </div>
    </div>
  )
}

function ProgressBar({
  percent,
  done,
  color,
  indeterminate = false,
}: {
  percent: number
  done: boolean
  color: 'indigo'
  indeterminate?: boolean
}) {
  const fillColor = done ? 'bg-emerald-500' : color === 'indigo' ? 'bg-indigo-600' : 'bg-stone-400'

  if (indeterminate) {
    return (
      <div className="w-full h-1.5 rounded-full bg-stone-100 overflow-hidden relative">
        <div
          className={`absolute inset-y-0 ${fillColor} rounded-full`}
          style={{ width: '35%', animation: 'aunionProgressSlide 1.4s ease-in-out infinite' }}
        />
        <style>{`
          @keyframes aunionProgressSlide {
            0%   { left: -35%; }
            100% { left: 100%; }
          }
        `}</style>
      </div>
    )
  }

  return (
    <div className="w-full h-1.5 rounded-full bg-stone-100 overflow-hidden">
      <div
        className={`h-full ${fillColor} rounded-full transition-all duration-500 ease-out`}
        style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
      />
    </div>
  )
}

// ─── Icons ──────────────────────────────────────────────────────────────────
function IconClock() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
        d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  )
}

function IconNetwork() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
        d="M8.288 15.038a5.25 5.25 0 017.424 0M5.106 11.856c3.807-3.808 9.98-3.808 13.788 0M1.924 8.674c5.565-5.565 14.587-5.565 20.152 0M12.53 18.22l-.53.53-.53-.53a.75.75 0 011.06 0z" />
    </svg>
  )
}

function IconLightning() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
        d="M13 10V3L4 14h7v7l9-11h-7z" />
    </svg>
  )
}

export default Install
