import { useState } from 'react'
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

interface FileQueueModalProps {
  files: File[]
  onConfirm: (orderedFiles: File[]) => void
  onCancel: () => void
}

interface FileItemProps {
  id: string
  file: File
  index: number
  onRemove: (id: string) => void
}

function SortableFileItem({ id, file, index, onRemove }: FileItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="flex items-center gap-3 p-3 bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg mb-2 shadow-sm"
    >
      {/* 드래그 핸들 */}
      <button
        {...attributes}
        {...listeners}
        className="cursor-grab active:cursor-grabbing p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8h16M4 16h16" />
        </svg>
      </button>

      {/* 순서 번호 */}
      <span className="w-6 h-6 flex items-center justify-center text-xs font-medium bg-blue-600 text-white rounded-full flex-shrink-0">
        {index + 1}
      </span>

      {/* 파일 정보 */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 dark:text-white truncate" title={file.name}>
          {file.name}
        </p>
        <p className="text-xs text-gray-500 dark:text-gray-400">{formatSize(file.size)}</p>
      </div>

      {/* 삭제 버튼 */}
      <button
        onClick={() => onRemove(id)}
        className="p-1 text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  )
}

export default function FileQueueModal({ files, onConfirm, onCancel }: FileQueueModalProps) {
  // 파일 ID 부여 (드래그 정렬용)
  const [items, setItems] = useState(() =>
    files.map((file, i) => ({ id: `file-${i}-${file.name}`, file }))
  )

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  )

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (over && active.id !== over.id) {
      setItems((prev) => {
        const oldIndex = prev.findIndex((item) => item.id === active.id)
        const newIndex = prev.findIndex((item) => item.id === over.id)
        return arrayMove(prev, oldIndex, newIndex)
      })
    }
  }

  const handleRemove = (id: string) => {
    setItems((prev) => prev.filter((item) => item.id !== id))
  }

  const handleConfirm = () => {
    onConfirm(items.map((item) => item.file))
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-md mx-4 max-h-[80vh] flex flex-col border border-gray-200 dark:border-gray-700">
        {/* 헤더 */}
        <div className="p-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">업로드 순서 설정</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            드래그하여 처리 순서를 변경하세요
          </p>
        </div>

        {/* 파일 목록 */}
        <div className="flex-1 overflow-y-auto p-4 bg-gray-50 dark:bg-gray-900">
          {items.length === 0 ? (
            <p className="text-center text-gray-400 py-8">파일이 없습니다</p>
          ) : (
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <SortableContext items={items.map((i) => i.id)} strategy={verticalListSortingStrategy}>
                {items.map((item, index) => (
                  <SortableFileItem
                    key={item.id}
                    id={item.id}
                    file={item.file}
                    index={index}
                    onRemove={handleRemove}
                  />
                ))}
              </SortableContext>
            </DndContext>
          )}
        </div>

        {/* 푸터 */}
        <div className="p-4 border-t border-gray-200 dark:border-gray-700 flex gap-3 bg-white dark:bg-gray-800">
          <button
            onClick={onCancel}
            className="flex-1 py-2.5 text-sm font-medium text-gray-700 dark:text-gray-200 bg-gray-100 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
          >
            취소
          </button>
          <button
            onClick={handleConfirm}
            disabled={items.length === 0}
            className="flex-1 py-2.5 text-sm font-medium text-white bg-primary rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            처리 시작 ({items.length}개)
          </button>
        </div>
      </div>
    </div>
  )
}
