import type { CellDetails, SourceReference, TabularCell } from '@/services/tabularReviewApi'
import { normalizeCellSourceReferences } from '@/utils/tabularCellViewerData'
import { preprocessTabularCitations } from '@/utils/tabularCitationUtils'

export interface CellCitationItem {
  index: number
  page?: number | null
  quote: string
  sourceRef?: SourceReference
}

/** Список цитат: столько ссылок, сколько цитат в ответе ИИ (или в source_references). */
export function buildCellCitationList(
  cellValue: string,
  details?: Pick<
    CellDetails,
    'cell_value' | 'source_references' | 'verbatim_extract' | 'source_page' | 'source_section'
  > |
    Pick<
      TabularCell,
      'cell_value' | 'source_references' | 'verbatim_extract' | 'source_page' | 'source_section'
    > |
    null,
): CellCitationItem[] {
  const sourceText = (details?.cell_value ?? cellValue) || ''
  const { citations: parsed } = preprocessTabularCitations(sourceText)
  const apiRefs = details?.source_references ?? []

  if (parsed.length > 0) {
    return parsed.map((citation, index) => ({
      index,
      page: apiRefs[index]?.page ?? citation.page,
      quote: (apiRefs[index]?.text ?? citation.quote).trim(),
      sourceRef: apiRefs[index],
    }))
  }

  if (apiRefs.length > 0) {
    return apiRefs.map((ref, index) => ({
      index,
      page: ref.page,
      quote: (ref.text ?? '').trim(),
      sourceRef: ref,
    }))
  }

  if (!details) return []

  return normalizeCellSourceReferences(details, cellValue).map((ref, index) => ({
    index,
    page: ref.page,
    quote: (ref.text ?? '').trim(),
    sourceRef: ref,
  }))
}
