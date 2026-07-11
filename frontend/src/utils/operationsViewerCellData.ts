/**
 * PDF viewer payload for operations rows — CITATION_CONTRACT_V1 aligned with Tabular Review.
 */
import type { SourceReference } from '@/services/tabularReviewApi'
import type { OperationTransaction } from '@/services/operationsApi'
import {
  buildTabularViewerCellData,
  tabularHighlightRevision,
  type TabularViewerCellData,
} from '@/utils/tabularCellViewerData'

export type OperationsViewerCellData = TabularViewerCellData & {
  verbatimAlternates?: string[] | null
}

export function buildOperationsViewerCellData(
  transaction: OperationTransaction,
): OperationsViewerCellData {
  const refs: SourceReference[] = (transaction.source_references ?? []).map((ref) => ({
    page: ref.page ?? null,
    section: ref.section ?? null,
    text: ref.text,
    bbox: ref.bbox ?? null,
    page_bbox: ref.page_bbox ?? null,
  }))

  const base = buildTabularViewerCellData({
    fileId: transaction.file_id,
    details: null,
    click: {
      verbatimExtract: transaction.verbatim_row_text || transaction.description,
      sourcePage: transaction.page_start ?? undefined,
      sourceReferences: refs,
      highlightMode: 'verbatim',
    },
  })

  const alternates = (transaction.highlight_fragments ?? []).filter(
    (fragment) => fragment && fragment !== base.verbatimExtract,
  )

  return {
    ...base,
    cellValue:
      transaction.description ||
      transaction.amount_raw ||
      (transaction.amount_rub != null ? String(transaction.amount_rub) : null),
    verbatimAlternates: alternates.length > 0 ? alternates : null,
  }
}

export function operationsHighlightRevision(transaction: OperationTransaction): string {
  return tabularHighlightRevision({
    fileId: transaction.file_id,
    verbatimExtract: transaction.verbatim_row_text || transaction.description,
    sourcePage: transaction.page_start,
  })
}
