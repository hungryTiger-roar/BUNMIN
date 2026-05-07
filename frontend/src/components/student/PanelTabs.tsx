export type TabType = 'chat' | 'participants' | 'materials'

interface PanelTabsProps {
  activeTab: TabType
  onChange: (tab: TabType) => void
  showMaterials: boolean
}

const ChatIcon = () => (
  <svg className="w-6 h-6 wide:w-5 wide:h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
  </svg>
)

const UsersIcon = () => (
  <svg className="w-6 h-6 wide:w-5 wide:h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
  </svg>
)

const DocumentIcon = () => (
  <svg className="w-6 h-6 wide:w-5 wide:h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
  </svg>
)

const TABS: { id: TabType; label: string; icon: JSX.Element }[] = [
  { id: 'chat', label: 'Chat', icon: <ChatIcon /> },
  { id: 'participants', label: 'Participants', icon: <UsersIcon /> },
  { id: 'materials', label: 'Materials', icon: <DocumentIcon /> },
]

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
            flex-1 flex items-center justify-center gap-2
            py-4 wide:py-3 text-lg wide:text-sm font-medium
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
