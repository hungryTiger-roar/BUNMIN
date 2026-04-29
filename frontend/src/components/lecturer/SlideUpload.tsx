import { useCallback, useEffect, useRef, useState } from 'react'
import { useLectureStore } from '@/stores/lectureStore'
import { API_BASE, switchToRealtimeMode, switchToSlideMode } from '@/lib/api'

type Stage = 'pending' | 'ocr' | 'translate' | 'bundling' | 'completed' | 'failed'

const STAGE_LABELS: Record<Stage, string> = {
  pending: '준비 중',
  ocr: 'OCR',
  translate: '번역',
  bundling: 'PDF 생성',
  completed: '완료',
  failed: '실패',
}

function formatEta(seconds: number): string {
  if (seconds < 1) return ''
  if (seconds < 60) return `약 ${Math.ceil(seconds)}초 남음`
  const min = Math.floor(seconds / 60)
  const sec = Math.ceil(seconds % 60)
  if (sec === 0 || sec === 60) return `약 ${sec === 60 ? min + 1 : min}분 남음`
  return `약 ${min}분 ${sec}초 남음`
}

function SlideUpload() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [stage, setStage] = useState<Stage>('pending')
  const [stageCurrent, setStageCurrent] = useState(0)
  const [stageTotal, setStageTotal] = useState(0)
  // ETA 앵커: 백엔드 폴링 응답 받은 시점의 (남은 초, 받은 시각). 클라이언트에서 1초씩 깎음
  const [etaAnchor, setEtaAnchor] = useState<{ value: number; at: number } | null>(null)
  const [displayEta, setDisplayEta] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const { slideStatus, setSlideId, setSlideStatus, modelMode, setModelMode } = useLectureStore()

  // ETA가 0에 도달한 적이 있는지 — 도달 후엔 카운트다운 대신 'AI 번역중...' 표시
  // (백엔드 baseline과 실제 속도가 다를 때 ETA가 0에 갔다가 다음 단계 시작 시 다시 점프하는 혼란 방지)
  const [etaReachedZero, setEtaReachedZero] = useState(false)

  useEffect(() => {
    if (displayEta !== null && displayEta <= 1 && slideStatus === 'processing') {
      setEtaReachedZero(true)
    }
  }, [displayEta, slideStatus])

  useEffect(() => {
    if (slideStatus === 'none') {
      setEtaReachedZero(false)
    }
  }, [slideStatus])

  // 1초마다 displayEta를 깎아냄 (다음 폴링까지의 부드러운 카운트다운)
  useEffect(() => {
    if (etaAnchor === null) {
      setDisplayEta(null)
      return
    }
    const tick = () => {
      const elapsed = (Date.now() - etaAnchor.at) / 1000
      setDisplayEta(Math.max(0, etaAnchor.value - elapsed))
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [etaAnchor])

  const handleFileSelect = useCallback(async (file: File) => {
    // 파일 타입 검증
    if (file.type !== 'application/pdf') {
      setError('PDF 파일만 업로드 가능합니다.')
      return
    }

    // 파일 크기 검증 (200MB)
    if (file.size > 200 * 1024 * 1024) {
      setError('파일 크기는 200MB 이하여야 합니다.')
      return
    }

    setError(null)
    setSlideStatus('uploading')

    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await fetch(`${API_BASE}/slides/upload`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        throw new Error('업로드에 실패했습니다.')
      }

      const data = await response.json()
      setSlideId(data.slide_id)
      setSlideStatus('processing')

      // 처리 상태 폴링
      pollStatus(data.slide_id)
    } catch (err) {
      console.error('[SlideUpload] 에러:', err)
      setError('업로드에 실패했습니다. 다시 시도해주세요.')
      setSlideStatus('none')
    }
  }, [setSlideId, setSlideStatus])

  // 처리 상태 확인
  const pollStatus = async (slideId: string) => {
    const checkStatus = async () => {
      try {
        const response = await fetch(`${API_BASE}/slides/status/${slideId}`)
        const data = await response.json()

        if (data.status === 'completed') {
          setStage('completed')
          setEtaAnchor(null)
          setDisplayEta(0)
          setSlideStatus('ready')
          // 옵션 B: 번역 완료 후 즉시 실시간 모드로 전환
          setModelMode('switching')
          try {
            await switchToRealtimeMode()
            setModelMode('realtime')
            console.log('[SlideUpload] 실시간 모드로 전환 완료')
          } catch (err) {
            console.error('[SlideUpload] 모드 전환 실패:', err)
            setModelMode('idle')
          }
          return
        }

        if (data.status === 'failed') {
          setStage('failed')
          setError('강의자료 처리에 실패했습니다.')
          setSlideStatus('none')
          return
        }

        // 단계 정보 업데이트
        const nextStage = (data.stage ?? 'pending') as Stage
        const current = data.stage_current ?? 0
        const total = data.stage_total ?? 0
        setStage(nextStage)
        setStageCurrent(current)
        setStageTotal(total)

        // ETA 앵커 갱신 — 백엔드는 페이지 완료 시점에만 갱신하고, 폴링 응답 시점에 흐른 시간만큼
        // 이미 감산해서 보내줌. 클라이언트는 그 시점부터 1초씩 깎아내림 (위 useEffect)
        const eta = data.eta_seconds
        if (typeof eta === 'number') {
          setEtaAnchor({ value: eta, at: Date.now() })
        } else {
          setEtaAnchor(null)
        }

        setTimeout(checkStatus, 2000)
      } catch (err) {
        console.error('[SlideUpload] 상태 확인 실패:', err)
      }
    }

    checkStatus()
  }

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file) {
      handleFileSelect(file)
    }
  }, [handleFileSelect])

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
  }

  const handleClick = () => {
    inputRef.current?.click()
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      handleFileSelect(file)
    }
  }

  const showAILoading =
    (slideStatus === 'processing' && etaReachedZero) ||
    (slideStatus === 'ready' && modelMode === 'switching')

  return (
    <div className="text-onSurface">
      <input
        ref={inputRef}
        type="file"
        accept=".pdf"
        onChange={handleChange}
        className="hidden"
      />

      {slideStatus === 'none' ? (
        <div
          onClick={handleClick}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          className="border-2 border-dashed border-primaryContainer rounded-lg p-6 text-center cursor-pointer hover:border-primary hover:bg-primaryContainer/40 transition-colors"
        >
          <svg className="w-10 h-10 mx-auto text-onSurface/30 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
          </svg>
          <p className="text-sm text-onSurface/70">PDF 파일을 드래그하거나 클릭하세요</p>
          <p className="text-xs text-onSurface/50 mt-1">업로드 즉시 번역이 시작됩니다</p>
        </div>
      ) : showAILoading ? (
        <div className="flex flex-col items-center gap-3 py-8 px-2">
          <svg className="animate-spin w-12 h-12 text-primary" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
          <p className="text-base font-semibold text-onSurface">AI 번역중...</p>
          <p className="text-sm text-onSurface/60">잠시만 기다려주세요</p>
        </div>
      ) : slideStatus === 'uploading' || slideStatus === 'processing' ? (
        <div className="py-4 px-2">
          <div className="flex items-center gap-2 mb-3">
            <svg className="animate-spin w-5 h-5 text-primary flex-shrink-0" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            <p className="text-base font-medium text-onSurface">
              {slideStatus === 'uploading'
                ? '업로드 중...'
                : stage === 'bundling'
                  ? 'PDF 생성 중...'
                  : stage === 'pending'
                    ? '준비 중...'
                    : stageTotal > 0
                      ? `${STAGE_LABELS[stage]} ${stageCurrent}/${stageTotal}`
                      : `${STAGE_LABELS[stage]}...`}
            </p>
          </div>

          {/* 진행률 바 — 단계별 표시 */}
          <div className="w-full h-2 bg-primaryContainer/40 rounded-full overflow-hidden">
            {stage === 'bundling' ? (
              <div className="h-full w-full bg-primary/60 animate-pulse" />
            ) : (
              <div
                className="h-full bg-primary transition-all duration-300"
                style={{
                  width:
                    stageTotal > 0
                      ? `${Math.min(100, Math.round((stageCurrent / stageTotal) * 100))}%`
                      : '0%',
                }}
              />
            )}
          </div>

          <p className="text-sm text-onSurface/60 mt-3 text-center font-medium">
            {slideStatus === 'uploading'
              ? ''
              : displayEta !== null
                ? formatEta(displayEta)
                : '남은 시간 계산 중...'}
          </p>
        </div>
      ) : slideStatus === 'ready' ? (
        <div className="text-center py-2">
          <div className="w-10 h-10 mx-auto mb-2 bg-emerald-100 rounded-full flex items-center justify-center">
            <svg className="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <p className="text-sm text-emerald-600 font-medium">준비 완료</p>
          <button
            onClick={async () => {
              setSlideStatus('none')
              setSlideId(null)
              if (modelMode === 'realtime') {
                setModelMode('switching')
                try {
                  await switchToSlideMode()
                  setModelMode('slide')
                } catch {
                  setModelMode('idle')
                }
              }
            }}
            className="text-xs text-onSurface/50 hover:text-onSurface mt-2"
          >
            다시 업로드
          </button>
        </div>
      ) : null}

      {error && (
        <p className="text-sm text-error mt-2 text-center">{error}</p>
      )}
    </div>
  )
}

export default SlideUpload
