import { useEffect, useRef, useState } from 'react'
import { loadSlide, renameSlide, switchToRealtimeMode } from '@/lib/api'
import { useLectureStore } from '@/stores/lectureStore'
import type { SlideLibraryItem as Item } from '@/types/slide'
import SlidePreviewModal from './SlidePreviewModal'

interface Props {
  item: Item
  selectionMode: boolean
  selected: boolean
  onToggleSelect: (slideId: string) => void
  onRenamed: (slideId: string, newFilename: string) => void
}

export default function SlideLibraryItem({
  item,
  selectionMode,
  selected,
  onToggleSelect,
  onRenamed,
}: Props) {
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draftName, setDraftName] = useState(item.filename.replace(/\.pdf$/i, ''))
  const [savingName, setSavingName] = useState(false)
  const [showPreview, setShowPreview] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const setSlideId = useLectureStore((s) => s.setSlideId)
  const setSlideStatus = useLectureStore((s) => s.setSlideStatus)
  const setSlideFilename = useLectureStore((s) => s.setSlideFilename)
  const setModelMode = useLectureStore((s) => s.setModelMode)
  const setCurrentPage = useLectureStore((s) => s.setCurrentPage)

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [editing])

  const handleCardClick = async () => {
    // 선택 모드: 카드 클릭 = 체크박스 토글
    if (selectionMode) {
      onToggleSelect(item.slide_id)
      return
    }
    // 편집 중에는 카드 클릭 동작 안 함
    if (editing) return
    // 일반 모드: 카드 클릭 = 무조건 불러오기 (요구사항)
    if (item.status !== 'completed') return
    setLoading(true)
    try {
      const res = await loadSlide(item.slide_id)
      setSlideId(item.slide_id)
      setSlideFilename(item.filename)
      // 마지막 본 페이지로 복원 (없으면 1페이지)
      setCurrentPage(res.last_page ?? 1)
      setSlideStatus('ready')
      // 새 업로드 흐름과 동일하게 실시간 모드로 전환 (강의 시작 가능 상태)
      setModelMode('switching')
      try {
        await switchToRealtimeMode()
        setModelMode('realtime')
      } catch (err) {
        console.error('[SlideLibrary] 실시간 모드 전환 실패:', err)
        setModelMode('idle')
      }
    } catch (err) {
      console.error('[SlideLibrary] 강의자료 로드 실패:', err)
    } finally {
      setLoading(false)
    }
  }

  const enterEdit = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (selectionMode || loading) return
    setDraftName(item.filename.replace(/\.pdf$/i, ''))
    setEditing(true)
  }

  const cancelEdit = () => {
    setDraftName(item.filename.replace(/\.pdf$/i, ''))
    setEditing(false)
  }

  const saveEdit = async () => {
    const trimmed = draftName.trim()
    if (!trimmed) {
      cancelEdit()
      return
    }
    // 동일하면 스킵
    if (trimmed === item.filename.replace(/\.pdf$/i, '')) {
      setEditing(false)
      return
    }
    setSavingName(true)
    try {
      const res = await renameSlide(item.slide_id, trimmed)
      onRenamed(item.slide_id, res.filename)
      setEditing(false)
    } catch (err) {
      console.error('[SlideLibrary] 이름 변경 실패:', err)
      alert(err instanceof Error ? err.message : '이름 변경 실패')
    } finally {
      setSavingName(false)
    }
  }

  const formatDate = (iso: string) => {
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

  const disabled = item.status !== 'completed'

  return (
    <div
      role="button"
      tabIndex={editing ? -1 : 0}
      onClick={handleCardClick}
      onKeyDown={(e) => {
        if (editing) return
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          handleCardClick()
        }
      }}
      className={`group flex items-center gap-3 p-3 bg-surface rounded-lg border transition-colors
        ${selected ? 'border-primary bg-primary/5' : 'border-primaryContainer hover:border-primary/50'}
        ${(disabled || loading) && !editing ? 'opacity-50 cursor-not-allowed' : editing ? '' : 'cursor-pointer'}`}
      aria-disabled={disabled || loading}
    >
      {selectionMode && (
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelect(item.slide_id)}
          onClick={(e) => e.stopPropagation()}
          className="w-4 h-4 accent-primary flex-shrink-0"
          aria-label={`${item.filename} 선택`}
        />
      )}

      <div className="flex-1 min-w-0">
        {editing ? (
          <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
            <svg className="w-4 h-4 flex-shrink-0 text-onSurface/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <input
              ref={inputRef}
              type="text"
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  saveEdit()
                } else if (e.key === 'Escape') {
                  e.preventDefault()
                  cancelEdit()
                }
              }}
              onBlur={saveEdit}
              disabled={savingName}
              maxLength={100}
              className="flex-1 min-w-0 bg-white border border-primaryContainer rounded px-2 py-1 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <span className="text-xs text-onSurface/50 flex-shrink-0">.pdf</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 min-w-0">
            <svg className="w-4 h-4 flex-shrink-0 text-onSurface/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <p className="font-medium text-sm text-onSurface truncate">{item.filename}</p>
          </div>
        )}
        <p className="text-xs text-onSurface/60 mt-0.5">
          {item.total_pages}페이지{item.uploaded_at && ` · ${formatDate(item.uploaded_at)}`}
          {item.status !== 'completed' && (
            <span className="ml-2 text-error">[{item.status}]</span>
          )}
        </p>
      </div>

      {!selectionMode && !editing && (
        <div className="flex items-center gap-0.5 flex-shrink-0">
          <button
            type="button"
            aria-label="미리보기"
            title="미리보기"
            onClick={(e) => {
              e.stopPropagation()
              if (item.status !== 'completed') return
              setShowPreview(true)
            }}
            disabled={item.status !== 'completed'}
            className="opacity-0 group-hover:opacity-100 p-1.5 text-onSurface/60 hover:text-onSurface hover:bg-primaryContainer/40 rounded transition-opacity disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
          </button>
          <button
            type="button"
            aria-label="이름 변경"
            title="이름 변경"
            onClick={enterEdit}
            className="opacity-0 group-hover:opacity-100 p-1.5 text-onSurface/60 hover:text-onSurface hover:bg-primaryContainer/40 rounded transition-opacity"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
          </button>
        </div>
      )}

      {showPreview && (
        <SlidePreviewModal
          slideId={item.slide_id}
          filename={item.filename}
          totalPages={item.total_pages}
          onClose={() => setShowPreview(false)}
        />
      )}
    </div>
  )
}
