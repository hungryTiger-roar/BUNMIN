// 강의자료 라이브러리 관련 타입

export type SortOrder = 'recent' | 'name' | 'size'

export interface SlideLibraryItem {
  slide_id: string
  filename: string
  uploaded_at: string  // ISO 8601
  total_pages: number
  status: 'pending' | 'processing' | 'completed' | 'failed'
  has_translated: boolean
  file_size?: number  // bytes — 검색 모달 정렬/표시용 (백엔드가 제공)
}

export interface SlideLibraryResponse {
  items: SlideLibraryItem[]
}

export interface SlideLoadResponse {
  slide_id: string
  message: string
  total_pages: number
  last_page?: number  // 마지막 본 페이지 (1-indexed). 없으면 1로 시작.
}

export interface SlideDeleteResponse {
  slide_id: string
  message: string
  deleted_files: string[]
}

export interface SlideBatchDeleteFailure {
  slide_id: string
  reason: string
}

export interface SlideBatchDeleteResponse {
  deleted: string[]
  failed: SlideBatchDeleteFailure[]
}

export interface SlideRenameResponse {
  slide_id: string
  filename: string
}
