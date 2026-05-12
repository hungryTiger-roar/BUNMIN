/**
 * TitleBar — frame: false BrowserWindow 용 자체 타이틀바.
 *
 * 동작:
 *  - 전체 영역: `-webkit-app-region: drag` 로 윈도우 드래그 핸들
 *  - 우측 버튼들: `no-drag` 로 클릭 가능
 *  - close 는 mainWindow.close() 호출 → close 이벤트 → isQuitting 분기 (트레이 hide 흐름과 일치)
 *  - max/restore 아이콘은 IPC 로 받은 maximize 상태에 따라 토글
 */
import { useEffect, useState } from 'react'

export function TitleBar() {
  const [maximized, setMaximized] = useState(false)

  useEffect(() => {
    let alive = true
    window.electron?.isWindowMaximized?.().then((m) => {
      if (alive) setMaximized(m)
    })
    const unsubscribe = window.electron?.onWindowMaximizedChange?.((m) => {
      setMaximized(m)
    })
    return () => {
      alive = false
      unsubscribe?.()
    }
  }, [])

  const dragStyle: React.CSSProperties = { WebkitAppRegion: 'drag' } as React.CSSProperties
  const noDragStyle: React.CSSProperties = { WebkitAppRegion: 'no-drag' } as React.CSSProperties

  // 테마별 색상 — index.css 가 light/dark/gradient 별로 var 재정의.
  // gradient 모드는 rgba 라 backdrop-filter 로 글래스 효과 강조.
  const barStyle: React.CSSProperties = {
    ...dragStyle,
    backgroundColor: 'var(--titlebar-bg)',
    color: 'var(--titlebar-fg)',
    backdropFilter: 'blur(8px)',
    WebkitBackdropFilter: 'blur(8px)',
  }

  return (
    <div
      className="fixed top-0 left-0 right-0 h-8 z-[100] flex items-center select-none"
      style={barStyle}
    >
      {/* 좌측 — 앱 이름 / 브랜드 라벨 */}
      <div className="flex items-center gap-2 pl-3 text-[11px] tracking-wide opacity-80">
        <span className="w-1.5 h-1.5 rounded-full bg-indigo-500" />
        <span>Aunion AI</span>
      </div>

      {/* 우측 — 윈도우 컨트롤 */}
      <div className="ml-auto flex h-full" style={noDragStyle}>
        <TitleButton
          onClick={() => window.electron?.minimizeWindow()}
          ariaLabel="최소화"
        >
          <svg width="10" height="10" viewBox="0 0 10 10">
            <line x1="0" y1="5" x2="10" y2="5" stroke="currentColor" strokeWidth="1" />
          </svg>
        </TitleButton>

        <TitleButton
          onClick={() => window.electron?.toggleMaximizeWindow()}
          ariaLabel={maximized ? '이전 크기로' : '최대화'}
        >
          {maximized ? (
            // 복원 — 두 사각형 겹침
            <svg width="10" height="10" viewBox="0 0 10 10">
              <rect x="0" y="2" width="7" height="7" fill="none" stroke="currentColor" strokeWidth="1" />
              <path d="M2 2 V 0 H 9 V 7 H 7" fill="none" stroke="currentColor" strokeWidth="1" />
            </svg>
          ) : (
            <svg width="10" height="10" viewBox="0 0 10 10">
              <rect x="0.5" y="0.5" width="9" height="9" fill="none" stroke="currentColor" strokeWidth="1" />
            </svg>
          )}
        </TitleButton>

        <button
          type="button"
          onClick={() => window.electron?.closeWindow()}
          aria-label="닫기"
          className="w-11 h-full inline-flex items-center justify-center transition-colors hover:bg-red-500 hover:text-white"
        >
          <svg width="10" height="10" viewBox="0 0 10 10">
            <path d="M0 0 L 10 10 M 10 0 L 0 10" stroke="currentColor" strokeWidth="1" />
          </svg>
        </button>
      </div>
    </div>
  )
}

function TitleButton({
  onClick,
  ariaLabel,
  children,
}: {
  onClick?: () => void
  ariaLabel: string
  children: React.ReactNode
}) {
  // 호버: 현재 색상의 10% 어두운 톤 — currentColor 의 mix-blend 로 처리하기 위해
  // bg-black/5 (라이트), dark 에선 별도 처리는 안 함 (어두운 배경 + 5% 검정 → 어두워지긴 함).
  // 깔끔히 하기 위해 일관된 black/5 사용.
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className="w-11 h-full inline-flex items-center justify-center transition-colors hover:bg-black/5 dark:hover:bg-white/10"
    >
      {children}
    </button>
  )
}
