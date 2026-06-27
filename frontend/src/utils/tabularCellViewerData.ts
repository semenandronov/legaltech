/**
 * Единая сборка payload для TabularDocumentViewer из cell details + клика по источнику.
 * CITATION_CONTRACT_V1: page 1-based, bbox на один выбранный фрагмент.
 */
import type { CellDetails, SourceReference } from '@/services/tabularReviewApi'

export type TabularCellClickPayload = {
  verbatimExtract?: string | null
  sourcePage?: number | null
  sourceSection?: string | null
  columnType?: string
  highlightMode?: 'verbatim' | 'page' | 'none'
  sourceReferences?: SourceReference[]
  /** Какой элемент source_references открыть в viewer (кнопка «Источник N»). */
  sourceReferenceIndex?: number
  docId?: string | null
  charStart?: number | null
  charEnd?: number | null
  /** Не показывать правую панель с ответом/обоснованием (уже в popover под ячейкой) */
  hideDetailPanel?: boolean
}

export type TabularViewerCellData = {
  verbatimExtract?: string | null
  cellValue?: string | null
  sourcePage?: number | null
  sourceSection?: string | null
  columnType?: string
  sourcePageBasis: 'one'
  highlightMode: 'verbatim' | 'page' | 'none'
  sourceReferences: SourceReference[]
  highlightBBox?: { x0: number; y0: number; x1: number; y1: number }
  highlightBBoxRegions?: Array<{ x0: number; y0: number; x1: number; y1: number }>
  highlightPageBBox?: { width: number; height: number }
  docId?: string | null
  charStart?: number | null
  charEnd?: number | null
}

type BBox = { x0: number; y0: number; x1: number; y1: number }

function isValidBBox(b: unknown): b is BBox {
  if (!b || typeof b !== 'object') return false
  const o = b as Record<string, unknown>
  return (
    typeof o.x0 === 'number' &&
    typeof o.y0 === 'number' &&
    typeof o.x1 === 'number' &&
    typeof o.y1 === 'number' &&
    o.x1 > o.x0 &&
    o.y1 > o.y0
  )
}

export function bboxFromReference(ref: SourceReference | undefined): BBox | undefined {
  if (!ref?.bbox || !isValidBBox(ref.bbox)) return undefined
  return ref.bbox
}

/** Нормализует legacy-ячейки без source_references в один синтетический ref. */
export function normalizeCellSourceReferences(
  details: Pick<
    CellDetails,
    'source_references' | 'verbatim_extract' | 'source_page' | 'source_section'
  >,
  fallbackText?: string | null,
): SourceReference[] {
  if (details.source_references && details.source_references.length > 0) {
    return details.source_references
  }
  const text = (details.verbatim_extract || fallbackText || '').trim()
  if (!text && details.source_page == null && !details.source_section) {
    return []
  }
  return [
    {
      page: details.source_page,
      section: details.source_section,
      text: text || fallbackText || '',
    },
  ]
}

export function resolveActiveSourceReference(
  refs: SourceReference[],
  index?: number,
): SourceReference | undefined {
  if (!refs.length) return undefined
  if (
    typeof index === 'number' &&
    index >= 0 &&
    index < refs.length
  ) {
    return refs[index]
  }
  return refs[0]
}

export function buildTabularViewerCellData(params: {
  details: CellDetails | null
  click: TabularCellClickPayload
  fileId: string
}): TabularViewerCellData {
  const { details, click, fileId } = params

  const refs: SourceReference[] =
    click.sourceReferences?.length
      ? click.sourceReferences
      : details
        ? normalizeCellSourceReferences(details, details.cell_value)
        : []

  const active = resolveActiveSourceReference(refs, click.sourceReferenceIndex)

  const verbatimExtract =
    (active?.text && String(active.text).trim()) ||
    (click.verbatimExtract && String(click.verbatimExtract).trim()) ||
    details?.verbatim_extract ||
    null

  const sourcePage =
    active?.page ?? click.sourcePage ?? details?.source_page ?? null
  const sourceSection =
    active?.section ?? click.sourceSection ?? details?.source_section ?? null

  const highlightMode: TabularViewerCellData['highlightMode'] =
    click.highlightMode ||
    details?.highlight_mode ||
    (verbatimExtract ? 'verbatim' : sourcePage != null ? 'page' : 'none')

  const bbox = bboxFromReference(active)
  const refIndex = click.sourceReferenceIndex ?? 0
  const usePrimaryCharSpan =
    refIndex === 0 &&
    (click.charStart != null || details?.primary_source_char_start != null)

  return {
    verbatimExtract,
    cellValue: details?.cell_value ?? null,
    sourcePage,
    sourceSection,
    columnType: click.columnType ?? details?.column_type,
    sourcePageBasis: 'one',
    highlightMode,
    sourceReferences: refs,
    highlightBBox: bbox,
    highlightBBoxRegions: bbox ? [bbox] : undefined,
    highlightPageBBox: active?.page_bbox ?? undefined,
    docId: click.docId ?? details?.primary_source_doc_id ?? fileId,
    charStart: usePrimaryCharSpan
      ? (click.charStart ?? details?.primary_source_char_start ?? undefined)
      : undefined,
    charEnd: usePrimaryCharSpan
      ? (click.charEnd ?? details?.primary_source_char_end ?? undefined)
      : undefined,
  }
}

/** Ключ смены подсветки без перезагрузки файла (tabular side panel). */
export function tabularHighlightRevision(parts: {
  fileId: string
  columnId?: string
  sourceReferenceIndex?: number
  verbatimExtract?: string | null
  sourcePage?: number | null
}): string {
  return [
    parts.fileId,
    parts.columnId,
    parts.sourceReferenceIndex ?? 0,
    parts.sourcePage,
    parts.verbatimExtract?.slice(0, 80) ?? '',
  ]
    .map((value) => (value == null ? '' : String(value)))
    .join(':')
}

export function sourceReferenceButtonLabel(
  ref: SourceReference,
  index: number,
  total: number,
): string {
  if (total <= 1) return 'View Source'
  const pagePart = ref.page != null ? ` · стр. ${ref.page}` : ''
  return `Источник ${index + 1}${pagePart}`
}

export function truncateQuote(text: string, maxLen = 80): string {
  const t = text.trim()
  if (t.length <= maxLen) return t
  return `${t.slice(0, maxLen)}…`
}
