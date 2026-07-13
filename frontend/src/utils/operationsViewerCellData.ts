/**
 * PDF/HTML viewer payload for operations rows — CITATION_CONTRACT_V1 aligned with Tabular Review.
 */
import type { SourceReference } from '@/services/tabularReviewApi'
import type { OperationTransaction } from '@/services/operationsApi'
import {
  buildTabularViewerCellData,
  tabularHighlightRevision,
  type TabularViewerCellData,
} from '@/utils/tabularCellViewerData'
import { buildQuoteSearchCandidates } from '@/utils/citationHighlight'

export type OperationsViewerCellData = TabularViewerCellData & {
  verbatimAlternates?: string[] | null
}

function looksLikeLabeledRow(text: string): boolean {
  const t = (text || '').trim()
  if (!t) return false
  const lines = t.split(/\n/).map((l) => l.trim()).filter(Boolean)
  return lines.filter((l) => /^[^:]{1,40}:\s+\S/.test(l)).length >= 2
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

  const fragments = (transaction.highlight_fragments ?? []).filter(
    (fragment) => fragment && String(fragment).trim().length >= 2,
  )
  const description = (transaction.description || '').trim()
  const amount = (transaction.amount_raw || '').trim()
  const verbatim = (transaction.verbatim_row_text || '').trim()

  // Prefer bare cell text for HTML Excel preview; keep labeled verbatim as alternate.
  const primary =
    (description && description) ||
    (fragments[0] && !looksLikeLabeledRow(fragments[0]) ? fragments[0] : null) ||
    (amount && amount) ||
    (verbatim && !looksLikeLabeledRow(verbatim) ? verbatim : null) ||
    fragments[0] ||
    verbatim ||
    null

  const base = buildTabularViewerCellData({
    fileId: transaction.file_id,
    details: null,
    click: {
      verbatimExtract: primary,
      sourcePage: transaction.page_start ?? undefined,
      sourceReferences: refs,
      highlightMode: 'verbatim',
    },
  })

  const alternates = buildQuoteSearchCandidates(null, [
    ...fragments,
    description,
    amount,
    verbatim,
  ]).filter((candidate) => candidate !== primary)

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
    verbatimExtract:
      transaction.description ||
      transaction.highlight_fragments?.[0] ||
      transaction.verbatim_row_text ||
      transaction.description,
    sourcePage: transaction.page_start,
  })
}
