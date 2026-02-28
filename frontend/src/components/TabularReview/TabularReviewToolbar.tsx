import {
  FileText,
  Filter,
  FolderOpen,
  Download,
} from "lucide-react"

interface TabularReviewToolbarProps {
  onOpenFilter?: (anchorEl: HTMLElement) => void
  onAddColumns?: () => void
  onUpdateDocuments?: () => void
  onExport?: () => void
  processing?: boolean
}

export function TabularReviewToolbar({
  onOpenFilter,
  onAddColumns,
  onUpdateDocuments,
  onExport,
  processing = false,
}: TabularReviewToolbarProps) {

  return (
    <div className="flex items-center justify-between py-4 px-6 border-b border-[#E5E7EB] bg-white/80 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        {onOpenFilter && (
          <button
            type="button"
            onClick={(e) => onOpenFilter(e.currentTarget as HTMLElement)}
            disabled={processing}
            className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            aria-label="Filter"
          >
            <Filter className="w-4 h-4" />
            Filter
          </button>
        )}
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
          className="px-4 py-2 bg-white border border-[#3B82F6] text-[#3B82F6] text-sm font-medium rounded-lg hover:bg-[#EFF6FF] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <FileText className="w-4 h-4" />
          Column builder
        </button>
      </div>

      {/* Right side */}
      {onExport && (
        <button
          onClick={onExport}
          disabled={processing}
          className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <Download className="w-4 h-4" />
          Export
        </button>
      )}
    </div>
  )
}
