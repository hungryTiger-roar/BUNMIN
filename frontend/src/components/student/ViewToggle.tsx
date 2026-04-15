import { useLectureStore } from '@/stores/lectureStore'

function ViewToggle() {
  const { viewMode, setViewMode } = useLectureStore()

  return (
    <div className="flex bg-slate-700 rounded-lg p-1">
      <button
        onClick={() => setViewMode('original')}
        className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
          viewMode === 'original'
            ? 'bg-slate-600 text-white'
            : 'text-slate-400 hover:text-white'
        }`}
      >
        원본
      </button>
      <button
        onClick={() => setViewMode('translated')}
        className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
          viewMode === 'translated'
            ? 'bg-blue-500 text-white'
            : 'text-slate-400 hover:text-white'
        }`}
      >
        번역
      </button>
    </div>
  )
}

export default ViewToggle
