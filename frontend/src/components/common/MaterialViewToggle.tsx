import { useLectureStore } from '@/stores/lectureStore'

interface MaterialViewToggleProps {
  className?: string
}

function MaterialViewToggle({ className = '' }: MaterialViewToggleProps) {
  const materialMode = useLectureStore((s) => s.materialMode)
  const setMaterialMode = useLectureStore((s) => s.setMaterialMode)
  const toggle = () =>
    setMaterialMode(materialMode === 'original' ? 'translated' : 'original')

  return (
    <button
      type="button"
      onClick={toggle}
      className={`flex bg-black/40 backdrop-blur-sm rounded-lg p-1 shadow-lg hover:bg-black/50 transition-colors ${className}`}
    >
      <span
        className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
          materialMode === 'original'
            ? 'bg-white text-gray-900'
            : 'text-white/70'
        }`}
      >
        원본
      </span>
      <span
        className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
          materialMode === 'translated'
            ? 'bg-primary text-onPrimary'
            : 'text-white/70'
        }`}
      >
        번역
      </span>
    </button>
  )
}

export default MaterialViewToggle
