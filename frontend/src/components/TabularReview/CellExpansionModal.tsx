import React from "react"
import Modal from "@/components/UI/Modal"
import { TabularCell, CellDetails } from "@/services/tabularReviewApi"
import { Badge } from "@/components/UI/Badge"
import { FileText, AlertCircle, CheckCircle2 } from "lucide-react"

interface CellExpansionModalProps {
  isOpen: boolean
  onClose: () => void
  cell: TabularCell
  cellDetails: CellDetails | null
  fileName: string
  columnLabel: string
  loading: boolean
}

export function CellExpansionModal({
  isOpen,
  onClose,
  cell,
  cellDetails,
  fileName,
  columnLabel,
  loading,
}: CellExpansionModalProps) {
  const details = cellDetails || {
    id: "",
    cell_value: cell.cell_value,
    verbatim_extract: cell.verbatim_extract,
    reasoning: cell.reasoning,
    confidence_score: cell.confidence_score,
    source_page: cell.source_page,
    source_section: cell.source_section,
    status: cell.status,
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={columnLabel} size="lg">
      <div className="space-y-6">
        {/* Source Document */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <FileText className="w-4 h-4 text-muted-foreground" />
            <span className="text-sm font-medium text-muted-foreground">Источник</span>
          </div>
          <p className="text-sm">{fileName}</p>
          {details.source_page && (
            <p className="text-xs text-muted-foreground mt-1">
              Страница: {details.source_page}
              {details.source_section && `, Раздел: ${details.source_section}`}
            </p>
          )}
        </div>

        {/* Answer */}
        <div>
          <h4 className="text-sm font-medium mb-2">Ответ</h4>
          <div className="bg-muted/50 rounded-md p-3">
            <p className="text-sm">{details.cell_value || "N/A"}</p>
          </div>
        </div>

        {/* Verbatim Extract */}
        {details.verbatim_extract && (
          <div>
            <h4 className="text-sm font-medium mb-2">Точная цитата (Verbatim)</h4>
            <div className="bg-blue-50 dark:bg-blue-950/20 rounded-md p-3 border border-blue-200 dark:border-blue-900">
              <p className="text-sm font-mono">{details.verbatim_extract}</p>
            </div>
          </div>
        )}

        {/* Reasoning */}
        {details.reasoning && (
          <div>
            <h4 className="text-sm font-medium mb-2">Объяснение (Reasoning)</h4>
            <div className="bg-muted/50 rounded-md p-3">
              <p className="text-sm text-muted-foreground">{details.reasoning}</p>
            </div>
          </div>
        )}

        {/* Confidence Score */}
        {details.confidence_score !== null && details.confidence_score !== undefined && (
          <div>
            <h4 className="text-sm font-medium mb-2">Уверенность (Confidence)</h4>
            <div className="flex items-center gap-3">
              <div className="flex-1 bg-muted rounded-full h-2">
                <div
                  className="bg-primary h-2 rounded-full transition-all"
                  style={{ width: `${details.confidence_score * 100}%` }}
                />
              </div>
              <span className="text-sm font-medium">
                {Math.round(details.confidence_score * 100)}%
              </span>
              {details.confidence_score >= 0.9 ? (
                <Badge variant="completed">
                  <CheckCircle2 className="w-3 h-3 mr-1" />
                  Высокая
                </Badge>
              ) : details.confidence_score >= 0.7 ? (
                <Badge variant="pending">Средняя</Badge>
              ) : (
                <Badge variant="flagged">
                  <AlertCircle className="w-3 h-3 mr-1" />
                  Низкая
                </Badge>
              )}
            </div>
          </div>
        )}

        {/* Status */}
        <div>
          <h4 className="text-sm font-medium mb-2">Статус</h4>
          <Badge
            variant={
              details.status === "completed" || details.status === "reviewed"
                ? "completed"
                : details.status === "processing"
                ? "pending"
                : "pending"
            }
          >
            {details.status === "completed" || details.status === "reviewed"
              ? "Завершено"
              : details.status === "processing"
              ? "Обработка"
              : "Ожидание"}
          </Badge>
        </div>

        {loading && (
          <div className="text-center py-4">
            <p className="text-sm text-muted-foreground">Загрузка деталей...</p>
          </div>
        )}
      </div>
    </Modal>
  )
}

