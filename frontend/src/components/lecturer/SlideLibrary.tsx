import { useEffect, useMemo, useState } from 'react'
import { getSlideLibrary, deleteSlidesBatch } from '@/lib/api'
import type { SlideLibraryItem as Item } from '@/types/slide'
import SlideLibraryItem from './SlideLibraryItem'
import DeleteConfirmModal from './DeleteConfirmModal'
import SlideLibrarySearchModal from './SlideLibrarySearchModal'

interface Props {
  /** 외부에서 라이브러리 새로고침을 트리거하는 키 (값 변경 시 재조회) */
  refreshKey?: number
}

// 카드 1개 높이 ≈ 64px (p-3 + 텍스트 2줄), 사이 gap 8px → 3개 노출 = 64*3 + 8*2 = 208px
const VISIBLE_MAX_HEIGHT = 208

export default function SlideLibrary({ refreshKey = 0 }: Props) {
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [showSearchModal, setShowSearchModal] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await getSlideLibrary('recent')
        if (!cancelled) setItems(data.items)
      } catch (err) {
        if (!cancelled) {
          console.error('[SlideLibrary] 조회 실패:', err)
          setError('라이브러리를 불러오지 못했습니다')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [refreshKey])

  // 라이브러리 카드 영역은 항상 최신순 (검색/정렬은 검색 모달에서)
  const sortedItems = useMemo(() => {
    return [...items].sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at))
  }, [items])

  const toggleSelect = (slideId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(slideId)) next.delete(slideId)
      else next.add(slideId)
      return next
    })
  }

  const enterSelectionMode = () => {
    setSelectionMode(true)
    setSelectedIds(new Set())
  }

  const exitSelectionMode = () => {
    setSelectionMode(false)
    setSelectedIds(new Set())
  }

  const handleRenamed = (slideId: string, newFilename: string) => {
    setItems((prev) =>
      prev.map((it) => (it.slide_id === slideId ? { ...it, filename: newFilename } : it))
    )
  }

  const handleBatchDelete = async () => {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) return
    setDeleting(true)
    try {
      const res = await deleteSlidesBatch(ids)
      // 성공한 것만 제거 (failed는 유지하고 사용자에게 알림)
      const deletedSet = new Set(res.deleted)
      setItems((prev) => prev.filter((item) => !deletedSet.has(item.slide_id)))
      if (res.failed.length > 0) {
        const reasons = res.failed.map((f) => `- ${f.slide_id}: ${f.reason}`).join('\n')
        alert(`일부 항목 삭제 실패:\n${reasons}`)
      }
    } catch (err) {
      console.error('[SlideLibrary] 일괄 삭제 실패:', err)
      alert('삭제 중 오류가 발생했습니다')
    } finally {
      setDeleting(false)
      setShowDeleteModal(false)
      exitSelectionMode()
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-3 gap-2">
        <h3 className="text-sm font-semibold text-onSurface flex-shrink-0">강의자료 라이브러리</h3>

        {!selectionMode ? (
          <div className="flex items-center gap-1">
            <button
              type="button"
              aria-label="강의자료 검색"
              title="강의자료 검색"
              onClick={() => setShowSearchModal(true)}
              className="p-1.5 text-onSurface/60 hover:text-onSurface hover:bg-primaryContainer/40 rounded transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </button>
            <button
              type="button"
              aria-label="강의자료 삭제"
              title="강의자료 삭제"
              onClick={enterSelectionMode}
              className="p-1.5 text-onSurface/60 hover:text-onSurface hover:bg-primaryContainer/40 rounded transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={exitSelectionMode}
              className="px-2 py-1 text-xs border border-primaryContainer rounded hover:bg-primaryContainer/40 transition-colors"
            >
              취소
            </button>
            <button
              type="button"
              onClick={() => setShowDeleteModal(true)}
              disabled={selectedIds.size === 0 || deleting}
              className="flex items-center gap-1 px-2 py-1 text-xs bg-error text-white rounded disabled:opacity-40 hover:opacity-90 transition-opacity"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              삭제({selectedIds.size})
            </button>
          </div>
        )}
      </div>

      {/* 목록 / 빈 상태 / 로딩 / 에러 */}
      {loading ? (
        <p className="text-sm text-onSurface/60 text-center py-8">로딩 중...</p>
      ) : error ? (
        <p className="text-sm text-error text-center py-8">{error}</p>
      ) : sortedItems.length === 0 ? (
        <p className="text-sm text-onSurface/60 text-center py-8">
          저장된 강의자료가 없습니다
        </p>
      ) : (
        <div
          className="space-y-2 overflow-y-auto pr-1 scrollbar-always"
          style={{ maxHeight: `${VISIBLE_MAX_HEIGHT}px` }}
        >
          {sortedItems.map((item) => (
            <SlideLibraryItem
              key={item.slide_id}
              item={item}
              selectionMode={selectionMode}
              selected={selectedIds.has(item.slide_id)}
              onToggleSelect={toggleSelect}
              onRenamed={handleRenamed}
            />
          ))}
        </div>
      )}

      {showDeleteModal && (
        <DeleteConfirmModal
          count={selectedIds.size}
          onConfirm={handleBatchDelete}
          onCancel={() => setShowDeleteModal(false)}
        />
      )}

      {showSearchModal && (
        <SlideLibrarySearchModal
          items={items}
          onClose={() => setShowSearchModal(false)}
          onDeleted={(slideIds) => {
            setItems((prev) => prev.filter((it) => !slideIds.includes(it.slide_id)))
          }}
        />
      )}
    </div>
  )
}
