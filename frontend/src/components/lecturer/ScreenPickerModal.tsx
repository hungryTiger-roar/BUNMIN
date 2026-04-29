import { useMemo, useState } from 'react'

interface Props {
  sources: ScreenSource[]
  onSelect: (sourceId: string) => void
  onCancel: () => void
}

type Tab = 'screen' | 'window'

function ScreenPickerModal({ sources, onSelect, onCancel }: Props) {
  const [tab, setTab] = useState<Tab>('screen')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const { screens, windows } = useMemo(() => {
    const screens = sources.filter((s) => s.id.startsWith('screen:'))
    const windows = sources.filter((s) => s.id.startsWith('window:'))
    return { screens, windows }
  }, [sources])

  const list = tab === 'screen' ? screens : windows

  const confirm = () => {
    if (selectedId) onSelect(selectedId)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onCancel}
    >
      <div
        className="flex w-[720px] max-w-[90vw] flex-col rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">공유할 항목 선택</h2>
          <p className="mt-1 text-sm text-gray-500">
            전체 화면 또는 특정 창을 선택해 강의에 공유하세요.
          </p>
        </div>

        <div className="flex border-b">
          <button
            type="button"
            onClick={() => {
              setTab('screen')
              setSelectedId(null)
            }}
            className={`flex-1 px-4 py-3 text-sm font-medium transition ${
              tab === 'screen'
                ? 'border-b-2 border-blue-500 text-blue-600'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            전체 화면 ({screens.length})
          </button>
          <button
            type="button"
            onClick={() => {
              setTab('window')
              setSelectedId(null)
            }}
            className={`flex-1 px-4 py-3 text-sm font-medium transition ${
              tab === 'window'
                ? 'border-b-2 border-blue-500 text-blue-600'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            창 ({windows.length})
          </button>
        </div>

        <div className="grid max-h-[420px] grid-cols-2 gap-3 overflow-y-auto p-4">
          {list.length === 0 && (
            <div className="col-span-2 py-12 text-center text-sm text-gray-400">
              {tab === 'screen' ? '감지된 화면이 없습니다.' : '공유 가능한 창이 없습니다.'}
            </div>
          )}
          {list.map((src) => {
            const selected = selectedId === src.id
            return (
              <button
                key={src.id}
                type="button"
                onClick={() => setSelectedId(src.id)}
                onDoubleClick={() => onSelect(src.id)}
                className={`flex flex-col overflow-hidden rounded-md border-2 text-left transition ${
                  selected
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200 hover:border-gray-400'
                }`}
              >
                <div className="flex aspect-video items-center justify-center bg-gray-100">
                  <img
                    src={src.thumbnail}
                    alt={src.name}
                    className="max-h-full max-w-full object-contain"
                  />
                </div>
                <div className="flex items-center gap-2 px-3 py-2">
                  {src.appIcon && (
                    <img src={src.appIcon} alt="" className="h-4 w-4 flex-shrink-0" />
                  )}
                  <span className="truncate text-sm text-gray-800" title={src.name}>
                    {src.name}
                  </span>
                </div>
              </button>
            )
          })}
        </div>

        <div className="flex justify-end gap-2 border-t px-6 py-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
          >
            취소
          </button>
          <button
            type="button"
            onClick={confirm}
            disabled={!selectedId}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            공유
          </button>
        </div>
      </div>
    </div>
  )
}

export default ScreenPickerModal
