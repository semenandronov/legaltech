import { useMemo } from 'react'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { TabularDocumentViewer } from './TabularDocumentViewer'
import type { buildTabularViewerCellData } from '@/utils/tabularCellViewerData'
import { tabularHighlightRevision } from '@/utils/tabularCellViewerData'

export interface TabularSidePanelSelection {
  fileId: string
  fileType?: string
  fileName?: string
  columnId?: string
  columnLabel?: string
  reasoning?: string | null
  confidence?: number | null
  sourceReferenceIndex?: number
  hideDetailPanel?: boolean
  cellData: ReturnType<typeof buildTabularViewerCellData>
}

interface TabularSidePanelProps {
  selection: TabularSidePanelSelection
  caseId: string
  columnIds: string[]
  onClose: () => void
  onNavigateColumn?: (columnId: string) => void
  /** Встроить в grid справа от таблицы вместо fixed overlay */
  embedded?: boolean
}

export function TabularSidePanel({
  selection,
  caseId,
  columnIds,
  onClose,
  onNavigateColumn,
  embedded = false,
}: TabularSidePanelProps) {
  const currentColumnIndex = selection.columnId
    ? columnIds.indexOf(selection.columnId)
    : -1
  const hasPrev = currentColumnIndex > 0
  const hasNext = currentColumnIndex >= 0 && currentColumnIndex < columnIds.length - 1

  const cellValue =
    selection.cellData.cellValue?.trim() ||
    selection.cellData.verbatimExtract?.trim() ||
    '—'

  const docOnly = selection.hideDetailPanel === true

  const highlightRevision = useMemo(
    () =>
      tabularHighlightRevision({
        fileId: selection.fileId,
        columnId: selection.columnId,
        sourceReferenceIndex: selection.sourceReferenceIndex,
        verbatimExtract: selection.cellData.verbatimExtract,
        sourcePage: selection.cellData.sourcePage,
      }),
    [selection],
  )

  return (
    <div
      className={`ws-tabular-glass-panel${embedded ? ' ws-tabular-glass-panel--embedded' : ''}${docOnly ? ' ws-tabular-glass-panel--doc-only' : ''}`}
      role="dialog"
      aria-label={docOnly ? 'Документ' : 'Детали ячейки'}
    >
      <div className="ws-tabular-glass-panel-doc">
        <div className="ws-tabular-glass-panel-header">
          <span className="text-sm font-semibold truncate" style={{ color: 'var(--color-text-secondary)' }}>
            {selection.fileName || 'Документ'}
          </span>
          <button type="button" onClick={onClose} className="ws-input-mic-btn" aria-label="Закрыть">
            <X className="w-4 h-4" />
          </button>
        </div>
        {!docOnly && selection.cellData.verbatimExtract?.trim() && (
          <div className="px-3 pb-2 shrink-0">
            <div
              className="rounded-md border px-2 py-2 text-sm truncate"
              style={{
                borderColor: 'var(--color-border)',
                backgroundColor: 'var(--color-bg-secondary)',
                color: 'var(--color-text-muted)',
              }}
              title={selection.cellData.verbatimExtract}
            >
              {selection.cellData.verbatimExtract}
            </div>
          </div>
        )}
        <div className="flex-1 min-h-0 overflow-hidden">
          <TabularDocumentViewer
            key={selection.fileId}
            highlightRevision={highlightRevision}
            fileId={selection.fileId}
            caseId={caseId}
            fileType={selection.fileType}
            fileName={selection.fileName}
            cellData={selection.cellData}
            onClose={onClose}
          />
        </div>
      </div>

      {!docOnly && (
      <div className="ws-tabular-glass-panel-detail">
        <div className="ws-tabular-glass-panel-header">
          <div className="flex items-center gap-1 min-w-0">
            {onNavigateColumn && selection.columnId && columnIds.length > 1 && (
              <>
                <button
                  type="button"
                  disabled={!hasPrev}
                  onClick={() => hasPrev && onNavigateColumn(columnIds[currentColumnIndex - 1])}
                  className="ws-input-mic-btn"
                  aria-label="Предыдущая колонка"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  disabled={!hasNext}
                  onClick={() => hasNext && onNavigateColumn(columnIds[currentColumnIndex + 1])}
                  className="ws-input-mic-btn"
                  aria-label="Следующая колонка"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
                <span className="text-xs tabular-nums ml-1" style={{ color: 'var(--color-text-muted)' }}>
                  {currentColumnIndex + 1}/{columnIds.length}
                </span>
              </>
            )}
          </div>
          <button type="button" onClick={onClose} className="ws-input-mic-btn" aria-label="Закрыть панель">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="ws-tabular-glass-panel-section">
            <div className="ws-tabular-glass-panel-section-title">Колонка</div>
            <div className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
              {selection.columnLabel || '—'}
            </div>
          </div>

          <div className="ws-tabular-glass-panel-section">
            <div className="ws-tabular-glass-panel-section-title">Результат</div>
            <div className="ws-tabular-glass-panel-value">{cellValue}</div>
          </div>

          {selection.reasoning?.trim() && (
            <div className="ws-tabular-glass-panel-section">
              <div className="ws-tabular-glass-panel-section-title">Обоснование</div>
              <div className="ws-tabular-glass-panel-reasoning">
                {selection.reasoning}
              </div>
            </div>
          )}

          {selection.confidence != null && (
            <div className="ws-tabular-glass-panel-section">
              <div className="ws-tabular-glass-panel-section-title">Уверенность</div>
              <div className="ws-tabular-glass-panel-value">
                {Math.round(selection.confidence * 100)}%
              </div>
            </div>
          )}
        </div>
      </div>
      )}
    </div>
  )
}
