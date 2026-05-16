import { useCallback, useEffect, useRef, useState } from 'react'
import { useLectureStore } from '@/stores/lectureStore'
import { API_BASE } from '@/lib/api'

type Stage = 'pending' | 'ocr' | 'translate' | 'bundling' | 'completed' | 'failed'

const STAGE_LABELS: Record<Stage, string> = {
  pending: '준비 중',
  ocr: '텍스트 인식',
  translate: '번역',
  bundling: 'PDF 생성',
  completed: '완료',
  failed: '실패',
}

interface Props {
  /** 업로드/처리 완료 시 부모(SlideUpload)가 라이브러리를 새로고침 */
  onUploadComplete?: () => void
}

export default function UploadDropzone({ onUploadComplete }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const cancelledRef = useRef(false)
  const clientTokenRef = useRef<string | null>(null)
  const slideIdRef = useRef<string | null>(null)

  // 다중 파일 큐
  const fileQueueRef = useRef<File[]>([])
  const [queueTotal, setQueueTotal] = useState(0)
  const [queueProcessed, setQueueProcessed] = useState(0)
  const [currentFileName, setCurrentFileName] = useState('')

  const [stage, setStage] = useState<Stage>('pending')
  const [stageCurrent, setStageCurrent] = useState(0)
  const [stageTotal, setStageTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)

  // ETA 계산용: 단계가 바뀌는 순간을 기준점으로 elapsed/current × (total-current) 추정.
  // stage 가 바뀌면 startedAt 을 갱신하므로 이전 단계의 처리 속도가 다음 단계로 새지 않음.
  const stageStartedAtRef = useRef<number>(0)
  const startedAtStageRef = useRef<Stage | null>(null)
  // 통합 진행률/ETA: 파일 처리 시작 시각 + 페이지 수 캐시. 다중 파일 큐는 파일별로 리셋.
  const processStartedAtRef = useRef<number>(0)
  const pageCountRef = useRef<number>(0)
  const slideStatus = useLectureStore((s) => s.slideStatus)
  const setSlideId = useLectureStore((s) => s.setSlideId)
  const setSlideStatus = useLectureStore((s) => s.setSlideStatus)

  useEffect(() => {
    if (slideStatus === 'none') {
      setStage('pending')
      setStageCurrent(0)
      setStageTotal(0)
      setError(null)
      startedAtStageRef.current = null
      processStartedAtRef.current = 0
      pageCountRef.current = 0
    }
  }, [slideStatus])

  // 컴포넌트 언마운트 시 진행 중인 업로드/폴링 정리
  useEffect(() => {
    return () => {
      cancelledRef.current = true
      abortControllerRef.current?.abort()
      abortControllerRef.current = null
    }
  }, [])

  const processOneFile = useCallback(async (file: File) => {
    setCurrentFileName(file.name)
    setError(null)
    setSlideStatus('uploading')
    cancelledRef.current = false
    slideIdRef.current = null
    // 파일 단위로 통합 진행률 기준점 초기화 (큐의 다음 파일은 다시 0초부터)
    processStartedAtRef.current = Date.now()
    pageCountRef.current = 0
    startedAtStageRef.current = null

    const controller = new AbortController()
    abortControllerRef.current = controller

    // client_token: 응답 받기 전 취소된 경우 백엔드가 add_task 를 스킵하도록 매칭하는 키
    const token =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2)}`
    clientTokenRef.current = token

    const pollStatus = async (slideId: string, onDone: () => void) => {
      const checkStatus = async () => {
        if (cancelledRef.current) return
        try {
          const response = await fetch(`${API_BASE}/slides/status/${slideId}`)
          const data = await response.json()

          if (data.status === 'completed') {
            setStage('completed')
            setSlideId(null)
            setSlideStatus('none')
            slideIdRef.current = null
            clientTokenRef.current = null
            onUploadComplete?.()
            onDone()
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
          if (nextStage !== startedAtStageRef.current) {
            stageStartedAtRef.current = Date.now()
            startedAtStageRef.current = nextStage
          }
          // 페이지 수는 OCR/translate 단계의 stage_total 에서 한 번만 캐시.
          // weight 계산이 페이지수에 의존하므로 가능한 빨리 잡아두면 ETA 정확도 ↑.
          if (total > 0 && pageCountRef.current === 0 && (nextStage === 'ocr' || nextStage === 'translate')) {
            pageCountRef.current = total
          }
          setStage(nextStage)
          setStageCurrent(current)
          setStageTotal(total)

          if (!cancelledRef.current) setTimeout(checkStatus, 2000)
        } catch (err) {
          if (!cancelledRef.current) console.error('[UploadDropzone] 상태 확인 실패:', err)
        }
      }

      checkStatus()
    }

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('client_token', token)

      const response = await fetch(`${API_BASE}/slides/upload`, {
        method: 'POST',
        body: formData,
        signal: controller.signal,
      })
      abortControllerRef.current = null

      if (!response.ok) throw new Error('업로드에 실패했습니다.')

      const data = await response.json()
      // 응답 도착 전에 사용자가 취소했으면 토큰이 매칭되어 백엔드가 cancelled=true 로 회신
      if (data.cancelled || cancelledRef.current) {
        setSlideStatus('none')
        clientTokenRef.current = null
        return
      }

      slideIdRef.current = data.slide_id
      setSlideId(data.slide_id)
      setSlideStatus('processing')

      pollStatus(data.slide_id, () => {
        const nextFile = fileQueueRef.current.shift()
        if (nextFile) {
          setQueueProcessed((p) => p + 1)
          processOneFile(nextFile)
        } else {
          setQueueTotal(0)
          setQueueProcessed(0)
          setCurrentFileName('')
        }
      })
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      console.error('[UploadDropzone] 에러:', err)
      setError('업로드에 실패했습니다. 다시 시도해주세요.')
      setSlideStatus('none')
    }
  }, [setSlideId, setSlideStatus, onUploadComplete])

  const handleFilesSelect = useCallback((files: File[]) => {
    const validFiles: File[] = []
    const skipped: string[] = []

    for (const f of files) {
      if (f.type !== 'application/pdf') {
        skipped.push(`${f.name}(PDF 아님)`)
      } else if (f.size > 200 * 1024 * 1024) {
        skipped.push(`${f.name}(200MB 초과)`)
      } else {
        validFiles.push(f)
      }
    }

    if (validFiles.length === 0) {
      setError(skipped.length > 0 ? `제외된 파일: ${skipped.join(', ')}` : 'PDF 파일만 업로드 가능합니다.')
      return
    }

    setError(skipped.length > 0 ? `일부 제외: ${skipped.join(', ')}` : null)
    fileQueueRef.current = validFiles.slice(1)
    setQueueTotal(validFiles.length)
    setQueueProcessed(0)
    processOneFile(validFiles[0])
  }, [processOneFile])

  const handleCancel = useCallback(() => {
    cancelledRef.current = true
    fileQueueRef.current = []
    setQueueTotal(0)
    setQueueProcessed(0)
    setCurrentFileName('')
    abortControllerRef.current?.abort()
    abortControllerRef.current = null

    const sid = slideIdRef.current
    const token = clientTokenRef.current

    if (sid) {
      // 처리 중 — 백엔드 flag set 으로 다음 체크포인트에서 cleanup 트리거
      fetch(`${API_BASE}/slides/${sid}/cancel`, {
        method: 'POST',
        keepalive: true,
      }).catch(() => {})
    } else if (token) {
      // 업로드 응답 받기 전 — 토큰만 보류 등록. upload_slide 가 매칭되면 add_task 스킵
      fetch(`${API_BASE}/slides/cancel-pending?client_token=${encodeURIComponent(token)}`, {
        method: 'POST',
        keepalive: true,
      }).catch(() => {})
    }

    slideIdRef.current = null
    clientTokenRef.current = null
    processStartedAtRef.current = 0
    pageCountRef.current = 0
    setSlideStatus('none')
  }, [setSlideStatus])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) handleFilesSelect(files)
  }, [handleFilesSelect])

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
  }

  const handleClick = () => {
    inputRef.current?.click()
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length > 0) handleFilesSelect(files)
    e.target.value = ''
  }

  const isMultiple = queueTotal > 1

  // 통합 진행률/ETA: 모델 로드(pending) → OCR → 번역 → PDF 생성(bundling) 전체를
  // 하나의 0~1 진행률로 환산하고, elapsed 기반 단순 외삽으로 종료 예상 시간을 낸다.
  //
  // weight 는 페이지 수 n 에 따라 동적으로 계산 — 모델 로드는 거의 고정 시간이고
  // OCR/번역/bundling 은 페이지수에 비례하므로, 페이지가 적으면 pending 비중↑,
  // 페이지가 많으면 번역 비중↑ 으로 자동 보정된다. (1페이지/100페이지 양극단도 흡수)
  //
  // 모든 계산은 NaN/Infinity/음수에 대해 방어적으로 동작. 정보 부족 시 그냥 null/0 반환.
  const computeWeights = (pageCount: number) => {
    const n = Math.max(1, pageCount)
    const tPending = 15           // 모델 로드 + PDF 읽기 (대략, 이미 로드돼 있으면 짧아짐)
    const tOcr = 1.5 * n          // 페이지당 OCR (surya, GPU)
    const tTranslate = 7 * n      // 페이지당 VLM 번역
    const tBundling = 0.5 * n + 5 // PDF 생성: 페이지당 + 폰트 임베딩 등 고정 비용
    const total = tPending + tOcr + tTranslate + tBundling
    return {
      pending: tPending / total,
      ocr: tOcr / total,
      translate: tTranslate / total,
      bundling: tBundling / total,
      expectedTotalSec: total,
    }
  }

  const weights = computeWeights(pageCountRef.current || 10)

  const unifiedProgress: number = (() => {
    if (slideStatus === 'uploading') return 0
    if (stage === 'completed') return 1
    if (stage === 'failed') return 0
    if (stage === 'pending') {
      // pending 은 stage_total 이 없으므로 elapsed/expected 로 부분 추정 (최대 90% cap).
      if (processStartedAtRef.current === 0) return 0
      const elapsed = (Date.now() - processStartedAtRef.current) / 1000
      const expected = weights.expectedTotalSec * weights.pending
      if (expected <= 0) return 0
      return Math.min(weights.pending * 0.9, (elapsed / expected) * weights.pending)
    }
    if (stage === 'ocr') {
      const frac = stageTotal > 0 ? Math.min(1, stageCurrent / stageTotal) : 0
      return weights.pending + weights.ocr * frac
    }
    if (stage === 'translate') {
      const frac = stageTotal > 0 ? Math.min(1, stageCurrent / stageTotal) : 0
      return weights.pending + weights.ocr + weights.translate * frac
    }
    if (stage === 'bundling') {
      // bundling 도 stage_total=0 이라 elapsed/expected 로 추정 (최대 95% cap, 완료 점프 방지).
      if (stageStartedAtRef.current === 0) {
        return weights.pending + weights.ocr + weights.translate
      }
      const elapsed = (Date.now() - stageStartedAtRef.current) / 1000
      const expected = weights.expectedTotalSec * weights.bundling
      const frac = expected > 0 ? Math.min(0.95, elapsed / expected) : 0
      return weights.pending + weights.ocr + weights.translate + weights.bundling * frac
    }
    return 0
  })()

  const unifiedEtaText: string | null = (() => {
    if (slideStatus !== 'processing') return null
    if (stage === 'completed' || stage === 'failed') return null
    if (processStartedAtRef.current === 0) return null
    const elapsed = (Date.now() - processStartedAtRef.current) / 1000
    if (elapsed < 5) return null  // 초반 표본 부족 — 디폴트 weight 만으로 ETA 내면 부정확
    const p = unifiedProgress
    if (!isFinite(p) || p <= 0.02 || p >= 1) return null
    const remaining = (elapsed * (1 - p)) / p
    if (!isFinite(remaining) || remaining <= 0) return null
    if (remaining < 60) return `약 ${Math.max(1, Math.round(remaining))}초 남음`
    const m = Math.floor(remaining / 60)
    const s = Math.round(remaining % 60)
    return s === 0 ? `약 ${m}분 남음` : `약 ${m}분 ${s}초 남음`
  })()

  const unifiedPercent = Math.max(0, Math.min(100, Math.round(unifiedProgress * 100)))

  return (
    <div className="text-onSurface min-h-[140px]">
      <input
        ref={inputRef}
        type="file"
        accept=".pdf"
        multiple
        onChange={handleChange}
        className="hidden"
      />

      {slideStatus === 'uploading' || slideStatus === 'processing' ? (
        <div className="py-4 px-2">
          <div className="flex items-center gap-2 mb-1">
            <svg className="animate-spin w-5 h-5 text-primary flex-shrink-0" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            <p className="text-base font-medium text-onSurface">
              {slideStatus === 'uploading'
                ? '업로드 중...'
                : `${STAGE_LABELS[stage]} ${unifiedPercent}%${unifiedEtaText ? ` · ${unifiedEtaText}` : ''}`}
            </p>
            {isMultiple && (
              <span className="ml-auto text-xs text-onSurface/50 flex-shrink-0">
                {queueProcessed + 1}/{queueTotal}
              </span>
            )}
          </div>

          {currentFileName && (
            <p className="text-xs text-onSurface/50 mb-2 truncate" title={currentFileName}>
              {currentFileName}
            </p>
          )}

          <div className="w-full h-2 bg-primaryContainer/40 rounded-full overflow-hidden">
            <div
              className="h-full bg-primary transition-all duration-300"
              style={{ width: `${unifiedPercent}%` }}
            />
          </div>

          <button
            type="button"
            onClick={handleCancel}
            className="mt-4 w-full py-2 text-sm text-error border border-error/30 rounded-lg hover:bg-error/10 transition-colors"
          >
            업로드 중단
          </button>
        </div>
      ) : (
        // uploading/processing 외의 모든 상태(none/ready/failed)에서 드롭존 노출.
        // → 처리 완료 후 자연스럽게 다시 활성화. 업로드 중일 때만 progress UI 가 차지.
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
          <p className="text-xs text-onSurface/50 mt-1">여러 파일 동시 선택 가능 · 업로드 즉시 번역이 시작됩니다</p>
        </div>
      )}

      {error && (
        <p className="text-sm text-error mt-2 text-center">{error}</p>
      )}
    </div>
  )
}
