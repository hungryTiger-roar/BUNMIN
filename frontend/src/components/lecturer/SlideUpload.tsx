import { useCallback, useRef, useState } from 'react'
import { useLectureStore } from '@/stores/lectureStore'
import { API_BASE, switchToRealtimeMode, switchToSlideMode } from '@/lib/api'

function SlideUpload() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const { slideStatus, setSlideId, setSlideStatus, modelMode, setModelMode } = useLectureStore()

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
    const maxAttempts = 300 // 최대 10분 (페이지 많은 PDF 대응)
    let attempts = 0

    const checkStatus = async () => {
      try {
        const response = await fetch(`${API_BASE}/slides/status/${slideId}`)
        const data = await response.json()

        if (data.status === 'completed') {
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
          setError('강의자료 처리에 실패했습니다.')
          setSlideStatus('none')
          return
        }

        // 진행률 업데이트
        if (data.total_pages > 0) {
          setUploadProgress(Math.round((data.processed_pages / data.total_pages) * 100))
        }

        attempts++
        if (attempts < maxAttempts) {
          setTimeout(checkStatus, 2000)
        } else {
          setError('처리 시간이 초과되었습니다.')
          setSlideStatus('none')
        }
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
      ) : slideStatus === 'uploading' || slideStatus === 'processing' ? (
        <div className="text-center py-6">
          <div className="w-12 h-12 mx-auto mb-3 relative">
            <svg className="animate-spin w-12 h-12 text-primary" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          </div>
          <p className="text-sm text-onSurface/80">
            {slideStatus === 'uploading' ? '업로드 중...' : '처리 중...'}
          </p>
          {slideStatus === 'processing' && uploadProgress > 0 && (
            <p className="text-xs text-onSurface/50 mt-1">{uploadProgress}% 완료</p>
          )}
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
