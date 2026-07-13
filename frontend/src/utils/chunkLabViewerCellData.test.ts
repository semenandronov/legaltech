import { describe, expect, it } from 'vitest'
import { buildChunkLabViewerCellData } from './chunkLabViewerCellData'

describe('buildChunkLabViewerCellData', () => {
  it('prefers highlight_targets over labeled Col: value quote', () => {
    const out = buildChunkLabViewerCellData({
      quote: 'Дата: 24.06.2026\nСумма: 1000.50\nНазначение платежа: Оплата по договору 1',
      quote_anchor: 'Дата: 24.06.2026\nСумма: 1000.50\nНазначение платежа: Оплата по договору 1',
      highlight_targets: ['Оплата по договору 1', '1000.50', '24.06.2026'],
    })
    expect(out.verbatimExtract).toBe('Оплата по договору 1')
    expect(out.verbatimAlternates).toContain('1000.50')
  })
})
