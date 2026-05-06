import PanelContent from './PanelContent'
import type { TabType } from './PanelTabs'
import type { MaterialItem } from './MaterialsPanel'
import type { ChatMessage, Participants } from '@/stores/lectureStore'

interface DesktopSidebarProps {
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
  participants: Participants
  studentCount: number
  // Materials props
  materials: MaterialItem[]
}

function DesktopSidebar(props: DesktopSidebarProps) {
  return (
    <aside className="w-80 flex-shrink-0 flex flex-col min-h-0 hidden wide:flex">
      <div className="flex-1 flex flex-col bg-surface text-onSurface backdrop-blur-md rounded-xl border border-primaryContainer shadow-sm overflow-hidden min-h-0 sidebar-card">
        <PanelContent {...props} />
      </div>
    </aside>
  )
}

export default DesktopSidebar
