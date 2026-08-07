import { describe, expect, it } from 'vitest'
import type { TableData } from '../services/tabularReviewApi'
import {
  countResolvedColumnCells,
  isColumnExtractionDone,
  isInFlightColumnCellStatus,
} from './tabularColumnExtractionPoll'

const table = (cells: Record<string, { status: string }>): TableData => ({
  review: { id: 'r1', name: 'T', status: 'draft' },
  columns: [{ id: 'col1', column_label: 'A', column_type: 'text', prompt: 'p', order_index: 0 }],
  rows: [
    { file_id: 'f1', file_name: 'a.pdf', status: 'not_reviewed', cells: { col1: cells.f1 as any } },
    { file_id: 'f2', file_name: 'b.pdf', status: 'not_reviewed', cells: { col1: cells.f2 as any } },
  ],
})

describe('tabularColumnExtractionPoll', () => {
  it('treats pending and processing as in-flight', () => {
    expect(isInFlightColumnCellStatus('pending')).toBe(true)
    expect(isInFlightColumnCellStatus('processing')).toBe(true)
    expect(isInFlightColumnCellStatus('completed')).toBe(false)
    expect(isInFlightColumnCellStatus('skipped')).toBe(false)
  })

  it('counts only non-in-flight cells', () => {
    const data = table({
      f1: { status: 'completed' },
      f2: { status: 'pending' },
    })
    expect(countResolvedColumnCells(data, 'col1')).toBe(1)

    const rerun = table({
      f1: { status: 'processing' },
      f2: { status: 'processing' },
    })
    expect(countResolvedColumnCells(rerun, 'col1')).toBe(0)
  })

  it('detects completion when all rows resolved', () => {
    const pending = table({
      f1: { status: 'pending' },
      f2: { status: 'pending' },
    })
    expect(isColumnExtractionDone(pending, 'col1', 2)).toBe(false)

    const processing = table({
      f1: { status: 'processing' },
      f2: { status: 'processing' },
    })
    expect(isColumnExtractionDone(processing, 'col1', 2)).toBe(false)

    const done = table({
      f1: { status: 'completed' },
      f2: { status: 'needs_review' },
    })
    expect(isColumnExtractionDone(done, 'col1', 2)).toBe(true)
  })
})
