import { Button } from "@/components/UI/Button"
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
}: TabularReviewToolbarProps) {
  return (
    <div className="flex items-center justify-between py-4 border-b">
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onAddDocuments}
          disabled={processing}
        >
          <Plus className="w-4 h-4 mr-2" />
          Add documents
        </Button>
        {onUpdateDocuments && (
          <Button
            variant="outline"
            size="sm"
            onClick={onUpdateDocuments}
            disabled={processing}
          >
            <FolderOpen className="w-4 h-4 mr-2" />
            Изменить документы
          </Button>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={onAddColumns}
          disabled={processing}
        >
          <FileText className="w-4 h-4 mr-2" />
          Add columns
        </Button>
        {onTemplates && (
          <Button
            variant="outline"
            size="sm"
            onClick={onTemplates}
            disabled={processing}
          >
            <LayoutTemplate className="w-4 h-4 mr-2" />
            Templates
          </Button>
        )}
      </div>
      
      <div className="flex items-center gap-2">
        <Button
          variant="default"
          size="sm"
          onClick={onRunAll}
          disabled={processing}
        >
          <Play className="w-4 h-4 mr-2" />
          {processing ? "Обработка..." : "Run all"}
        </Button>
        
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" disabled={processing}>
              <Download className="w-4 h-4 mr-2" />
              Download
              <ChevronDown className="w-4 h-4 ml-2" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => onDownload?.("csv")}>
              CSV
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onDownload?.("excel")}>
              Excel
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        
        <Button
          variant="outline"
          size="sm"
          onClick={onShare}
          disabled={processing}
        >
          <Share2 className="w-4 h-4 mr-2" />
          Share
        </Button>
      </div>
    </div>
  )
}

