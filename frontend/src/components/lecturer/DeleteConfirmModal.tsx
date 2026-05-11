interface Props {
  count: number
  onConfirm: () => void
  onCancel: () => void
}

export default function DeleteConfirmModal({ count, onConfirm, onCancel }: Props) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={(e) => e.stopPropagation()}>
      <div className="bg-surface text-onSurface rounded-2xl shadow-2xl p-6 w-[min(90%,400px)] flex flex-col gap-4">
        <h3 className="text-lg font-semibold flex items-center gap-2">
          <svg className="w-5 h-5 text-error" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          강의자료 삭제
        </h3>

        <div className="space-y-1.5">
          <p className="text-sm">
            선택한 <span className="font-medium">{count}개</span>의 강의자료를 삭제하시겠습니까?
          </p>
          <p className="text-xs text-error flex items-center gap-1">
            <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            원본과 번역본이 모두 삭제됩니다.
          </p>
        </div>

        <div className="flex justify-end gap-2 mt-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 text-sm border border-primaryContainer rounded-lg hover:bg-primaryContainer/40 transition-colors"
          >
            취소
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-4 py-2 text-sm bg-error text-white rounded-lg hover:opacity-90 transition-opacity"
          >
            삭제
          </button>
        </div>
      </div>
    </div>
  )
}
