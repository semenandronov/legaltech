"use client"

import { useMemo } from 'react'
import { X } from 'lucide-react'
import { TabularDocumentViewer } from '@/components/TabularReview/TabularDocumentViewer'
import type { OperationTransaction } from '@/services/operationsApi'
import {
  buildOperationsViewerCellData,
  operationsHighlightRevision,
} from '@/utils/operationsViewerCellData'
import { fileTypeFromName } from '@/utils/fileType'

interface OperationsSidePanelProps {
  caseId: string
  transaction: OperationTransaction
  fileName: string
  onClose: () => void
}

export function OperationsSidePanel({
  caseId,
  transaction,
  fileName,
  onClose,
}: OperationsSidePanelProps) {
  const cellData = useMemo(() => buildOperationsViewerCellData(transaction), [transaction])
  const highlightRevision = useMemo(() => operationsHighlightRevision(transaction), [transaction])
  const fileType = fileTypeFromName(fileName)

  return (
    <aside className="ws-tabular-aside min-h-0">
      <div className="ws-tabular-glass-panel ws-tabular-glass-panel--embedded flex h-full min-h-0 flex-col" role="dialog" aria-label="Источник операции">
        <div className="ws-tabular-glass-panel-header shrink-0">
          <span className="truncate text-sm font-semibold" style={{ color: 'var(--color-text-secondary)' }}>
            {fileName}
          </span>
          <button type="button" onClick={onClose} className="ws-input-mic-btn" aria-label="Закрыть">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden">
          <TabularDocumentViewer
            fileId={transaction.file_id}
            caseId={caseId}
            fileName={fileName}
            fileType={fileType}
            citationPreview
            highlightRevision={highlightRevision}
            cellData={cellData}
          />
        </div>
      </div>
    </aside>
  )
}
