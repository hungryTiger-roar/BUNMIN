# 강의자료 라이브러리 - 프론트엔드 설계

## 개요

강의자가 사전에 업로드/처리한 강의자료를 목록에서 선택하여 강의를 시작할 수 있게 함.

## 현재 문제점

- 강의 시작 시 매번 PDF 업로드 필요
- 기존 처리된 자료 재사용 불가
- 자료 관리(삭제) 기능 없음

---

## UI 설계

### 변경 전

```
┌─────────────────────────────┐
│                             │
│  ☁️ PDF 파일을 드래그하거나  │
│       클릭하세요            │
│                             │
│  업로드 즉시 번역이 시작됩니다 │
└─────────────────────────────┘
```

### 변경 후 (좌우 2분할 레이아웃)

화면을 절반으로 나눠 **왼쪽은 기존 라이브러리**, **오른쪽은 새 업로드 영역**으로 구성한다.

```
┌──────────────────────────────────────────────┬───────────────────────────────────────┐
│  📚 강의자료 라이브러리       [최신순][이름순] ⋮│  ＋ 새 강의자료 업로드                  │
├──────────────────────────────────────────────┤                                       │
│  ┌────────────────────────────────────────┐  │  ┌─────────────────────────────────┐  │
│  │ 📄 알고리즘_강의.pdf                    │  │  │                                 │  │
│  │    15페이지 · 2025.04.29                │  │  │  ☁️ PDF 파일을 드래그하거나      │  │
│  └────────────────────────────────────────┘  │  │       클릭하세요                 │  │
│  ┌────────────────────────────────────────┐  │  │                                 │  │
│  │ 📄 자료구조_1장.pdf                     │  │  │  업로드 즉시 번역이 시작됩니다    │  │
│  │    8페이지 · 2025.04.28                 │  │  │                                 │  │
│  └────────────────────────────────────────┘  │  └─────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │                                       │
│  │ 📄 운영체제_2장.pdf                     │  │                                       │
│  │    12페이지 · 2025.04.27                │  │                                       │
│  └────────────────────────────────────────┘  │                                       │
│  (기본 3개 노출, 초과 시 ▼ 스크롤)            │                                       │
└──────────────────────────────────────────────┴───────────────────────────────────────┘
```

- **클릭 동작**: 라이브러리의 PDF 카드를 누르면 **무조건 "불러오기"** 가 실행된다 (별도 버튼 없음).
- 평상시에는 카드 위에 `불러오기` / `🗑️ 삭제` 버튼을 표시하지 않는다 (간결한 목록 뷰).

### 정렬 / 선택 모드 진입 (⋮ 메뉴)

라이브러리 헤더 우측 영역:

```
[ 최신순 ]  [ 이름순 ]  ⋮
                       │
                       ▼ (드롭다운)
                 ┌─────────────┐
                 │ 🗑️ 삭제      │  ← 클릭 시 선택 모드 진입
                 └─────────────┘
```

- **기본 정렬**: 최신순 (`uploaded_at desc`)
- **이름순**: 파일명 오름차순 (`filename asc`, `localeCompare('ko')`)
- 활성 정렬 버튼은 강조 스타일(예: `bg-primary/10 text-primary`).

### 선택 모드 (다중 삭제)

`⋮` 메뉴에서 `삭제`를 선택하면 선택 모드로 진입하여 각 항목 좌측에 빈 체크박스가 표시된다.

```
┌──────────────────────────────────────────────┐
│  📚 강의자료 라이브러리         [취소] [🗑️ 삭제(2)] │
├──────────────────────────────────────────────┤
│  ┌────────────────────────────────────────┐  │
│  │ ☑ 📄 알고리즘_강의.pdf                  │  │
│  │      15페이지 · 2025.04.29              │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │ ☐ 📄 자료구조_1장.pdf                   │  │
│  │      8페이지 · 2025.04.28               │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │ ☑ 📄 운영체제_2장.pdf                   │  │
│  │      12페이지 · 2025.04.27              │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

- 선택 모드에서는 카드 클릭이 "체크 토글"로 동작 (불러오기 비활성화).
- 우측 상단 `🗑️ 삭제(N)` 버튼: 선택된 N개를 일괄 삭제 (모달 확인 후).
- `취소` 버튼: 선택 모드 해제.
- 정렬(`최신순`/`이름순`) 버튼은 선택 모드에서도 사용 가능.

### 빈 상태 (저장된 자료 없음)

좌측 패널만 빈 상태로 표시되고, 우측 업로드 패널은 그대로 유지된다.

```
┌──────────────────────────────────────────────┬───────────────────────────────────────┐
│  📚 강의자료 라이브러리                        │  ＋ 새 강의자료 업로드                  │
├──────────────────────────────────────────────┤                                       │
│                                              │  ┌─────────────────────────────────┐  │
│         저장된 강의자료가 없습니다              │  │  ☁️ PDF 파일을 드래그하거나      │  │
│                                              │  │       클릭하세요                 │  │
│                                              │  └─────────────────────────────────┘  │
└──────────────────────────────────────────────┴───────────────────────────────────────┘
```

### 일괄 삭제 확인 모달

```
┌─────────────────────────────────────┐
│  ⚠️ 강의자료 삭제                    │
├─────────────────────────────────────┤
│                                     │
│  선택한 2개의 강의자료를              │
│  삭제하시겠습니까?                   │
│                                     │
│  ⚠️ 원본과 번역본이 모두 삭제됩니다.  │
│                                     │
│         [취소]     [삭제]            │
│                                     │
└─────────────────────────────────────┘
```

---

## 컴포넌트 구조

```
components/lecturer/
├── SlideUpload.tsx            (기존, 수정)
│   └── 좌우 2분할 컨테이너 (좌: SlideLibrary / 우: UploadDropzone)
│
├── SlideLibrary.tsx           (신규)
│   ├── 헤더 (제목 + 정렬 버튼 + ⋮ 더보기 / 선택 모드 액션바)
│   ├── 라이브러리 목록 (기본 3개 노출, 초과 시 스크롤)
│   └── 정렬/선택 상태 관리
│
├── SlideLibraryItem.tsx       (신규)
│   ├── 개별 강의자료 카드 (파일명 + 페이지수 + 업로드일)
│   ├── 일반 모드: 카드 클릭 → 불러오기
│   └── 선택 모드: 좌측 체크박스 + 카드 클릭 → 토글
│
├── LibraryMoreMenu.tsx        (신규)
│   └── ⋮ 드롭다운 (현재는 "삭제" 항목만)
│
├── UploadDropzone.tsx         (신규, 기존 로직 분리)
│   └── 드래그앤드롭 업로드 영역 (오른쪽 패널 상시 노출)
│
└── DeleteConfirmModal.tsx     (신규)
    └── 일괄 삭제 확인 다이얼로그 (선택 개수 표시)
```

---

## 타입 정의

```typescript
// types/slide.ts

export type SortOrder = 'recent' | 'name'

export interface SlideLibraryItem {
  slide_id: string
  filename: string
  uploaded_at: string  // ISO 8601
  total_pages: number
  status: 'pending' | 'processing' | 'completed' | 'failed'
  has_translated: boolean
}

export interface SlideLibraryResponse {
  items: SlideLibraryItem[]
}

export interface SlideLoadResponse {
  slide_id: string
  message: string
  total_pages: number
}

export interface SlideDeleteResponse {
  slide_id: string
  message: string
  deleted_files: string[]
}

export interface SlideBatchDeleteResponse {
  deleted: string[]
  failed: { slide_id: string; reason: string }[]
}
```

---

## API 함수

```typescript
// lib/api.ts

export async function getSlideLibrary(): Promise<SlideLibraryResponse> {
  const res = await fetch(`${API_BASE}/slides/library`)
  if (!res.ok) throw new Error('라이브러리 조회 실패')
  return res.json()
}

export async function loadSlide(slideId: string): Promise<SlideLoadResponse> {
  const res = await fetch(`${API_BASE}/slides/load/${slideId}`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('강의자료 로드 실패')
  return res.json()
}

// 단건 삭제 (호환성 유지용, UI에서 직접 호출하지 않음)
export async function deleteSlide(slideId: string): Promise<SlideDeleteResponse> {
  const res = await fetch(`${API_BASE}/slides/delete/${slideId}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error('강의자료 삭제 실패')
  return res.json()
}

// 일괄 삭제 (선택 모드에서 사용)
export async function deleteSlidesBatch(
  slideIds: string[]
): Promise<SlideBatchDeleteResponse> {
  const res = await fetch(`${API_BASE}/slides/delete-batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slide_ids: slideIds }),
  })
  if (!res.ok) throw new Error('강의자료 일괄 삭제 실패')
  return res.json()
}
```

---

## 컴포넌트 상세

### SlideUpload.tsx (좌우 2분할 컨테이너)

```tsx
import SlideLibrary from './SlideLibrary'
import UploadDropzone from './UploadDropzone'

export default function SlideUpload() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 h-full">
      {/* 왼쪽: 라이브러리 */}
      <div className="border-r border-outline/20 pr-4">
        <SlideLibrary />
      </div>
      {/* 오른쪽: 새 업로드 (상시 노출) */}
      <div className="pl-4">
        <UploadDropzone />
      </div>
    </div>
  )
}
```

### SlideLibrary.tsx

```tsx
import { useEffect, useMemo, useState } from 'react'
import { getSlideLibrary, deleteSlidesBatch } from '@/lib/api'
import type { SlideLibraryItem as Item, SortOrder } from '@/types/slide'
import SlideLibraryItem from './SlideLibraryItem'
import LibraryMoreMenu from './LibraryMoreMenu'
import DeleteConfirmModal from './DeleteConfirmModal'

// 기본 3개 노출 → 카드 1개 높이를 약 72px로 가정 (p-3 + 텍스트 2줄)
const VISIBLE_ITEM_HEIGHT = 72
const VISIBLE_COUNT = 3

export default function SlideLibrary() {
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(true)
  const [sortOrder, setSortOrder] = useState<SortOrder>('recent')
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [showDeleteModal, setShowDeleteModal] = useState(false)

  useEffect(() => {
    loadLibrary()
  }, [])

  const loadLibrary = async () => {
    try {
      const data = await getSlideLibrary()
      setItems(data.items)
    } catch (err) {
      console.error('라이브러리 로드 실패:', err)
    } finally {
      setLoading(false)
    }
  }

  // 정렬: 기본 최신순
  const sortedItems = useMemo(() => {
    const arr = [...items]
    if (sortOrder === 'recent') {
      arr.sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at))
    } else {
      arr.sort((a, b) => a.filename.localeCompare(b.filename, 'ko'))
    }
    return arr
  }, [items, sortOrder])

  const toggleSelect = (slideId: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(slideId)) next.delete(slideId)
      else next.add(slideId)
      return next
    })
  }

  const enterSelectionMode = () => {
    setSelectionMode(true)
    setSelectedIds(new Set())
  }

  const exitSelectionMode = () => {
    setSelectionMode(false)
    setSelectedIds(new Set())
  }

  const handleBatchDelete = async () => {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) return
    try {
      await deleteSlidesBatch(ids)
      setItems(prev => prev.filter(item => !selectedIds.has(item.slide_id)))
    } catch (err) {
      console.error('일괄 삭제 실패:', err)
    } finally {
      setShowDeleteModal(false)
      exitSelectionMode()
    }
  }

  if (loading) return <div>로딩 중...</div>

  return (
    <div className="flex flex-col h-full">
      {/* 헤더: 제목 + 정렬 + ⋮ / 선택 모드 액션바 */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold">📚 강의자료 라이브러리</h3>

        {!selectionMode ? (
          <div className="flex items-center gap-1">
            <button
              onClick={() => setSortOrder('recent')}
              className={`px-2 py-1 text-xs rounded ${
                sortOrder === 'recent'
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-gray-500 hover:bg-surface-variant'
              }`}
            >
              최신순
            </button>
            <button
              onClick={() => setSortOrder('name')}
              className={`px-2 py-1 text-xs rounded ${
                sortOrder === 'name'
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-gray-500 hover:bg-surface-variant'
              }`}
            >
              이름순
            </button>
            <LibraryMoreMenu onSelectDelete={enterSelectionMode} />
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSortOrder('recent')}
              className={`px-2 py-1 text-xs rounded ${
                sortOrder === 'recent' ? 'bg-primary/10 text-primary' : 'text-gray-500'
              }`}
            >
              최신순
            </button>
            <button
              onClick={() => setSortOrder('name')}
              className={`px-2 py-1 text-xs rounded ${
                sortOrder === 'name' ? 'bg-primary/10 text-primary' : 'text-gray-500'
              }`}
            >
              이름순
            </button>
            <button
              onClick={exitSelectionMode}
              className="px-2 py-1 text-xs border border-outline rounded"
            >
              취소
            </button>
            <button
              onClick={() => setShowDeleteModal(true)}
              disabled={selectedIds.size === 0}
              className="px-2 py-1 text-xs bg-error text-white rounded disabled:opacity-40"
            >
              🗑️ 삭제({selectedIds.size})
            </button>
          </div>
        )}
      </div>

      {/* 목록: 기본 3개 노출, 초과 시 스크롤 */}
      {sortedItems.length > 0 ? (
        <div
          className="space-y-2 overflow-y-auto pr-1"
          style={{ maxHeight: `${VISIBLE_ITEM_HEIGHT * VISIBLE_COUNT}px` }}
        >
          {sortedItems.map(item => (
            <SlideLibraryItem
              key={item.slide_id}
              item={item}
              selectionMode={selectionMode}
              selected={selectedIds.has(item.slide_id)}
              onToggleSelect={toggleSelect}
            />
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-500 text-center py-8">
          저장된 강의자료가 없습니다
        </p>
      )}

      {showDeleteModal && (
        <DeleteConfirmModal
          count={selectedIds.size}
          onConfirm={handleBatchDelete}
          onCancel={() => setShowDeleteModal(false)}
        />
      )}
    </div>
  )
}
```

### SlideLibraryItem.tsx

```tsx
import { useState } from 'react'
import { loadSlide } from '@/lib/api'
import type { SlideLibraryItem as Item } from '@/types/slide'
import { useLectureStore } from '@/stores/lectureStore'

interface Props {
  item: Item
  selectionMode: boolean
  selected: boolean
  onToggleSelect: (slideId: string) => void
}

export default function SlideLibraryItem({
  item,
  selectionMode,
  selected,
  onToggleSelect,
}: Props) {
  const [loading, setLoading] = useState(false)
  const { setSlideId, setSlideStatus } = useLectureStore()

  const handleCardClick = async () => {
    // 선택 모드: 카드 클릭 = 체크박스 토글
    if (selectionMode) {
      onToggleSelect(item.slide_id)
      return
    }
    // 일반 모드: 카드 클릭 = 무조건 불러오기
    if (item.status !== 'completed') return
    setLoading(true)
    try {
      await loadSlide(item.slide_id)
      setSlideId(item.slide_id)
      setSlideStatus('ready')
    } catch (err) {
      console.error('로드 실패:', err)
    } finally {
      setLoading(false)
    }
  }

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    })

  return (
    <div
      role="button"
      onClick={handleCardClick}
      className={`flex items-center gap-3 p-3 bg-surface rounded-lg
                  border border-outline/20 cursor-pointer
                  hover:border-primary/50 transition-colors
                  ${selected ? 'border-primary bg-primary/5' : ''}
                  ${loading ? 'opacity-50 pointer-events-none' : ''}`}
    >
      {selectionMode && (
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelect(item.slide_id)}
          onClick={e => e.stopPropagation()}
          className="w-4 h-4 accent-primary"
        />
      )}

      <div className="flex-1 min-w-0">
        <p className="font-medium truncate">📄 {item.filename}</p>
        <p className="text-xs text-gray-500">
          {item.total_pages}페이지 · {formatDate(item.uploaded_at)}
        </p>
      </div>

      {/* 일반 모드에서도 개별 액션 버튼은 노출하지 않음 (요구사항) */}
    </div>
  )
}
```

### LibraryMoreMenu.tsx

```tsx
import { useEffect, useRef, useState } from 'react'

interface Props {
  onSelectDelete: () => void
}

export default function LibraryMoreMenu({ onSelectDelete }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div ref={ref} className="relative">
      <button
        aria-label="더보기"
        onClick={() => setOpen(o => !o)}
        className="px-2 py-1 text-gray-500 hover:bg-surface-variant rounded"
      >
        ⋮
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-32 bg-surface border border-outline/20
                        rounded shadow-md z-10">
          <button
            onClick={() => {
              setOpen(false)
              onSelectDelete()
            }}
            className="w-full text-left px-3 py-2 text-sm hover:bg-surface-variant"
          >
            🗑️ 삭제
          </button>
        </div>
      )}
    </div>
  )
}
```

### DeleteConfirmModal.tsx

```tsx
interface Props {
  count: number
  onConfirm: () => void
  onCancel: () => void
}

export default function DeleteConfirmModal({ count, onConfirm, onCancel }: Props) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-surface rounded-lg p-6 max-w-sm w-full mx-4 shadow-xl">
        <h3 className="text-lg font-semibold mb-4">⚠️ 강의자료 삭제</h3>

        <p className="text-sm mb-2">
          선택한 <span className="font-medium">{count}개</span>의 강의자료를 삭제하시겠습니까?
        </p>

        <p className="text-xs text-error mb-6">
          ⚠️ 원본과 번역본이 모두 삭제됩니다.
        </p>

        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm border border-outline rounded
                       hover:bg-surface-variant"
          >
            취소
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm bg-error text-white rounded
                       hover:bg-error/90"
          >
            삭제
          </button>
        </div>
      </div>
    </div>
  )
}
```

---

## 상태 관리

### lectureStore 수정

```typescript
// stores/lectureStore.ts

interface LectureState {
  // 기존
  slideId: string | null
  slideStatus: 'none' | 'uploading' | 'processing' | 'ready'

  // 신규
  libraryLoaded: boolean

  // 액션
  setSlideId: (id: string | null) => void
  setSlideStatus: (status: SlideStatus) => void
  resetSlide: () => void
}
```

라이브러리 컴포넌트 내부 상태(정렬/선택)는 `SlideLibrary` 로컬 state로 관리한다.

---

## 사용자 플로우

### 1. 기존 자료로 강의 시작 (PDF 카드 클릭 = 불러오기)

```
1. 강의자 페이지 진입
2. 좌우 2분할 레이아웃 렌더링 (좌: SlideLibrary / 우: UploadDropzone 상시 노출)
3. GET /slides/library 호출 (기본 최신순 정렬)
4. 라이브러리 카드 클릭
5. POST /slides/load/{id} 호출
6. slideId, slideStatus 업데이트
7. 슬라이드 뷰어 표시 → 강의 시작 가능
```

### 2. 새 자료 업로드 (오른쪽 패널)

```
1. 우측 UploadDropzone에 PDF 드래그/선택
2. POST /slides/upload 호출
3. 처리 상태 폴링
4. 완료 시 좌측 라이브러리 새로고침
5. 새 자료가 (최신순 기준) 목록 상단에 표시
```

### 3. 자료 정렬

```
1. 헤더의 [최신순] / [이름순] 버튼 클릭
2. 목록 즉시 재정렬 (클라이언트 정렬, 서버 호출 없음)
```

### 4. 자료 다중 삭제

```
1. ⋮ 더보기 → "🗑️ 삭제" 클릭 → 선택 모드 진입
2. 각 카드 좌측 체크박스 표시 (또는 카드 클릭으로 토글)
3. 여러 항목 선택
4. 우측 상단 "🗑️ 삭제(N)" 버튼 클릭
5. DeleteConfirmModal 표시 → "삭제" 확인
6. POST /slides/delete-batch (body: {slide_ids})
7. 목록에서 제거 + 선택 모드 해제
```

---

## 스타일 가이드

### 레이아웃

| 요소 | 스타일 |
|-----|------|
| 좌우 분할 컨테이너 | `grid grid-cols-1 md:grid-cols-2 gap-4` |
| 좌측 패널 구분선 | `border-r border-outline/20 pr-4` |
| 우측 패널 패딩 | `pl-4` |

### 색상

| 요소 | 색상 |
|-----|------|
| 활성 정렬 버튼 | `bg-primary/10 text-primary` |
| 일괄 삭제 버튼 | `bg-error text-white` |
| 선택된 카드 | `border-primary bg-primary/5` |
| 카드 배경 | `bg-surface` |
| 카드 테두리 | `border-outline/20` (hover 시 `border-primary/50`) |

### 간격 / 크기

- 카드 간 간격: `space-y-2`
- 카드 내부 패딩: `p-3`
- 라이브러리 목록 최대 높이: **카드 3개분** (`max-h: 72px × 3 = 216px`), 초과 시 `overflow-y-auto`
- 모달 최대 너비: `max-w-sm`

### 반응형

- `md` 미만: 1단(세로) 배치 — 라이브러리 위, 업로드 아래
- `md` 이상: 2단(가로) 배치 — 좌우 절반 분할

---

## 테스트 체크리스트

- [ ] 좌우 2분할 레이아웃 정상 렌더 (md 이상)
- [ ] 모바일/좁은 화면에서 1단 폴백 동작
- [ ] 라이브러리 기본 3개 노출, 4번째부터 스크롤 발생
- [ ] 기본 정렬이 최신순
- [ ] 이름순 클릭 시 한글 정렬 동작
- [ ] 일반 모드에서 카드 클릭 = 불러오기
- [ ] 일반 모드에서 개별 삭제/불러오기 버튼 미노출
- [ ] ⋮ 메뉴 → "삭제" 클릭 시 선택 모드 진입
- [ ] 선택 모드에서 체크박스 토글 동작
- [ ] 선택 모드에서 카드 클릭 = 체크 토글 (불러오기 미실행)
- [ ] 일괄 삭제 버튼 disabled (선택 0개)
- [ ] 일괄 삭제 확인 모달 표시 및 N개 표기
- [ ] 일괄 삭제 후 목록 갱신 + 선택 모드 자동 해제
- [ ] 새 업로드 후 라이브러리 자동 새로고침
- [ ] 처리 중(`status !== 'completed'`)인 자료 클릭 시 불러오기 미실행
- [ ] 빈 상태 메시지 표시
- [ ] 로딩 / 에러 상태 표시
