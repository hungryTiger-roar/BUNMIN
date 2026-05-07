# Student 페이지 모바일 반응형 설계

> **버전**: v2.0
> **최종 수정**: 2025-05-07
> **상태**: 구현 완료

---

## 1. 현재 구조 분석

### 1.1 기존 반응형 로직
```tsx
// Student.tsx:221-222
const [isNarrow, setIsNarrow] = useState(() => window.innerWidth < 1000)
const [sidebarOpen, setSidebarOpen] = useState(false)

// Student.tsx:314-322
useEffect(() => {
  const onResize = () => {
    const narrow = window.innerWidth < 1000
    setIsNarrow(narrow)
    setSidebarOpen(!narrow)  // 문제: 사용자 의도 무시
  }
  window.addEventListener('resize', onResize)
  return () => window.removeEventListener('resize', onResize)
}, [])
```

### 1.2 기존 문제점
| 문제 | 설명 |
|------|------|
| **width만 체크** | height 체크 없음 → 일반 스마트폰 가로모드(width 800+, height 360)에서도 사이드바 표시 |
| **브레이크포인트 1000px** | 태블릿/폴드 외부화면에서 애매한 동작 |
| **우측 슬라이드 방식** | 모바일에서 손가락 접근성 나쁨, 가로모드에서 슬라이드 영역 좁아짐 |
| **레이아웃 재계산** | 사이드바 열면 슬라이드 영역이 줄어듦 → 시청 중 화면 흔들림 |
| **사용자 의도 무시** | `setSidebarOpen(!narrow)` → 사용자가 닫았어도 resize 시 다시 열림 |

### 1.3 현재 사이드바 컴포넌트 구성
```
aside (w-80, 320px)
├── Today's lecture material (강의 시작 후에만)
│   ├── Header
│   └── Material list (다운로드 버튼)
│
└── Chat panel
    ├── Header
    ├── Messages scroll area
    ├── Input form
    └── ParticipantsPanel (overlay) ← absolute/fixed 스타일 결합, 분리 필요
```

---

## 2. 새로운 레이아웃 설계

### 2.1 브레이크포인트 기준

```ts
// 상수 정의 (한 곳에서 관리)
export const WIDE_MIN_WIDTH = 900
export const WIDE_MIN_HEIGHT = 500
export const WIDE_MEDIA_QUERY =
  `(min-width: ${WIDE_MIN_WIDTH}px) and (min-height: ${WIDE_MIN_HEIGHT}px)`
```

```css
/* Compact Layout (모바일) - 기본값 */

/* Wide Layout (태블릿/데스크톱) */
@media (min-width: 900px) and (min-height: 500px) {
  /* 오른쪽 사이드바 표시 */
}
```

**기준 근거:**
- 일반 스마트폰 가로모드: width 800~900px, height 360~430px → **Compact**
- 갤럭시 폴드 외부: width ~717px → **Compact**
- 갤럭시 폴드 내부: CSS viewport 기준 Wide 조건 만족 시 → **Wide**
- 태블릿 가로: width 1024+, height 600+ → **Wide**

> **주의**: 폴더블 기기는 물리 픽셀이 아닌 **실제 CSS viewport 기준** (`window.innerWidth`, `window.innerHeight`)으로 판단합니다.

### 2.2 레이아웃 전환 정책

```text
Wide: DesktopSidebar 상시 표시, panelOpen 무시
Compact: panelOpen으로 BottomSheet 열림/닫힘 관리
모드 전환 시 panelOpen은 false로 초기화
```

### 2.3 레이아웃 비교

#### Compact Layout (모바일)
```
┌────────────────────────────────────┐
│              Header                │
├────────────────────────────────────┤
│                                    │
│                                    │
│         강의자료 (100%)             │
│                                    │
│                           [💬]     │  ← 플로팅 버튼 (safe-area 고려)
│                                    │
└────────────────────────────────────┘
                 ↓ 버튼 클릭
┌────────────────────────────────────┐
│              Header                │
├────────────────────────────────────┤
│         강의자료 (100%)             │  ← 크기 변화 없음 (오버레이)
├────────────────────────────────────┤
│ ────────────────────────────────── │  ← 드래그 핸들
│ [채팅] [참여자] [자료]              │  ← 탭
│                                    │
│        Bottom Sheet 내용            │
│        (키보드 대응 필수)           │
└────────────────────────────────────┘
```

#### Wide Layout (태블릿/데스크톱)
```
┌──────────────────────────────────────────────────────┐
│                       Header                         │
├──────────────────────────────────────────────────────┤
│                                    │                 │
│                                    │    오른쪽       │
│         강의자료 (flex-1)           │    사이드바     │
│                                    │    (320px)     │
│                                    │                 │
└──────────────────────────────────────────────────────┘
```

---

## 3. 컴포넌트 구조 설계

### 3.1 새로운 컴포넌트 트리
```
Student.tsx
├── Header
├── LectureStage (슬라이드/화면공유 영역)
│
├── [Wide] DesktopSidebar
│   └── PanelContent
│
└── [Compact]
    ├── FloatingPanelButton (wrapper로 감싸서 wide:hidden 적용)
    └── MobileBottomSheet
        └── PanelContent
```

### 3.2 컴포넌트 분리 원칙 (기존 결합 해소)

**기존 문제**: `ChatPanel` 안에 `ParticipantsPanel overlay`가 강하게 묶여 있음
→ `absolute`, `fixed`, `z-index` 스타일이 ParticipantsPanel에 직접 들어가 있으면 탭 안에서 깨짐

**새 구조**:
```
ChatPanel
├── 채팅 메시지 리스트
├── 입력창
└── 참여자 버튼 없음 (탭으로 분리)

ParticipantsPanel (순수 목록 컴포넌트로 변경)
└── 참여자 목록만 담당
└── absolute/fixed/z-index 제거 → 부모가 필요시 감싸서 처리

MaterialsPanel
└── 자료 목록만 담당
└── Empty state 포함: "등록된 자료가 없습니다."

PanelContent
└── 탭 전환만 담당 (Chat/Participants/Materials 컨테이너)
└── 상태 보정 로직 없음 (상위에서 처리)
```

### 3.3 새로운 컴포넌트 목록

| 컴포넌트 | 파일 | 역할 |
|----------|------|------|
| `useResponsiveLayout` | `hooks/useResponsiveLayout.ts` | matchMedia 기반 레이아웃 모드 판단 |
| `PanelTabs` | `components/student/PanelTabs.tsx` | 채팅/참여자/자료 탭 UI |
| `PanelContent` | `components/student/PanelContent.tsx` | 탭별 콘텐츠 컨테이너 |
| `ChatPanel` | `components/student/ChatPanel.tsx` | 채팅 전용 (분리) |
| `MaterialsPanel` | `components/student/MaterialsPanel.tsx` | 자료 전용 (분리) |
| `FloatingPanelButton` | `components/student/FloatingPanelButton.tsx` | 모바일 플로팅 버튼 |
| `MobileBottomSheet` | `components/student/MobileBottomSheet.tsx` | 모바일 하단 시트 |
| `DesktopSidebar` | `components/student/DesktopSidebar.tsx` | 데스크톱 오른쪽 사이드바 |

---

## 4. 상세 설계

### 4.1 useResponsiveLayout Hook

```tsx
// hooks/useResponsiveLayout.ts
import { useState, useEffect } from 'react'

export const WIDE_MIN_WIDTH = 900
export const WIDE_MIN_HEIGHT = 500
export const WIDE_MEDIA_QUERY =
  `(min-width: ${WIDE_MIN_WIDTH}px) and (min-height: ${WIDE_MIN_HEIGHT}px)`

type LayoutMode = 'compact' | 'wide'

interface LayoutState {
  mode: LayoutMode
  isWide: boolean
  isCompact: boolean
}

export function useResponsiveLayout(): LayoutState {
  const [mode, setMode] = useState<LayoutMode>(() => getLayoutMode())

  useEffect(() => {
    const handleChange = () => {
      const nextMode = getLayoutMode()
      // 동일 모드면 setState 생략 (불필요한 리렌더링 방지)
      setMode(prev => (prev === nextMode ? prev : nextMode))
    }

    const mediaQuery = window.matchMedia(WIDE_MEDIA_QUERY)

    // resize + orientationchange + matchMedia 모두 감지
    window.addEventListener('resize', handleChange)
    window.addEventListener('orientationchange', handleChange)
    mediaQuery.addEventListener('change', handleChange)

    // 초기 렌더 후 실제 viewport 기준으로 한 번 더 체크
    handleChange()

    return () => {
      window.removeEventListener('resize', handleChange)
      window.removeEventListener('orientationchange', handleChange)
      mediaQuery.removeEventListener('change', handleChange)
    }
  }, [])

  return {
    mode,
    isWide: mode === 'wide',
    isCompact: mode === 'compact',
  }
}

function getLayoutMode(): LayoutMode {
  // SSR 안전성
  if (typeof window === 'undefined') return 'compact'

  // matchMedia 기반 (CSS media query와 동일 기준)
  return window.matchMedia(WIDE_MEDIA_QUERY).matches ? 'wide' : 'compact'
}
```

### 4.2 MobileBottomSheet 컴포넌트

```tsx
// components/student/MobileBottomSheet.tsx
import { useEffect } from 'react'

interface MobileBottomSheetProps {
  isOpen: boolean
  onClose: () => void
  children: React.ReactNode
}

function MobileBottomSheet({ isOpen, onClose, children }: MobileBottomSheetProps) {
  // ESC 키로 닫기
  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  return (
    <>
      {/* 백드롭 - z-50 */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-50"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* 시트 - z-60 */}
      <div
        role="dialog"
        aria-modal={isOpen ? 'true' : undefined}
        aria-hidden={!isOpen}
        aria-label="Lecture panel"
        className={`
          mobile-bottom-sheet
          fixed left-0 right-0 bottom-0 z-60
          flex flex-col
          bg-surface rounded-t-2xl shadow-2xl
          transition-transform duration-300 ease-out
          ${isOpen
            ? 'translate-y-0 pointer-events-auto'
            : 'translate-y-full pointer-events-none'}
        `}
        style={{
          height: 'min(calc(var(--app-height, 100dvh) * 0.5), 400px)',
        }}
      >
        {/* 드래그 핸들 */}
        <div className="flex justify-center py-3 shrink-0">
          <div className="w-10 h-1 bg-onSurface/30 rounded-full" />
        </div>

        {/* 콘텐츠 - safe-area 패딩 적용 */}
        <div className="mobile-bottom-sheet-content flex-1 min-h-0 overflow-hidden">
          {children}
        </div>
      </div>
    </>
  )
}

export default MobileBottomSheet
```

### 4.3 FloatingPanelButton 컴포넌트

```tsx
// components/student/FloatingPanelButton.tsx
interface FloatingPanelButtonProps {
  onClick: () => void
  hasUnread?: boolean
}

function FloatingPanelButton({ onClick, hasUnread }: FloatingPanelButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="floating-panel-button"
      aria-label="Open chat panel"
    >
      <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
        />
      </svg>

      {hasUnread && (
        <span className="absolute -top-1 -right-1 w-4 h-4 bg-error rounded-full" />
      )}
    </button>
  )
}

export default FloatingPanelButton
```

**사용 예시** (wrapper로 감싸서 반응형 처리):
```tsx
{isCompact && !panelOpen && (
  <FloatingPanelButton
    onClick={() => setPanelOpen(true)}
    hasUnread={hasUnreadMessages}
  />
)}
```

### 4.4 PanelTabs 컴포넌트

```tsx
// components/student/PanelTabs.tsx
type TabType = 'chat' | 'participants' | 'materials'

interface PanelTabsProps {
  activeTab: TabType
  onChange: (tab: TabType) => void
  showMaterials: boolean
}

const TABS: { id: TabType; label: string; icon: JSX.Element }[] = [
  { id: 'chat', label: 'Chat', icon: <ChatIcon /> },
  { id: 'participants', label: 'Participants', icon: <UsersIcon /> },
  { id: 'materials', label: 'Materials', icon: <DocumentIcon /> },
]

// 아이콘 크기: w-9 h-9
function PanelTabs({ activeTab, onChange, showMaterials }: PanelTabsProps) {
  const visibleTabs = showMaterials
    ? TABS
    : TABS.filter(t => t.id !== 'materials')

  return (
    <div className="flex border-b border-primaryContainer shrink-0" role="tablist">
      {visibleTabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`panel-tab-${tab.id}`}
          aria-selected={activeTab === tab.id}
          aria-controls={`panel-tabpanel-${tab.id}`}
          onClick={() => onChange(tab.id)}
          className={`
            flex-1 flex items-center justify-center gap-3
            py-6 text-2xl font-medium
            border-b-2 transition-colors
            ${activeTab === tab.id
              ? 'border-primary text-primary'
              : 'border-transparent text-onSurface/60 hover:text-onSurface'
            }
          `}
        >
          {tab.icon}
          {tab.label}
        </button>
      ))}
    </div>
  )
}

export default PanelTabs
```

### 4.5 PanelContent 컴포넌트 (순수 렌더링)

```tsx
// components/student/PanelContent.tsx
import PanelTabs from './PanelTabs'
import ChatPanel from './ChatPanel'
import ParticipantsPanel from '@/components/common/ParticipantsPanel'
import MaterialsPanel from './MaterialsPanel'

type TabType = 'chat' | 'participants' | 'materials'

interface PanelContentProps {
  activeTab: TabType
  onTabChange: (tab: TabType) => void
  showMaterials: boolean
  // Chat props
  chatMessages: ChatMessage[]
  chatInput: string
  onChatInputChange: (value: string) => void
  onChatSubmit: () => void
  isConnected: boolean
  // Participants props
  participants: ParticipantsData
  studentCount: number
  // Materials props
  materials: MaterialItem[]
}

function PanelContent({
  activeTab,
  onTabChange,
  showMaterials,
  ...props
}: PanelContentProps) {
  // 상태 보정 로직은 Student.tsx에서 처리 (이 컴포넌트는 순수 렌더링)

  return (
    <div className="flex flex-col h-full min-h-0">
      <PanelTabs
        activeTab={activeTab}
        onChange={onTabChange}
        showMaterials={showMaterials}
      />

      <div
        className="flex-1 min-h-0 overflow-hidden"
        role="tabpanel"
        id={`panel-tabpanel-${activeTab}`}
        aria-labelledby={`panel-tab-${activeTab}`}
      >
        {activeTab === 'chat' && (
          <ChatPanel
            messages={props.chatMessages}
            input={props.chatInput}
            onInputChange={props.onChatInputChange}
            onSubmit={props.onChatSubmit}
            isConnected={props.isConnected}
          />
        )}
        {activeTab === 'participants' && (
          <ParticipantsPanel
            participants={props.participants}
            fallbackStudentCount={props.studentCount}
          />
        )}
        {activeTab === 'materials' && (
          <MaterialsPanel materials={props.materials} />
        )}
      </div>
    </div>
  )
}

export default PanelContent
```

### 4.6 ChatPanel (키보드 + form 대응)

```tsx
// components/student/ChatPanel.tsx
import { FormEvent } from 'react'

interface ChatPanelProps {
  messages: ChatMessage[]
  input: string
  onInputChange: (value: string) => void
  onSubmit: () => void
  isConnected: boolean
}

function ChatPanel({ messages, input, onInputChange, onSubmit, isConnected }: ChatPanelProps) {
  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()  // 페이지 새로고침 방지
    if (input.trim()) {
      onSubmit()
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* 메시지 영역 - flex-1 + min-h-0 + overflow-y-auto */}
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 ? (
          <div className="text-center text-2xl text-onSurface/60 mt-8">
            No messages yet
          </div>
        ) : (
          messages.map((msg) => (
            // 메시지 이름: text-2xl font-semibold
            // 메시지 본문: text-2xl leading-relaxed
            <ChatMessage key={msg.id} message={msg} />
          ))
        )}
      </div>

      {/* 입력 영역 - shrink-0 (키보드 올라와도 고정) */}
      <form
        onSubmit={handleSubmit}
        className="p-5 border-t border-primaryContainer flex gap-4 shrink-0"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          placeholder={isConnected ? 'Type a message...' : 'Connecting...'}
          disabled={!isConnected}
          className="flex-1 bg-white text-gray-900 rounded-xl px-6 py-5 text-2xl"
          maxLength={200}
        />
        <button
          type="submit"
          disabled={!input.trim() || !isConnected}
          className="px-8 py-5 bg-primary text-onPrimary rounded-xl text-2xl font-medium disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  )
}

export default ChatPanel
```

### 4.7 MaterialsPanel (Empty State 포함)

```tsx
// components/student/MaterialsPanel.tsx
interface MaterialsPanelProps {
  materials: MaterialItem[]
}

function MaterialsPanel({ materials }: MaterialsPanelProps) {
  if (materials.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center text-2xl text-onSurface/60">
          <DocumentIcon className="w-16 h-16 mx-auto mb-4 opacity-40" />
          <p>No materials uploaded yet.</p>
        </div>
      </div>
    )
  }

  // 각 아이템: w-8 h-8 아이콘, text-2xl 파일명, text-lg 상태
  return (
    <div className="h-full min-h-0 overflow-y-auto p-3 space-y-1">
      {materials.map((material) => (
        <MaterialItem key={material.slide_id} material={material} />
      ))}
    </div>
  )
}

export default MaterialsPanel
```

---

## 5. CSS 설계

### 5.1 추가할 CSS 클래스 (index.css)

```css
/* ===== 반응형 레이아웃 ===== */

/* 플로팅 버튼 - safe-area 고려 */
.floating-panel-button {
  position: fixed;
  right: max(1.5rem, env(safe-area-inset-right));
  bottom: max(1.5rem, env(safe-area-inset-bottom));
  z-index: 40;
  width: 4.5rem;
  height: 4.5rem;
  border-radius: 9999px;
  background-color: var(--color-primary);
  color: var(--color-on-primary);
  box-shadow: 0 4px 12px rgba(100, 149, 235, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.15s, opacity 0.15s;
}

.floating-panel-button:active {
  transform: scale(0.95);
}

/* 모바일 바텀시트 */
.mobile-bottom-sheet {
  /* 기본 스타일은 Tailwind로 처리 */
}

/* 모바일 바텀시트 콘텐츠 - safe-area 패딩 */
.mobile-bottom-sheet-content {
  padding-bottom: env(safe-area-inset-bottom);
}

/* 그라데이션 모드 바텀시트 */
html.theme-gradient .mobile-bottom-sheet {
  background: #E0DEF7;
  --color-on-surface: #374151;
}

/* Wide 레이아웃에서 숨김 */
@media (min-width: 900px) and (min-height: 500px) {
  .mobile-only {
    display: none !important;
  }
}

/* Compact 레이아웃에서 숨김 */
@media not all and (min-width: 900px) and (min-height: 500px) {
  .desktop-only {
    display: none !important;
  }
}

/* 모션 감소 설정 대응 */
@media (prefers-reduced-motion: reduce) {
  .mobile-bottom-sheet,
  .floating-panel-button {
    transition: none;
  }
}
```

### 5.2 Tailwind 커스텀 스크린 추가 (tailwind.config.js)

```js
// tailwind.config.js
export default {
  theme: {
    extend: {
      screens: {
        // Wide 레이아웃: 900px 이상 AND 500px 높이 이상
        // 주의: hooks/useResponsiveLayout.ts의 WIDE_MEDIA_QUERY와 동일 기준
        'wide': { raw: '(min-width: 900px) and (min-height: 500px)' },
      },
      zIndex: {
        '60': '60',
      },
    },
  },
}
```

사용 예시:
```tsx
<DesktopSidebar className="hidden wide:flex" />
```

---

## 6. 상태 관리

### 6.1 필요한 상태 (Student.tsx)

```tsx
const { isWide, isCompact } = useResponsiveLayout()

const [panelOpen, setPanelOpen] = useState(false)
const [activeTab, setActiveTab] = useState<'chat' | 'participants' | 'materials'>('chat')
const [lastReadMessageCount, setLastReadMessageCount] = useState(0)

const showMaterials = isLectureStarted

// onTabChange는 useCallback으로 메모이제이션
const handleTabChange = useCallback((tab: TabType) => {
  setActiveTab(tab)
}, [])
```

### 6.2 레이아웃 전환 시 상태 처리

```tsx
// 모드 전환 시 panelOpen = false
useEffect(() => {
  setPanelOpen(false)
}, [isWide])
```

### 6.3 자료 탭 방어 처리 (Student.tsx에서만)

```tsx
// 자료 탭 숨김 상태인데 activeTab이 materials면 chat으로 전환
useEffect(() => {
  if (!showMaterials && activeTab === 'materials') {
    setActiveTab('chat')
  }
}, [showMaterials, activeTab])
```

### 6.4 안 읽은 메시지 처리

```tsx
// 내가 보낸 메시지 제외, 패널 닫혀있을 때만 unread 처리
const hasUnreadMessages = useMemo(() => {
  if (panelOpen && activeTab === 'chat') return false

  const newMessages = chatMessages.slice(lastReadMessageCount)
  // 내가 보낸 메시지 제외
  return newMessages.some(msg => msg.sender !== 'self')
}, [chatMessages, lastReadMessageCount, panelOpen, activeTab])

// 패널 열고 채팅 탭 보면 읽음 처리
useEffect(() => {
  if (panelOpen && activeTab === 'chat') {
    setLastReadMessageCount(chatMessages.length)
  }
}, [panelOpen, activeTab, chatMessages.length])
```

---

## 7. 마이그레이션 계획

### 7.1 단계별 구현

**Phase 1: 기존 컴포넌트 분리** (가장 중요)
1. 기존 Student.tsx 사이드바 코드 영역 식별
2. 자료 목록 UI를 `MaterialsPanel`로 추출 (empty state 포함)
3. 채팅 UI를 `ChatPanel`로 추출 (form submit preventDefault 포함)
4. `ParticipantsPanel`에서 absolute/fixed/z-index 의존성 제거
5. `PanelTabs` 컴포넌트 생성
6. `PanelContent`에서 세 패널을 탭으로 조합

**Phase 2: 데스크톱 사이드바 적용**
1. `DesktopSidebar`에 `PanelContent` 적용
2. 기존 Wide 동작 유지 확인
3. 탭 전환 테스트

**Phase 3: 반응형 훅 적용**
1. `useResponsiveLayout` 훅 생성
2. Tailwind `wide` 스크린 및 `z-60` 추가
3. 기존 `isNarrow` 로직 제거
4. 레이아웃 전환 테스트

**Phase 4: 모바일 UI 구현**
1. CSS 클래스 추가 (floating-panel-button, mobile-bottom-sheet 등)
2. `MobileBottomSheet` 컴포넌트 생성 (CSS 클래스명 일치 확인)
3. `FloatingPanelButton` 컴포넌트 생성
4. 모바일 레이아웃 통합
5. 키보드 입력 테스트

**Phase 5: 정리 및 테스트**
1. 기존 사이드바 토글 버튼 제거
2. unread badge, 접근성 정리
3. 모든 화면 크기에서 테스트
4. 애니메이션/전환 효과 다듬기

### 7.2 파일 변경 목록

| 작업 | 파일 | 변경 유형 |
|------|------|----------|
| 훅 생성 | `hooks/useResponsiveLayout.ts` | 신규 |
| Tailwind 설정 | `tailwind.config.js` | 수정 |
| CSS 추가 | `styles/index.css` | 수정 |
| 채팅 분리 | `components/student/ChatPanel.tsx` | 신규 |
| 자료 분리 | `components/student/MaterialsPanel.tsx` | 신규 |
| 탭 컴포넌트 | `components/student/PanelTabs.tsx` | 신규 |
| 패널 콘텐츠 | `components/student/PanelContent.tsx` | 신규 |
| 플로팅 버튼 | `components/student/FloatingPanelButton.tsx` | 신규 |
| 바텀시트 | `components/student/MobileBottomSheet.tsx` | 신규 |
| 사이드바 | `components/student/DesktopSidebar.tsx` | 신규 |
| 참여자 패널 | `components/common/ParticipantsPanel.tsx` | 수정 (스타일 분리) |
| 메인 페이지 | `pages/Student.tsx` | 수정 |

---

## 8. 접근성 고려사항

### 8.1 키보드 접근성
- 바텀시트: ESC로 닫기 (구현됨)
- 플로팅 버튼: Tab으로 포커스 가능
- 탭: `role="tablist"`, `role="tab"`, `aria-selected`, `aria-controls`

### 8.2 스크린 리더
- 플로팅 버튼: `aria-label="채팅 패널 열기"`
- 바텀시트 열림: `role="dialog"`, `aria-modal="true"`, `aria-label`
- 바텀시트 닫힘: `aria-hidden="true"`, `pointer-events-none`
- 탭패널: `role="tabpanel"`, `aria-labelledby`

### 8.3 Focus Trap (후순위)
- `aria-modal="true"` 사용 시 원칙적으로 focus trap 필요
- MVP에서는 ESC 닫기 + aria-hidden + pointer-events-none으로 대응
- Focus trap은 후속 개선으로 분리

### 8.4 모션 감소
```css
@media (prefers-reduced-motion: reduce) {
  .mobile-bottom-sheet,
  .floating-panel-button {
    transition: none;
  }
}
```

---

## 9. 테스트 시나리오

### 9.1 디바이스별 테스트
| 디바이스 | 화면 크기 | 예상 레이아웃 |
|----------|----------|--------------|
| iPhone 14 세로 | 390 x 844 | Compact |
| iPhone 14 가로 | 844 x 390 | Compact (height < 500) |
| Galaxy S23 가로 | 915 x 412 | Compact (height < 500) |
| iPad Mini 가로 | 1024 x 768 | Wide |
| Galaxy Fold 외부 | 717 x 1024 | Compact (width < 900) |
| Galaxy Fold 내부 | CSS viewport 기준 | 조건 만족 시 Wide |
| Desktop | 1920 x 1080 | Wide |

### 9.2 기능 테스트
- [x] Compact: 플로팅 버튼 표시 확인
- [x] Compact: 바텀시트 열기/닫기
- [x] Compact: ESC로 바텀시트 닫기
- [x] Compact: 배경(backdrop) 클릭 시 바텀시트 닫기
- [x] Compact: 탭 전환 동작
- [x] Compact: 슬라이드 영역 크기 변화 없음 (오버레이)
- [x] Compact: 채팅 입력 시 키보드가 올라와도 입력창이 가려지지 않음
- [x] Compact: 채팅 Enter/전송 버튼 클릭 시 페이지 새로고침 안 됨
- [x] Compact: 바텀시트 닫힘 상태에서 내부 요소로 Tab 포커스 이동 안 됨
- [x] Wide: 사이드바 상시 표시
- [x] Wide: 플로팅 버튼 숨김
- [x] 화면 회전 시 레이아웃 전환
- [x] Wide → Compact 전환 시 사이드바 사라지고 플로팅 버튼 나타남
- [x] Compact → Wide 전환 시 바텀시트 닫히고 사이드바로 전환
- [x] 채팅 메시지 수신 시 뱃지 표시 (내가 보낸 메시지 제외)
- [x] 패널 열고 채팅 탭 보면 뱃지 사라짐
- [x] 참여자/자료 탭만 열었을 때는 채팅 뱃지 유지
- [x] 자료 탭 숨김 상태에서 activeTab이 materials로 남아있지 않음
- [x] 강의 시작 후 자료 없을 때 "No materials uploaded yet." 표시
- [x] Android WebView에서 `window.innerHeight` 값이 예상대로 나옴

---

## 10. 위험 요소 및 필수 반영 사항

### 10.1 위험도 높은 부분

| 위험 요소 | 설명 | 대응 |
|----------|------|------|
| **기존 ParticipantsPanel 스타일** | absolute/fixed/z-index가 남아있으면 탭 안에서 깨짐 | Phase 1에서 스타일 분리 |
| **CSS 클래스명 불일치** | mobile-bottom-sheet 등 JSX에서 누락 | 컴포넌트에 클래스 추가 |
| **form onSubmit 기본동작** | preventDefault 누락 시 새로고침 | ChatPanel에서 처리 |
| **키보드 대응** | Bottom Sheet 안에서 입력창이 가려질 수 있음 | 실기기 테스트 필수 |
| **닫힌 Bottom Sheet 접근성** | DOM에 남아있어 포커스/스크린리더 문제 | aria-hidden, pointer-events-none |
| **activeTab 불일치** | showMaterials=false인데 activeTab=materials | Student.tsx에서 방어 |
| **기준 불일치** | CSS media query와 JS hook 기준이 다름 | 상수 한 곳에서 관리 |

### 10.2 필수 반영 체크리스트

- [x] MobileBottomSheet JSX에 `mobile-bottom-sheet` class 추가
- [x] 콘텐츠 영역에 `mobile-bottom-sheet-content` class 추가
- [x] 닫힌 Bottom Sheet에 `aria-hidden`, `pointer-events-none` 적용
- [x] ChatPanel form submit에서 `preventDefault` 처리
- [x] activeTab=materials 방어 처리는 Student.tsx에서만
- [x] Tailwind z-index는 `z-60` 사용 (config에 추가)
- [x] FloatingPanelButton은 조건부 렌더링으로 처리 (className prop 없음)
- [x] useResponsiveLayout에서 동일 mode면 setState 생략
- [x] PanelTabs에 `aria-controls`, `id` 추가
- [x] PanelContent에 `role="tabpanel"`, `aria-labelledby` 추가
- [x] MaterialsPanel에 empty state 포함
- [x] ParticipantsPanel에서 absolute/fixed/z-index 제거

---

## 11. 향후 개선 사항

1. **드래그로 바텀시트 높이 조절** - 사용자가 원하는 만큼 올리고 내리기
2. **스와이프로 닫기** - 아래로 스와이프하면 바텀시트 닫기
3. **탭별 상태 유지** - 탭 전환해도 스크롤 위치 등 유지
4. **Picture-in-Picture 모드** - 바텀시트 열어도 슬라이드 미니 뷰 표시
5. **Focus Trap** - 접근성 완성도 향상
6. **visualViewport 대응** - 키보드로 인한 viewport 변화 정밀 감지
7. **unread id/time 기반** - count 기반보다 정확한 읽음 처리
