import { useLectureStore } from '@/stores/lectureStore'

function ViewToggle() {
  const { viewMode, setViewMode } = useLectureStore()

  return (
    <div className="flex bg-white/15 rounded-lg p-1">
      <button
        onClick={() => setViewMode('original')}
        className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
          viewMode === 'original'
            ? 'bg-white text-gray-900'
            : 'text-onPrimary/70 hover:text-onPrimary'
        }`}
      >
        원본
      </button>
      <button
        onClick={() => setViewMode('translated')}
        className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
          viewMode === 'translated'
            ? 'bg-primary text-onPrimary'
            : 'text-onPrimary/70 hover:text-onPrimary'
        }`}
      >
        번역
      </button>
    </div>
  )
}

export default ViewToggle
