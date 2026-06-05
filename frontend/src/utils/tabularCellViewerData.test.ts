import { describe, expect, it } from 'vitest'
import {
  buildTabularViewerCellData,
  normalizeCellSourceReferences,
  sourceReferenceButtonLabel,
} from './tabularCellViewerData'
import type { CellDetails } from '@/services/tabularReviewApi'

describe('normalizeCellSourceReferences', () => {
  it('returns API refs when present', () => {
    const refs = normalizeCellSourceReferences({
      source_references: [{ text: 'a', page: 1 }],
      verbatim_extract: null,
      source_page: null,
      source_section: null,
    })
    expect(refs).toHaveLength(1)
    expect(refs[0].text).toBe('a')
  })

  it('synthesizes one ref from legacy verbatim + page', () => {
    const refs = normalizeCellSourceReferences({
      source_references: [],
      verbatim_extract: 'цитата',
      source_page: 2,
      source_section: '§1',
    })
    expect(refs).toEqual([{ page: 2, section: '§1', text: 'цитата' }])
  })
})

describe('buildTabularViewerCellData', () => {
  const details: CellDetails = {
    id: 'c1',
    cell_value: 'ответ',
    verbatim_extract: 'legacy',
    source_page: 1,
    source_section: null,
    status: 'done',
    source_references: [
      { text: 'первый', page: 2, bbox: { x0: 1, y0: 2, x1: 3, y1: 4 } },
      { text: 'второй', page: 3, bbox: { x0: 10, y0: 20, x1: 30, y1: 40 } },
    ],
  }

  it('highlights only the selected source reference', () => {
    const out = buildTabularViewerCellData({
      details,
      fileId: 'f1',
      click: {
        sourceReferences: details.source_references,
        sourceReferenceIndex: 1,
      },
    })
    expect(out.verbatimExtract).toBe('второй')
    expect(out.sourcePage).toBe(3)
    expect(out.highlightBBox).toEqual({ x0: 10, y0: 20, x1: 30, y1: 40 })
    expect(out.highlightBBoxRegions).toHaveLength(1)
  })

  it('defaults to first reference when index omitted', () => {
    const out = buildTabularViewerCellData({
      details,
      fileId: 'f1',
      click: { sourceReferences: details.source_references },
    })
    expect(out.verbatimExtract).toBe('первый')
    expect(out.sourcePage).toBe(2)
  })
})

describe('sourceReferenceButtonLabel', () => {
  it('uses View Source for single ref', () => {
    expect(sourceReferenceButtonLabel({ text: 'x', page: 1 }, 0, 1)).toBe('View Source')
  })

  it('numbers multiple refs', () => {
    expect(sourceReferenceButtonLabel({ text: 'x', page: 5 }, 1, 3)).toBe('Источник 2 · стр. 5')
  })
})
