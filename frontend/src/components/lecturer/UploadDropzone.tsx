import { useCallback, useEffect, useRef, useState } from 'react'
import { useLectureStore } from '@/stores/lectureStore'
import { API_BASE } from '@/lib/api'

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
  return `약 ${Math.ceil(seconds / 60)}분 남음`
}

interface Props {
  /** 업로드/처리 완료 시 부모(SlideUpload)가 라이브러리를 새로고침 */
  onUploadComplete?: () => void
}

export default function UploadDropzone({ onUploadComplete }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const cancelledRef = useRef(false)
  const [stage, setStage] = useState<Stage>('pending')
  const [stageCurrent, setStageCurrent] = useState(0)
  const [stageTotal, setStageTotal] = useState(0)
  const [etaAnchor, setEtaAnchor] = useState<{ value: number; at: number } | null>(null)
  const [displayEta, setDisplayEta] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [etaReachedZero, setEtaReachedZero] = useState(false)

  const slideStatus = useLectureStore((s) => s.slideStatus)
  const setSlideId = useLectureStore((s) => s.setSlideId)
  const setSlideStatus = useLectureStore((s) => s.setSlideStatus)

  useEffect(() => {
    if (displayEta !== null && displayEta <= 1 && slideStatus === 'processing') {
      setEtaReachedZero(true)
    }
  }, [displayEta, slideStatus])

  useEffect(() => {
    if (slideStatus === 'none') {
      setEtaReachedZero(false)
      setStage('pending')
      setStageCurrent(0)
      setStageTotal(0)
      setEtaAnchor(null)
      setDisplayEta(null)
      setError(null)
    }
  }, [slideStatus])

  // displayEta 1초 카운트다운
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
    if (file.type !== 'application/pdf') {
      setError('PDF 파일만 업로드 가능합니다.')
      return
    }
    if (file.size > 200 * 1024 * 1024) {
      setError('파일 크기는 200MB 이하여야 합니다.')
      return
    }

    setError(null)
    setSlideStatus('uploading')
    cancelledRef.current = false

    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await fetch(`${API_BASE}/slides/upload`, {
        method: 'POST',
        body: formData,
        signal: controller.signal,
      })
      abortControllerRef.current = null

      if (!response.ok) {
        throw new Error('업로드에 실패했습니다.')
      }

      const data = await response.json()
      setSlideId(data.slide_id)
      setSlideStatus('processing')
      pollStatus(data.slide_id)
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      console.error('[UploadDropzone] 에러:', err)
      setError('업로드에 실패했습니다. 다시 시도해주세요.')
      setSlideStatus('none')
    }
  }, [setSlideId, setSlideStatus])

  const pollStatus = async (slideId: string) => {
    const checkStatus = async () => {
      if (cancelledRef.current) return
      try {
        const response = await fetch(`${API_BASE}/slides/status/${slideId}`)
        const data = await response.json()

        if (data.status === 'completed') {
          setStage('completed')
          setEtaAnchor(null)
          setDisplayEta(0)
          setSlideId(null)
          setSlideStatus('none')
          onUploadComplete?.()
          return
        }

        if (data.status === 'failed') {
          setStage('failed')
          setError('강의자료 처리에 실패했습니다.')
          setSlideStatus('none')
          return
        }

        const nextStage = (data.stage ?? 'pending') as Stage
        const current = data.stage_current ?? 0
        const total = data.stage_total ?? 0
        setStage(nextStage)
        setStageCurrent(current)
        setStageTotal(total)

        const eta = data.eta_seconds
        if (typeof eta === 'number') {
          setEtaAnchor({ value: eta, at: Date.now() })
        } else {
          setEtaAnchor(null)
        }

        if (!cancelledRef.current) setTimeout(checkStatus, 2000)
      } catch (err) {
        if (!cancelledRef.current) console.error('[UploadDropzone] 상태 확인 실패:', err)
      }
    }

    checkStatus()
  }

  const handleCancel = useCallback(() => {
    cancelledRef.current = true
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    setSlideStatus('none')
  }, [setSlideStatus])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file) handleFileSelect(file)
  }, [handleFileSelect])

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
  }

  const handleClick = () => {
    inputRef.current?.click()
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) handleFileSelect(file)
  }

  const showAILoading = slideStatus === 'processing' && etaReachedZero

  return (
    <div className="text-onSurface min-h-[140px]">
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

          <button
            type="button"
            onClick={handleCancel}
            className="mt-4 w-full py-2 text-sm text-error border border-error/30 rounded-lg hover:bg-error/10 transition-colors"
          >
            업로드 중단
          </button>
        </div>
      ) : null}

      {error && (
        <p className="text-sm text-error mt-2 text-center">{error}</p>
      )}
    </div>
  )
}
