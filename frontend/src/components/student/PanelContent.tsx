import PanelTabs, { type TabType } from './PanelTabs'
import ChatPanel from './ChatPanel'
import ParticipantsPanel from '@/components/common/ParticipantsPanel'
import MaterialsPanel, { type MaterialItem } from './MaterialsPanel'
import type { ChatMessage, Participants } from '@/stores/lectureStore'

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
  participants: Participants
  studentCount: number
  // Materials props
  materials: MaterialItem[]
}

function PanelContent({
  activeTab,
  onTabChange,
  showMaterials,
  chatMessages,
  chatInput,
  onChatInputChange,
  onChatSubmit,
  isConnected,
  participants,
  studentCount,
  materials,
}: PanelContentProps) {
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
            messages={chatMessages}
            input={chatInput}
            onInputChange={onChatInputChange}
            onSubmit={onChatSubmit}
            isConnected={isConnected}
          />
        )}
        {activeTab === 'participants' && (
          <ParticipantsPanel
            participants={participants}
            fallbackStudentCount={studentCount}
          />
        )}
        {activeTab === 'materials' && (
          <MaterialsPanel materials={materials} />
        )}
      </div>
    </div>
  )
}

export default PanelContent
