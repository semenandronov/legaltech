import { buildQuoteSearchCandidates } from './citationHighlight'

/**
 * Единый cellData для TabularDocumentViewer/PDF — как ChunkLabPage:
 * verbatim: quote (как во всплывашке цитаты) → quote_anchor → text_preview,
 * страница 1-based (sourcePageBasis: 'one'), bbox из индекса.
 */
export type ChunkLabViewerCellData = {
  verbatimExtract: string | null
  verbatimAlternates?: string[] | null
  highlightMode: 'verbatim'
  sourcePage: number | null
  sourcePageBasis: 'one'
  highlightBBox?: { x0?: number; y0?: number; x1?: number; y1?: number }
  highlightBBoxRegions?: Array<{ x0?: number; y0?: number; x1?: number; y1?: number }>
  highlightPageBBox?: { width?: number; height?: number }
  charStart?: number | null
  charEnd?: number | null
}

export function buildChunkLabViewerCellData(parts: {
  quote_anchor?: string | null
  quote?: string | null
  text_preview?: string | null
  page?: number | null
  bbox?: { x0?: number; y0?: number; x1?: number; y1?: number }
  bbox_regions?: Array<{ x0?: number; y0?: number; x1?: number; y1?: number }>
  page_bbox?: { width?: number; height?: number }
  char_start?: number | null
  char_end?: number | null
}): ChunkLabViewerCellData {
  const quote = (parts.quote && String(parts.quote).trim()) || ''
  const anchor = (parts.quote_anchor && String(parts.quote_anchor).trim()) || ''
  const preview = (parts.text_preview && String(parts.text_preview).trim()) || ''
  // Совпадает с InlineCitationAdapter (quote first). Длинный aligned quote_anchor часто ≠ цитате в ответе.
  const extract =
    (quote.length >= 8 && quote) ||
    (anchor && anchor) ||
    (quote && quote) ||
    (preview && preview) ||
    null

  const alternates = buildQuoteSearchCandidates(null, [anchor, preview, quote]).filter(
    (candidate) => candidate !== extract,
  )

  return {
    verbatimExtract: extract,
    verbatimAlternates: alternates.length > 0 ? alternates : null,
    highlightMode: 'verbatim',
    sourcePage: parts.page ?? null,
    sourcePageBasis: 'one',
    highlightBBox: parts.bbox,
    highlightBBoxRegions: parts.bbox_regions,
    highlightPageBBox: parts.page_bbox,
    charStart: parts.char_start ?? null,
    charEnd: parts.char_end ?? null,
  }
}

/** Ключ смены подсветки без перезагрузки файла (тот же source_id). */
export function citationHighlightRevision(parts: {
  citation_id?: string | null
  chunk_id?: string | null
  page?: number | null
  char_start?: number | null
  char_end?: number | null
  quote?: string | null
  quote_anchor?: string | null
}): string {
  return [
    parts.citation_id,
    parts.chunk_id,
    parts.page,
    parts.char_start,
    parts.char_end,
    parts.quote,
    parts.quote_anchor,
  ]
    .map((value) => (value == null ? '' : String(value)))
    .join(':')
}
