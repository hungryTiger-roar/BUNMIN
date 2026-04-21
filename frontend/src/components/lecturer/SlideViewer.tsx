import { useEffect } from 'react'
import { useLectureStore } from '@/stores/lectureStore'
import { API_BASE } from '@/lib/api'

interface SlideViewerProps {
  onPageChange?: (page: number) => void
}

function SlideViewer({ onPageChange }: SlideViewerProps) {
  const {
    slideId,
    slideStatus,
    currentPage,
    totalPages,
    slidePages,
    setCurrentPage,
    setSlidePages,
    nextPage,
    prevPage,
  } = useLectureStore()

  // 슬라이드 페이지 목록 로드
  useEffect(() => {
    if (slideId && slideStatus === 'ready') {
      loadSlidePages()
    }
  }, [slideId, slideStatus])

  const loadSlidePages = async () => {
    if (!slideId) return

    try {
      const response = await fetch(`${API_BASE}/slides/pages/${slideId}`)
      if (!response.ok) throw new Error('Failed to load slides')

      const data = await response.json()
      setSlidePages(data.pages)
    } catch (err) {
      console.error('[SlideViewer] 슬라이드 로드 실패:', err)
    }
  }

  // 페이지 변경 시 콜백 호출
  useEffect(() => {
    if (onPageChange && currentPage > 0) {
      onPageChange(currentPage)
    }
  }, [currentPage, onPageChange])

  // 키보드 네비게이션
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === ' ') {
        e.preventDefault()
        nextPage()
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault()
        prevPage()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [nextPage, prevPage])

  // 현재 슬라이드 이미지 URL
  const currentSlideImage = slidePages[currentPage - 1]?.imageUrl

  // 슬라이드가 없을 때
  if (slideStatus !== 'ready' || !slideId) {
    return (
      <div className="bg-slate-900 rounded-xl overflow-hidden aspect-video flex items-center justify-center">
        <div className="text-slate-500 text-center">
          <svg className="w-16 h-16 mx-auto mb-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <p>강의자료를 업로드하세요</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* 슬라이드 표시 영역 */}
      <div className="relative bg-slate-900 rounded-xl overflow-hidden aspect-video group">
        {currentSlideImage ? (
          <img
            src={`${API_BASE}${currentSlideImage}`}
            alt={`슬라이드 ${currentPage}`}
            className="w-full h-full object-contain"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-slate-500">
            <div className="animate-pulse">로딩 중...</div>
          </div>
        )}

        {/* 이전/다음 버튼 (호버 시 표시) */}
        <button
          onClick={prevPage}
          disabled={currentPage <= 1}
          className="absolute left-2 top-1/2 -translate-y-1/2 p-3 bg-black/50 hover:bg-black/70 rounded-full text-white opacity-0 group-hover:opacity-100 transition-opacity disabled:opacity-0"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>

        <button
          onClick={nextPage}
          disabled={currentPage >= totalPages}
          className="absolute right-2 top-1/2 -translate-y-1/2 p-3 bg-black/50 hover:bg-black/70 rounded-full text-white opacity-0 group-hover:opacity-100 transition-opacity disabled:opacity-0"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>

      </div>

      {/* 하단 네비게이션 */}
      <div className="flex items-center justify-between bg-white rounded-xl p-3 shadow-sm">
        <button
          onClick={prevPage}
          disabled={currentPage <= 1}
          className="flex items-center gap-1 px-3 py-2 rounded-lg text-slate-600 hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          <span className="text-sm">이전</span>
        </button>

        {/* 페이지 직접 선택 */}
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={1}
            max={totalPages}
            value={currentPage}
            onChange={(e) => {
              const page = parseInt(e.target.value)
              if (page >= 1 && page <= totalPages) {
                setCurrentPage(page)
              }
            }}
            className="w-16 px-2 py-1 text-center border border-slate-200 rounded-lg text-sm"
          />
          <span className="text-slate-500 text-sm">/ {totalPages}</span>
        </div>

        <button
          onClick={nextPage}
          disabled={currentPage >= totalPages}
          className="flex items-center gap-1 px-3 py-2 rounded-lg text-slate-600 hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <span className="text-sm">다음</span>
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>
      </div>

      {/* 썸네일 (선택적) */}
      {totalPages <= 20 && (
        <div className="flex gap-2 overflow-x-auto pb-2">
          {slidePages.map((page, index) => (
            <button
              key={page.pageNumber}
              onClick={() => setCurrentPage(index + 1)}
              className={`flex-shrink-0 w-20 h-12 rounded-lg overflow-hidden border-2 transition-colors ${
                currentPage === index + 1
                  ? 'border-primary-500'
                  : 'border-transparent hover:border-slate-300'
              }`}
            >
              <img
                src={`${API_BASE}${page.imageUrl}`}
                alt={`썸네일 ${index + 1}`}
                className="w-full h-full object-cover"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default SlideViewer
