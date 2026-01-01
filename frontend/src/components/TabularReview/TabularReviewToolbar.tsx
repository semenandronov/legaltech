import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/UI/dropdown-menu"
import {
  Plus,
  FileText,
  Play,
  Download,
  Share2,
  ChevronDown,
  FolderOpen,
  LayoutTemplate,
} from "lucide-react"

interface TabularReviewToolbarProps {
  onAddDocuments?: () => void
  onAddColumns?: () => void
  onUpdateDocuments?: () => void
  onRunAll?: () => void
  onDownload?: (format: "csv" | "excel") => void
  onShare?: () => void
  onTemplates?: () => void
  processing?: boolean
  creditsUsed?: number
  creditsLimit?: number
}

export function TabularReviewToolbar({
  onAddDocuments,
  onAddColumns,
  onUpdateDocuments,
  onRunAll,
  onDownload,
  onShare,
  onTemplates,
  processing = false,
  creditsUsed = 0,
  creditsLimit = 1000,
}: TabularReviewToolbarProps) {
  const creditsPercentage = creditsLimit > 0 ? (creditsUsed / creditsLimit) * 100 : 0
  const isWarning = creditsPercentage >= 80
  const isError = creditsPercentage >= 95

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
        {onTemplates && (
          <button
            onClick={onTemplates}
            disabled={processing}
            className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <LayoutTemplate className="w-4 h-4" />
            Templates
          </button>
        )}
      </div>
      
      <div className="flex items-center gap-3">
        {/* Credits indicator */}
        {(creditsUsed > 0 || creditsLimit > 0) && (
          <div
            className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-2 ${
              isError
                ? "bg-red-50 text-red-700 border border-red-200"
                : isWarning
                ? "bg-yellow-50 text-yellow-700 border border-yellow-200"
                : "bg-gray-50 text-gray-700 border border-gray-200"
            }`}
            title={`Использовано ${creditsUsed} из ${creditsLimit} кредитов`}
          >
            <span>{creditsUsed}/{creditsLimit}</span>
            {isWarning && (
              <span className="text-[10px] opacity-75">⚠️</span>
            )}
          </div>
        )}
        
        <button
          onClick={onRunAll}
          disabled={processing}
          className="px-5 py-2 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white text-sm font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <Play className="w-4 h-4" />
          {processing ? "Обработка..." : "Run all"}
        </button>
        
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              disabled={processing}
              className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              Download
              <ChevronDown className="w-4 h-4" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="bg-white border border-[#E5E7EB] rounded-lg shadow-lg">
            <DropdownMenuItem 
              onClick={() => onDownload?.("csv")}
              className="hover:bg-[#F3F4F6] cursor-pointer"
            >
              CSV
            </DropdownMenuItem>
            <DropdownMenuItem 
              onClick={() => onDownload?.("excel")}
              className="hover:bg-[#F3F4F6] cursor-pointer"
            >
              Excel
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        
        <button
          onClick={onShare}
          disabled={processing}
          className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <Share2 className="w-4 h-4" />
          Share
        </button>
      </div>
    </div>
  )
}

