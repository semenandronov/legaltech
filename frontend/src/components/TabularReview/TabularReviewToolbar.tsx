import {
  Plus,
  FileText,
  Play,
  FolderOpen,
} from "lucide-react"

interface TabularReviewToolbarProps {
  onAddDocuments?: () => void
  onAddColumns?: () => void
  onUpdateDocuments?: () => void
  onRunAll?: () => void
  processing?: boolean
}

export function TabularReviewToolbar({
  onAddDocuments,
  onAddColumns,
  onUpdateDocuments,
  onRunAll,
  processing = false,
}: TabularReviewToolbarProps) {

  return (
    <div className="flex items-center justify-between py-4 px-6 border-b border-[#E5E7EB] bg-white/80 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        <button
          onClick={onAddDocuments}
          disabled={processing}
          className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <Plus className="w-4 h-4" />
          Add documents
        </button>
        {onUpdateDocuments && (
          <button
            onClick={onUpdateDocuments}
            disabled={processing}
            className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <FolderOpen className="w-4 h-4" />
            Изменить документы
          </button>
        )}
        <button
          onClick={onAddColumns}
          disabled={processing}
          className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <FileText className="w-4 h-4" />
          Add columns
        </button>
      </div>
      
      <div className="flex items-center gap-3">
        <button
          onClick={onRunAll}
          disabled={processing}
          className="px-5 py-2 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white text-sm font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <Play className="w-4 h-4" />
          {processing ? "Обработка..." : "Run all"}
        </button>
      </div>
    </div>
  )
}

