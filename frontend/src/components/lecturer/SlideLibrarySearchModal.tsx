import { useEffect, useMemo, useRef, useState } from 'react'
import { API_BASE, deleteSlidesBatch, loadSlide, switchToRealtimeMode } from '@/lib/api'
import { useLectureStore } from '@/stores/lectureStore'
import type { SlideLibraryItem as Item, SortOrder } from '@/types/slide'
import DeleteConfirmModal from './DeleteConfirmModal'

interface Props {
  items: Item[]
  onClose: () => void
  /** 모달 안에서 강의자료를 삭제했을 때 부모 라이브러리 목록도 동기화 */
  onDeleted?: (slideIds: string[]) => void
  className?: string
}

const SORT_LABELS: Record<SortOrder, string> = {
  recent: '최신순',
  name: '이름순',
  size: '파일 크기 순',
}

function formatDate(iso: string): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    })
  } catch {
    return ''
  }
}

function formatFileSize(bytes?: number): string {
  if (!bytes || bytes <= 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let v = bytes
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

export default function SlideLibrarySearchModal({ items, onClose, onDeleted, className }: Props) {
  const [query, setQuery] = useState('')
  const [sortOrder, setSortOrder] = useState<SortOrder>('recent')
  const [selectedId, setSelectedId] = useState<string | null>(items[0]?.slide_id ?? null)
  const [previewPage, setPreviewPage] = useState(0)
  const [previewLoaded, setPreviewLoaded] = useState(false)
  const [previewError, setPreviewError] = useState(false)
  const [loading, setLoading] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set())
  const inputRef = useRef<HTMLInputElement>(null)
  const selectAllRef = useRef<HTMLInputElement>(null)

  const setSlideId = useLectureStore((s) => s.setSlideId)
  const setSlideStatus = useLectureStore((s) => s.setSlideStatus)
  const setSlideFilename = useLectureStore((s) => s.setSlideFilename)
  const setModelMode = useLectureStore((s) => s.setModelMode)
  const setCurrentPage = useLectureStore((s) => s.setCurrentPage)

  // 모달 오픈 시 검색창 자동 포커스
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // ESC로 닫기
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  // 검색/정렬 적용
  const filteredItems = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = q
      ? items.filter((it) => it.filename.toLowerCase().includes(q))
      : items
    const arr = [...filtered]
    if (sortOrder === 'name') {
      arr.sort((a, b) => a.filename.localeCompare(b.filename, 'ko'))
    } else if (sortOrder === 'size') {
      arr.sort((a, b) => (b.file_size ?? 0) - (a.file_size ?? 0))
    } else {
      arr.sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at))
    }
    return arr
  }, [items, query, sortOrder])

  // 필터 결과가 바뀌면 선택 항목이 사라질 수 있음 — 첫 항목 자동 선택
  useEffect(() => {
    if (filteredItems.length === 0) {
      setSelectedId(null)
      return
    }
    if (!selectedId || !filteredItems.some((it) => it.slide_id === selectedId)) {
      setSelectedId(filteredItems[0].slide_id)
    }
  }, [filteredItems, selectedId])

  // 선택 변경 시 미리보기 페이지/로딩 상태 리셋
  useEffect(() => {
    setPreviewPage(0)
    setPreviewLoaded(false)
    setPreviewError(false)
  }, [selectedId])

  // 전체선택 체크박스 indeterminate 동기화
  useEffect(() => {
    const el = selectAllRef.current
    if (!el) return
    const someChecked = checkedIds.size > 0
    const allChecked = filteredItems.length > 0 && filteredItems.every((it) => checkedIds.has(it.slide_id))
    el.indeterminate = someChecked && !allChecked
  }, [checkedIds, filteredItems])

  const selected = useMemo(
    () => items.find((it) => it.slide_id === selectedId) ?? null,
    [items, selectedId],
  )

  const handleBatchDelete = async () => {
    if (checkedIds.size === 0 || deleting) return
    setDeleting(true)
    const ids = Array.from(checkedIds)
    try {
      await deleteSlidesBatch(ids)
      onDeleted?.(ids)
      setCheckedIds(new Set())
      setShowDeleteConfirm(false)
    } catch (err) {
      console.error('[SlideLibrarySearch] 강의자료 삭제 실패:', err)
      alert(err instanceof Error ? err.message : '강의자료 삭제 실패')
    } finally {
      setDeleting(false)
    }
  }

  const loadAndClose = async (item: Item) => {
    if (item.status !== 'completed' || loading) return
    setLoading(true)
    try {
      const res = await loadSlide(item.slide_id)
      setSlideId(item.slide_id)
      setSlideFilename(item.filename)
      setCurrentPage(res.last_page ?? 1)
      setSlideStatus('ready')
      setModelMode('switching')
      try {
        await switchToRealtimeMode()
        setModelMode('realtime')
      } catch (err) {
        console.error('[SlideLibrarySearch] 실시간 모드 전환 실패:', err)
        setModelMode('idle')
      }
      onClose()
    } catch (err) {
      console.error('[SlideLibrarySearch] 강의자료 로드 실패:', err)
      alert(err instanceof Error ? err.message : '강의자료 로드 실패')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className={`fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 ${className ?? ''}`}
      onClick={onClose}
    >
      <div
        className="bg-surface text-onSurface rounded-2xl shadow-2xl flex flex-col w-[min(95%,1000px)] h-[min(85vh,720px)] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-primaryContainer flex-shrink-0">
          <h3 className="text-sm font-semibold">강의자료 라이브러리</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="w-8 h-8 rounded-full flex items-center justify-center text-onSurface/60 hover:bg-primaryContainer/40 transition-colors"
          >
            ✕
          </button>
        </div>

        {/* 검색창 + 정렬 */}
        <div className="flex flex-col gap-2 px-5 py-3 border-b border-primaryContainer flex-shrink-0">
          <div className="relative">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-onSurface/50 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="파일 이름으로 검색..."
              className="w-full pl-9 pr-3 py-2 bg-white border border-primaryContainer rounded-lg text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
          <div className="flex items-center gap-1">
            {(Object.keys(SORT_LABELS) as SortOrder[]).map((order) => (
              <button
                key={order}
                type="button"
                onClick={() => setSortOrder(order)}
                className={`px-2.5 py-1 text-xs rounded transition-colors ${
                  sortOrder === order
                    ? 'bg-primary/10 text-primary font-medium'
                    : 'text-onSurface/60 hover:bg-primaryContainer/40'
                }`}
              >
                {SORT_LABELS[order]}
              </button>
            ))}
            <button
              type="button"
              aria-label="선택한 강의자료 삭제"
              title={checkedIds.size > 0 ? `${checkedIds.size}개 삭제` : '강의자료를 선택 후 삭제하세요'}
              onClick={() => setShowDeleteConfirm(true)}
              disabled={checkedIds.size === 0}
              className="ml-auto p-1.5 text-onSurface/60 hover:text-error hover:bg-error/10 rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:text-onSurface/60 disabled:hover:bg-transparent"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
        </div>

        {/* 본문: 좌측 목록 + 우측 미리보기 */}
        <div className="flex-1 min-h-0 flex">
          {/* 파일 목록 */}
          <div className="w-[42%] min-w-[280px] border-r border-primaryContainer overflow-y-auto p-2">
            {filteredItems.length === 0 ? (
              <p className="text-sm text-onSurface/60 text-center py-12">
                {query ? '검색 결과가 없습니다' : '저장된 강의자료가 없습니다'}
              </p>
            ) : (
              <>
                {/* 전체선택 행 */}
                <div className="flex items-center gap-2 px-3 py-2 mb-1 border-b border-primaryContainer">
                  <input
                    ref={selectAllRef}
                    type="checkbox"
                    checked={filteredItems.every((it) => checkedIds.has(it.slide_id))}
                    onChange={(e) =>
                      setCheckedIds(
                        e.target.checked
                          ? new Set(filteredItems.map((it) => it.slide_id))
                          : new Set()
                      )
                    }
                    className="w-4 h-3.5 accent-primary cursor-pointer"
                  />
                  <span className="text-xs text-onSurface/60">
                    {checkedIds.size > 0 ? `${checkedIds.size}개 선택됨` : '전체 선택'}
                  </span>
                </div>

                <ul className="space-y-1">
                  {filteredItems.map((item) => {
                    const isSelected = item.slide_id === selectedId
                    const disabled = item.status !== 'completed'
                    return (
                      <li key={item.slide_id}>
                        <div
                          className={`flex items-center gap-1 px-2 py-1.5 rounded-lg transition-colors
                            ${isSelected ? 'bg-primary/10 border border-primary/40' : 'border border-transparent hover:bg-primaryContainer/30'}
                            ${disabled ? 'opacity-50' : ''}`}
                        >
                          <input
                            type="checkbox"
                            checked={checkedIds.has(item.slide_id)}
                            onChange={(e) =>
                              setCheckedIds((prev) => {
                                const next = new Set(prev)
                                if (e.target.checked) next.add(item.slide_id)
                                else next.delete(item.slide_id)
                                return next
                              })
                            }
                            onClick={(e) => e.stopPropagation()}
                            className="w-6 h-3.5 flex-shrink-0 accent-primary cursor-pointer"
                          />
                          <button
                            type="button"
                            onClick={() => setSelectedId(item.slide_id)}
                            onDoubleClick={() => loadAndClose(item)}
                            disabled={disabled}
                            className={`flex-1 flex items-center gap-2 px-1.5 py-0.5 text-left min-w-0 ${disabled ? 'cursor-not-allowed' : 'cursor-pointer'}`}
                          >
                            <svg className="w-4 h-4 flex-shrink-0 text-onSurface/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                            </svg>
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium truncate">{item.filename}</p>
                              <p className="text-xs text-onSurface/60 mt-0.5">
                                {item.total_pages}페이지 · {formatFileSize(item.file_size)}
                                {item.uploaded_at && ` · ${formatDate(item.uploaded_at)}`}
                              </p>
                            </div>
                          </button>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              </>
            )}
          </div>

          {/* 미리보기 */}
          <div className="flex-1 min-w-0 flex flex-col">
            {selected ? (
              <>
                <div className="px-4 py-2 border-b border-primaryContainer flex-shrink-0">
                  <p className="text-sm font-medium truncate">{selected.filename}</p>
                  <p className="text-xs text-onSurface/60 mt-0.5">
                    {selected.total_pages}페이지 · {formatFileSize(selected.file_size)}
                    {selected.uploaded_at && ` · ${formatDate(selected.uploaded_at)}`}
                  </p>
                </div>

                <div className="relative flex-1 min-h-0 bg-black flex items-center justify-center overflow-hidden">
                  {!previewLoaded && !previewError && (
                    <div className="absolute inset-0 flex items-center justify-center text-white/60">
                      <svg className="animate-spin w-7 h-7" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                      </svg>
                    </div>
                  )}
                  {previewError ? (
                    <p className="text-white/70 text-sm">미리보기를 불러올 수 없습니다</p>
                  ) : (
                    <img
                      key={`${selected.slide_id}-${previewPage}`}
                      src={`${API_BASE}/slides/image/${selected.slide_id}/${previewPage}`}
                      alt={`${selected.filename} 페이지 ${previewPage + 1}`}
                      onLoad={() => setPreviewLoaded(true)}
                      onError={() => setPreviewError(true)}
                      className={`max-w-full max-h-full object-contain transition-opacity ${
                        previewLoaded ? 'opacity-100' : 'opacity-0'
                      }`}
                    />
                  )}

                  {selected.total_pages > 1 && (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          setPreviewPage((p) => Math.max(0, p - 1))
                          setPreviewLoaded(false)
                          setPreviewError(false)
                        }}
                        disabled={previewPage <= 0}
                        aria-label="이전 페이지"
                        className="absolute left-2 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full bg-black/60 text-white flex items-center justify-center hover:bg-black/80 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                        </svg>
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setPreviewPage((p) => Math.min(selected.total_pages - 1, p + 1))
                          setPreviewLoaded(false)
                          setPreviewError(false)
                        }}
                        disabled={previewPage >= selected.total_pages - 1}
                        aria-label="다음 페이지"
                        className="absolute right-2 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full bg-black/60 text-white flex items-center justify-center hover:bg-black/80 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                      </button>
                    </>
                  )}
                </div>

                <div className="flex items-center justify-between px-4 py-2 border-t border-primaryContainer flex-shrink-0">
                  <span className="text-xs text-onSurface/60 font-mono tabular-nums">
                    {previewPage + 1} / {selected.total_pages}
                  </span>
                  <button
                    type="button"
                    onClick={() => loadAndClose(selected)}
                    disabled={selected.status !== 'completed' || loading}
                    className="px-3 py-1.5 bg-primary text-onPrimary text-sm font-medium rounded-lg disabled:opacity-50 hover:opacity-90 transition-opacity"
                  >
                    {loading ? '불러오는 중...' : '불러오기'}
                  </button>
                </div>
              </>
            ) : (
              <div className="flex-1 flex items-center justify-center text-onSurface/50 text-sm">
                미리볼 강의자료를 선택하세요
              </div>
            )}
          </div>
        </div>
      </div>

      {showDeleteConfirm && (
        <DeleteConfirmModal
          count={checkedIds.size}
          onConfirm={handleBatchDelete}
          onCancel={() => setShowDeleteConfirm(false)}
        />
      )}
    </div>
  )
}
