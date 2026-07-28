/**
 * Единая сборка payload для TabularDocumentViewer из cell details + клика по источнику.
 * CITATION_CONTRACT_V1: page 1-based, bbox на один выбранный фрагмент.
 */
import type { CellDetails, SourceReference } from '@/services/tabularReviewApi'
import { buildQuoteSearchCandidates } from './citationHighlight'

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
  verbatimAlternates?: string[] | null
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

function sameBBox(a: unknown, b: unknown): boolean {
  if (!isValidBBox(a) || !isValidBBox(b)) return false
  return a.x0 === b.x0 && a.y0 === b.y0 && a.x1 === b.x1 && a.y1 === b.y1
}

/**
 * Legacy tabular cells often stamp the same char span / bbox from the top RAG chunk
 * onto every source_reference. Those geometries open the wrong place for secondary quotes.
 * Prefer text-layer search when provenance is clearly shared across different quotes.
 *
 * Geometry-first contract otherwise: trusted unique bbox on the active ref wins;
 * text search is only a fallback when this returns false.
 */
export function isTrustedSourceReferenceHighlight(
  active: SourceReference | undefined,
  allRefs: SourceReference[],
): boolean {
  if (!active || !isValidBBox(active.bbox)) return false
  const activeText = (active.text || '').trim().toLowerCase()
  const cs = active.char_start
  const ce = active.char_end
  const siblings = allRefs.filter((ref) => ref !== active)
  if (siblings.length === 0) return true

  if (cs != null && ce != null) {
    const sharedSpan = siblings.some(
      (ref) =>
        ref.char_start === cs &&
        ref.char_end === ce &&
        (ref.text || '').trim().toLowerCase() !== activeText,
    )
    if (sharedSpan) return false
  }

  const sharedBbox = siblings.some(
    (ref) =>
      sameBBox(ref.bbox, active.bbox) &&
      (ref.text || '').trim().toLowerCase() !== activeText,
  )
  if (sharedBbox) return false

  return true
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

  const trustGeometry = isTrustedSourceReferenceHighlight(active, refs)
  const bbox = trustGeometry ? bboxFromReference(active) : undefined
  const refIndex = click.sourceReferenceIndex ?? 0
  const activeText = (active?.text || '').trim().toLowerCase()
  const sharedCharSpan = Boolean(
    active &&
      active.char_start != null &&
      active.char_end != null &&
      refs.some(
        (ref) =>
          ref !== active &&
          ref.char_start === active.char_start &&
          ref.char_end === active.char_end &&
          (ref.text || '').trim().toLowerCase() !== activeText,
      ),
  )
  const fallbackCharStart = click.charStart ?? details?.primary_source_char_start ?? undefined
  const fallbackCharEnd = click.charEnd ?? details?.primary_source_char_end ?? undefined
  const charStart = sharedCharSpan
    ? undefined
    : active?.char_start != null
      ? active.char_start
      : refIndex === 0
        ? fallbackCharStart
        : undefined
  const charEnd = sharedCharSpan
    ? undefined
    : active?.char_end != null
      ? active.char_end
      : refIndex === 0
        ? fallbackCharEnd
        : undefined
  const verbatimAlternates = buildQuoteSearchCandidates(
    null,
    [
      click.verbatimExtract,
      details?.verbatim_extract,
      details?.cell_value,
      ...refs.map((ref, index) => (index === refIndex ? null : ref.text)),
    ],
  ).filter((candidate) => candidate !== verbatimExtract)

  return {
    verbatimExtract,
    verbatimAlternates: verbatimAlternates.length > 0 ? verbatimAlternates : null,
    cellValue: details?.cell_value ?? null,
    sourcePage,
    sourceSection,
    columnType: click.columnType ?? details?.column_type,
    sourcePageBasis: 'one',
    highlightMode,
    sourceReferences: refs,
    highlightBBox: bbox,
    highlightBBoxRegions: bbox ? [bbox] : undefined,
    highlightPageBBox: bbox ? active?.page_bbox ?? undefined : undefined,
    docId: active?.doc_id ?? click.docId ?? details?.primary_source_doc_id ?? fileId,
    charStart,
    charEnd,
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
