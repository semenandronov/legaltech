import {
  FileText,
  Play,
  FolderOpen,
  MessageSquare,
  BookOpen,
} from "lucide-react"

interface TabularReviewToolbarProps {
  onAddColumns?: () => void
  onUpdateDocuments?: () => void
  onRunAll?: () => void
  onToggleChat?: () => void
  onRunPlaybook?: () => void
  isChatOpen?: boolean
  processing?: boolean
  playbookRunning?: boolean
}

export function TabularReviewToolbar({
  onAddColumns,
  onUpdateDocuments,
  onRunAll,
  onToggleChat,
  onRunPlaybook,
  isChatOpen = false,
  processing = false,
  playbookRunning = false,
}: TabularReviewToolbarProps) {

  return (
    <div className="flex items-center justify-between py-4 px-6 border-b border-[#E5E7EB] bg-white/80 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        {onUpdateDocuments && (
          <button
            onClick={onUpdateDocuments}
            disabled={processing || playbookRunning}
            className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <FolderOpen className="w-4 h-4" />
            Изменить документы
          </button>
        )}
        <button
          onClick={onAddColumns}
          disabled={processing || playbookRunning}
          className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <FileText className="w-4 h-4" />
          Add columns
        </button>
        {onRunPlaybook && (
          <button
            onClick={onRunPlaybook}
            disabled={processing || playbookRunning}
            className="px-4 py-2 bg-white border border-green-300 text-green-700 text-sm font-medium rounded-lg hover:bg-green-50 hover:text-green-800 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <BookOpen className="w-4 h-4" />
            {playbookRunning ? "Проверка..." : "Playbook"}
          </button>
        )}
        {onToggleChat && (
          <button
            onClick={onToggleChat}
            disabled={processing || playbookRunning}
            className={`px-4 py-2 border text-sm font-medium rounded-lg transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 ${
              isChatOpen
                ? "bg-accent text-bg-primary border-accent hover:bg-accent-hover"
                : "bg-white border-[#E5E7EB] text-[#6B7280] hover:bg-[#F3F4F6] hover:text-[#1F2937]"
            }`}
          >
            <MessageSquare className="w-4 h-4" />
            Чат
          </button>
        )}
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={onRunAll}
          disabled={processing || playbookRunning}
          className="px-5 py-2 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white text-sm font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <Play className="w-4 h-4" />
          {processing ? "Обработка..." : "Run all"}
        </button>
      </div>
    </div>
  )
}
