import { useEffect, useState } from 'react'
import { API_BASE } from '@/lib/api'

interface Props {
  slideId: string
  filename: string
  totalPages: number
  onClose: () => void
}

export default function SlidePreviewModal({ slideId, filename, totalPages, onClose }: Props) {
  // 0-indexed (backend 이미지 경로 규약)
  const [page, setPage] = useState(0)
  const [imgLoaded, setImgLoaded] = useState(false)
  const [imgError, setImgError] = useState(false)

  // 키보드 네비게이션 (ESC, 좌/우 화살표)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        setPage((p) => Math.max(0, p - 1))
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        setPage((p) => Math.min(totalPages - 1, p + 1))
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [totalPages, onClose])

  // 페이지 변경 시 로딩 상태 리셋
  useEffect(() => {
    setImgLoaded(false)
    setImgError(false)
  }, [page])

  const canPrev = page > 0
  const canNext = page < totalPages - 1
  const imageUrl = `${API_BASE}/slides/image/${slideId}/${page}`

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="bg-surface text-onSurface rounded-2xl shadow-2xl flex flex-col w-[min(95%,900px)] max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-primaryContainer flex-shrink-0">
          <h3 className="text-sm font-semibold truncate flex-1 min-w-0 mr-3 flex items-center gap-2">
            <svg className="w-4 h-4 flex-shrink-0 text-onSurface/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <span className="truncate">{filename}</span>
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="w-8 h-8 rounded-full flex items-center justify-center text-onSurface/60 hover:bg-primaryContainer/40 transition-colors flex-shrink-0"
          >
            ✕
          </button>
        </div>

        {/* 이미지 영역 */}
        <div className="relative flex-1 min-h-0 bg-black flex items-center justify-center overflow-hidden">
          {!imgLoaded && !imgError && (
            <div className="absolute inset-0 flex items-center justify-center text-white/60">
              <svg className="animate-spin w-8 h-8" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
            </div>
          )}
          {imgError ? (
            <p className="text-white/70 text-sm">이미지를 불러올 수 없습니다</p>
          ) : (
            <img
              key={page}
              src={imageUrl}
              alt={`${filename} 페이지 ${page + 1}`}
              onLoad={() => setImgLoaded(true)}
              onError={() => setImgError(true)}
              className={`max-w-full max-h-[70vh] object-contain transition-opacity ${
                imgLoaded ? 'opacity-100' : 'opacity-0'
              }`}
            />
          )}

          {/* 좌측 이전 버튼 */}
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={!canPrev}
            aria-label="이전 페이지"
            className="absolute left-3 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-black/60 text-white flex items-center justify-center hover:bg-black/80 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>

          {/* 우측 다음 버튼 */}
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={!canNext}
            aria-label="다음 페이지"
            className="absolute right-3 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-black/60 text-white flex items-center justify-center hover:bg-black/80 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>

        {/* 푸터 — 페이지 카운터 */}
        <div className="flex items-center justify-center px-5 py-3 border-t border-primaryContainer flex-shrink-0">
          <span className="text-sm text-onSurface/70 font-mono tabular-nums">
            {page + 1} / {totalPages}
          </span>
        </div>
      </div>
    </div>
  )
}
