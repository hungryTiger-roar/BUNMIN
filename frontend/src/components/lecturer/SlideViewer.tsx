import { useEffect } from 'react'
import { useLectureStore } from '@/stores/lectureStore'
import { usePreferencesStore, type AspectRatio } from '@/stores/preferencesStore'
import { API_BASE } from '@/lib/api'

const ASPECT_CLASS: Record<AspectRatio, string> = {
  '16/9': 'aspect-[16/9]',
  '4/3': 'aspect-[4/3]',
  '5/3': 'aspect-[5/3]',
}

interface SlideViewerProps {
  onPageChange?: (page: number) => void
  children?: React.ReactNode
  containerRef?: React.RefObject<HTMLDivElement>
}

function SlideViewer({ onPageChange, children, containerRef }: SlideViewerProps) {
  const aspectRatio = usePreferencesStore((s) => s.aspectRatio)
  const aspectClass = ASPECT_CLASS[aspectRatio]
  const {
    slideId,
    slideStatus,
    currentPage,
    totalPages,
    slidePages,
    setSlidePages,
    nextPage,
    prevPage,
  } = useLectureStore()

  // 슬라이드 페이지 목록 로드
  useEffect(() => {
    if (slideId && slideStatus === 'ready') {
      loadSlidePages()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      // 입력 필드 포커스된 경우 키보드 내비게이션 스킵
      const target = e.target as HTMLElement
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
      ) {
        return
      }
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

  const currentSlideImage = slidePages[currentPage - 1]?.imageUrl

  // aspect 박스 한 개만 렌더 — 페이지 네비/썸네일은 Lecturer에서 별도 배치
  return (
    <div
      ref={containerRef}
      className={`relative bg-slate-900 rounded-xl overflow-hidden ${aspectClass} max-h-full h-full max-w-full group shadow-2xl`}
    >
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

      {/* 오버레이 (자막 등) */}
      {children}
    </div>
  )
}

export default SlideViewer
