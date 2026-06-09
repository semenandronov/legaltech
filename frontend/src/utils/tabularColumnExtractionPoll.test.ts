import { describe, expect, it } from 'vitest'
import type { TableData } from '../services/tabularReviewApi'
import { countResolvedColumnCells, isColumnExtractionDone } from './tabularColumnExtractionPoll'

const table = (cells: Record<string, { status: string }>): TableData => ({
  review: { id: 'r1', name: 'T', status: 'draft' },
  columns: [{ id: 'col1', column_label: 'A', column_type: 'text', prompt: 'p', order_index: 0 }],
  rows: [
    { file_id: 'f1', file_name: 'a.pdf', status: 'not_reviewed', cells: { col1: cells.f1 as any } },
    { file_id: 'f2', file_name: 'b.pdf', status: 'not_reviewed', cells: { col1: cells.f2 as any } },
  ],
})

describe('tabularColumnExtractionPoll', () => {
  it('counts only non-pending cells', () => {
    const data = table({
      f1: { status: 'completed' },
      f2: { status: 'pending' },
    })
    expect(countResolvedColumnCells(data, 'col1')).toBe(1)
  })

  it('detects completion when all rows resolved', () => {
    const pending = table({
      f1: { status: 'pending' },
      f2: { status: 'pending' },
    })
    expect(isColumnExtractionDone(pending, 'col1', 2)).toBe(false)

    const done = table({
      f1: { status: 'completed' },
      f2: { status: 'needs_review' },
    })
    expect(isColumnExtractionDone(done, 'col1', 2)).toBe(true)
  })
})
