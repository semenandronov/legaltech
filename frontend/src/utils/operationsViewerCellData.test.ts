import { describe, expect, it } from 'vitest'
import { buildOperationsViewerCellData } from './operationsViewerCellData'
import type { OperationTransaction } from '@/services/operationsApi'

const baseTx: OperationTransaction = {
  id: 'tx-1',
  file_id: 'file-1',
  global_row_index: 0,
  row_columns: {
    Дата: '15.03.2024',
    Дебет: '1 000,00',
    Назначение: 'Оплата услуг',
  },
  page_start: 2,
  verbatim_row_text: '15.03.2024 | 1 000,00 | Оплата услуг',
  highlight_fragments: ['1 000,00', 'Оплата услуг'],
  source_references: [
    {
      page: 2,
      text: '15.03.2024 | 1 000,00 | Оплата услуг',
      bbox: { x0: 10, y0: 20, x1: 500, y1: 35 },
    },
  ],
}

describe('buildOperationsViewerCellData', () => {
  it('uses full row text and bbox for PDF highlight', () => {
    const out = buildOperationsViewerCellData(baseTx)
    expect(out.verbatimExtract).toContain('1 000,00')
    expect(out.highlightBBox).toEqual({ x0: 10, y0: 20, x1: 500, y1: 35 })
    expect(out.sourcePage).toBe(2)
    expect(out.verbatimAlternates?.length).toBeGreaterThan(0)
  })
})
