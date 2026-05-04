import { useLectureStore } from '@/stores/lectureStore'

interface MaterialViewToggleProps {
  className?: string
  locale?: 'en' | 'ko'
}

function MaterialViewToggle({ className = '', locale = 'en' }: MaterialViewToggleProps) {
  const { materialMode, setMaterialMode } = useLectureStore()
  const toggle = () =>
    setMaterialMode(materialMode === 'original' ? 'translated' : 'original')

  const labels = locale === 'ko'
    ? { original: '원본', translated: '번역' }
    : { original: 'Original', translated: 'Translated' }

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
        {labels.original}
      </span>
      <span
        className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
          materialMode === 'translated'
            ? 'bg-primary text-onPrimary'
            : 'text-white/70'
        }`}
      >
        {labels.translated}
      </span>
    </button>
  )
}

export default MaterialViewToggle
