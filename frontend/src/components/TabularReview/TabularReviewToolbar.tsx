import {
  FileText,
  Filter,
  FolderOpen,
  Download,
  HelpCircle,
  MessageSquare,
} from "lucide-react"

interface TabularReviewToolbarProps {
  onOpenFilter?: (anchorEl: HTMLElement) => void
  onAddColumns?: () => void
  onUpdateDocuments?: () => void
  onExport?: () => void
  onOpenHelp?: () => void
  onToggleChat?: () => void
  chatOpen?: boolean
  processing?: boolean
}

export function TabularReviewToolbar({
  onOpenFilter,
  onAddColumns,
  onUpdateDocuments,
  onExport,
  onOpenHelp,
  onToggleChat,
  chatOpen = false,
  processing = false,
}: TabularReviewToolbarProps) {

  return (
    <div className="flex items-center justify-between py-4 px-6 border-b border-[#E5E7EB] bg-white/80 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        {onOpenHelp && (
          <button
            type="button"
            onClick={onOpenHelp}
            disabled={processing}
            className="px-3 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            aria-label="Как пользоваться таблицей"
          >
            <HelpCircle className="w-4 h-4" />
            Справка
          </button>
        )}
        {onOpenFilter && (
          <button
            type="button"
            onClick={(e) => onOpenFilter(e.currentTarget as HTMLElement)}
            disabled={processing}
            className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            aria-label="Фильтр"
          >
            <Filter className="w-4 h-4" />
            Фильтр
          </button>
        )}
        {onUpdateDocuments && (
          <button
            onClick={onUpdateDocuments}
            disabled={processing}
            className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <FolderOpen className="w-4 h-4" />
            Добавить файлы
          </button>
        )}
        <button
          onClick={onAddColumns}
          disabled={processing}
          className="px-4 py-2 bg-white border border-[#3B82F6] text-[#3B82F6] text-sm font-medium rounded-lg hover:bg-[#EFF6FF] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <FileText className="w-4 h-4" />
          Добавить колонку
        </button>
      </div>

      <div className="flex items-center gap-2">
        {onToggleChat && (
          <button
            type="button"
            onClick={onToggleChat}
            disabled={processing}
            className={`px-4 py-2 text-sm font-medium rounded-lg transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 border ${
              chatOpen
                ? 'bg-[#EFF6FF] border-[#3B82F6] text-[#3B82F6]'
                : 'bg-white border-[#E5E7EB] text-[#6B7280] hover:bg-[#F3F4F6] hover:text-[#1F2937]'
            }`}
            aria-pressed={chatOpen}
          >
            <MessageSquare className="w-4 h-4" />
            Чат
          </button>
        )}
        {onExport && (
          <button
            onClick={onExport}
            disabled={processing}
            className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] text-sm font-medium rounded-lg hover:bg-[#F3F4F6] hover:text-[#1F2937] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <Download className="w-4 h-4" />
            Экспорт
          </button>
        )}
      </div>
    </div>
  )
}
