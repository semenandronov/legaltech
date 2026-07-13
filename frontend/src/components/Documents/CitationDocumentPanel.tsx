import { useMemo } from 'react'
import { X } from 'lucide-react'
import type { SourceInfo } from '@/services/api'
import { TabularDocumentViewer } from '@/components/TabularReview/TabularDocumentViewer'
import { CitationQuoteBanner } from '@/components/Documents/CitationQuoteBanner'
import {
  buildChunkLabViewerCellData,
  citationHighlightRevision,
} from '@/utils/chunkLabViewerCellData'
import { fileTypeFromName } from '@/utils/fileType'

export interface CitationDocumentPanelProps {
  source: SourceInfo
  caseId: string
  onClose: () => void
  fileApiBase?: string
  citationPreview?: boolean
  className?: string
}

/**
 * Единая боковая панель просмотра документа по цитате (case + global assistant).
 * Файл монтируется по source_id; смена цитаты того же файла только обновляет подсветку.
 */
export function CitationDocumentPanel({
  source,
  caseId,
  onClose,
  fileApiBase,
  citationPreview = true,
  className = '',
}: CitationDocumentPanelProps) {
  const cellData = useMemo(
    () =>
      buildChunkLabViewerCellData({
        quote_anchor: source.quote_anchor,
        quote: source.quote,
        text_preview: source.text_preview,
        highlight_targets: source.highlight_targets,
        page: source.page ?? null,
        bbox: source.bbox,
        bbox_regions: source.bbox_regions,
        page_bbox: source.page_bbox,
        char_start: source.char_start,
        char_end: source.char_end,
      }),
    [source],
  )

  const highlightRevision = useMemo(
    () =>
      citationHighlightRevision({
        citation_id: source.citation_id,
        chunk_id: source.chunk_id,
        page: source.page,
        char_start: source.char_start,
        char_end: source.char_end,
        quote: source.quote,
        quote_anchor: source.quote_anchor,
        highlight_targets: source.highlight_targets,
      }),
    [source],
  )

  const displayName = source.file || source.title || 'Документ'
  const quoteLabel =
    cellData.verbatimExtract || source.quote || source.text_preview || ''

  if (!source.source_id) {
    return (
      <div className={`flex h-full min-h-0 flex-col ${className}`}>
        <PanelHeader title={displayName} onClose={onClose} />
        <div className="flex-1 overflow-y-auto p-6">
          {quoteLabel ? (
            <CitationQuoteBanner quote={quoteLabel} page={source.page} className="rounded-lg border" />
          ) : (
            <p className="text-sm text-gray-500">Текст недоступен</p>
          )}
          <p className="mt-3 text-xs text-gray-400">
            Для навигации по документу прикрепите файл через «Из дел»
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className={`flex h-full min-h-0 flex-col ${className}`}>
      <PanelHeader title={displayName} onClose={onClose} />
      {quoteLabel ? (
        <CitationQuoteBanner quote={quoteLabel} page={source.page} />
      ) : null}
      <div className="min-h-0 flex-1 overflow-hidden">
        <TabularDocumentViewer
          key={source.source_id}
          highlightRevision={highlightRevision}
          fileId={source.source_id}
          caseId={caseId}
          fileType={fileTypeFromName(source.file || source.title)}
          fileName={displayName}
          cellData={cellData}
          fileApiBase={fileApiBase}
          citationPreview={citationPreview}
        />
      </div>
    </div>
  )
}

function PanelHeader({ title, onClose }: { title: string; onClose: () => void }) {
  return (
    <div className="flex shrink-0 items-center justify-between border-b border-gray-200 px-4 py-3">
      <span className="truncate text-sm font-medium text-gray-700">{title}</span>
      <button
        type="button"
        onClick={onClose}
        className="rounded-full p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700"
        aria-label="Закрыть"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}
