import {
  FileText,
  FolderOpen,
} from "lucide-react"

interface TabularReviewToolbarProps {
  onAddColumns?: () => void
  onUpdateDocuments?: () => void
  processing?: boolean
}

export function TabularReviewToolbar({
  onAddColumns,
  onUpdateDocuments,
  processing = false,
}: TabularReviewToolbarProps) {

  return (
    <div className="flex items-center justify-between py-4 px-6 border-b border-[#E5E7EB] bg-white/80 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        {onUpdateDocuments && (
          <button
            onClick={onUpdateDocuments}
            disabled={processing}
            className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <FolderOpen className="w-4 h-4" />
            Add file
          </button>
        )}
        <button
          onClick={onAddColumns}
          disabled={processing}
          className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <FileText className="w-4 h-4" />
          Column builder
        </button>
      </div>
    </div>
  )
}
