import { useState } from 'react'
import SlideLibrary from './SlideLibrary'
import UploadDropzone from './UploadDropzone'

/**
 * 강의자료 영역 — 좌우 2분할 컨테이너
 * - 좌측: 저장된 강의자료 라이브러리 (선택 시 즉시 불러오기)
 * - 우측: 새 PDF 업로드 드롭존
 *
 * `md` 미만 화면에서는 1단(세로) 배치로 폴백.
 */
export default function SlideUpload() {
  // 새 업로드 완료 시 라이브러리를 새로고침하기 위한 트리거
  const [refreshKey, setRefreshKey] = useState(0)

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 w-full">
      {/* 좌측: 라이브러리 */}
      <div className="md:border-r md:border-primaryContainer md:pr-4">
        <SlideLibrary refreshKey={refreshKey} />
      </div>
      {/* 우측: 새 업로드 (상시 노출) */}
      <div className="md:pl-0 flex flex-col">
        <h3 className="text-sm font-semibold text-onSurface mb-3 flex items-center gap-1.5">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          새 강의자료 업로드
        </h3>
        <UploadDropzone onUploadComplete={() => setRefreshKey((k) => k + 1)} />
      </div>
    </div>
  )
}
