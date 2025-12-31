import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { AssistantUIChat } from '../components/Chat/AssistantUIChat'
import { ChatHistoryPanel } from '../components/Chat/ChatHistoryPanel'
import { 
  DropdownMenu, 
  DropdownMenuContent, 
  DropdownMenuItem, 
  DropdownMenuTrigger 
} from '../components/UI/dropdown-menu'
import { ChevronDown, Upload, Share2, History, Plus } from 'lucide-react'

const AssistantChatPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()
  const [historyPanelOpen, setHistoryPanelOpen] = useState(false)
  const [selectedQuery, setSelectedQuery] = useState<string>('')

  if (!caseId) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-body text-[#6B7280]">Дело не найдено</p>
      </div>
    )
  }

  const handleSelectQuery = (query: string) => {
    setSelectedQuery(query)
    setHistoryPanelOpen(false)
  }

  return (
    <div className="h-full w-full flex flex-col fade-in-up relative">
      {/* Top toolbar */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-gray-200 bg-white">
        <div className="flex items-center gap-4">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors">
                Tabular Review
                <ChevronDown className="w-4 h-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem onClick={() => navigate(`/cases/${caseId}/tabular-review`)}>
                Open Tabular Review
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors">
                Uploads
                <ChevronDown className="w-4 h-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem>
                <Upload className="w-4 h-4 mr-2" />
                Upload Documents
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <div className="flex items-center gap-3">
          <button className="px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors">
            <Share2 className="w-4 h-4" />
          </button>
          <button 
            onClick={() => setHistoryPanelOpen(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <History className="w-4 h-4" />
            Chat history
            <Plus className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Main chat area */}
      <div className="flex-1 overflow-hidden">
        <AssistantUIChat 
          caseId={caseId} 
          className="h-full"
          initialQuery={selectedQuery}
          onQuerySelected={() => setSelectedQuery('')}
        />
      </div>

      {/* History panel */}
      <ChatHistoryPanel
        isOpen={historyPanelOpen}
        onClose={() => setHistoryPanelOpen(false)}
        currentCaseId={caseId}
        onSelectQuery={handleSelectQuery}
      />
    </div>
  )
}

export default AssistantChatPage


