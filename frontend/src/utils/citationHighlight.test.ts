import { describe, expect, it } from 'vitest'
import {
  buildQuoteSearchCandidates,
  findNormSegmentInPlain,
  findQuoteMatchAmongCandidates,
  findQuoteMatchInPlain,
  normalizeForQuoteMatch,
  scoreTableRowsForCandidates,
  splitQuoteSegments,
} from './citationHighlight'

describe('citationHighlight', () => {
  it('normalizeForQuoteMatch убирает пунктуацию и пробелы', () => {
    expect(normalizeForQuoteMatch('Ст. 123, п. 4')).toBe('ст123п4')
  })

  it('splitQuoteSegments режет по многоточию', () => {
    expect(splitQuoteSegments('первая часть...вторая часть длинная')).toHaveLength(2)
  })

  it('findQuoteMatchInPlain находит при расхождении пунктуации', () => {
    const doc = 'Договор заключён между Сторонами в соответствии с законом.'
    const quote = 'Договор заключен между Сторонами'
    const hit = findQuoteMatchInPlain(doc, quote)
    expect(hit).not.toBeNull()
    expect(doc.slice(hit!.start, hit!.end)).toContain('Договор')
  })

  it('findNormSegmentInPlain маппит координаты в исходный текст', () => {
    const doc = 'abc-def ghi'
    const hit = findNormSegmentInPlain(doc, 'defghi')
    expect(hit).toEqual({ start: 4, end: 11 })
  })

  it('findQuoteMatchAmongCandidates skips labeled row and hits cell value', () => {
    const htmlText = 'ДатаСуммаНазначение платежа24.06.20261000.50Оплата по договору 1'
    const labeled = 'Дата: 24.06.2026\nСумма: 1000.50\nНазначение платежа: Оплата по договору 1'
    const hit = findQuoteMatchAmongCandidates(htmlText, [
      labeled,
      'Оплата по договору 1',
      '1000.50',
    ])
    expect(hit).not.toBeNull()
    expect(hit!.matched).toBe('Оплата по договору 1')
  })

  it('buildQuoteSearchCandidates puts primary then cell alternates', () => {
    const labeled = 'Дата: 24.06.2026\nСумма: 1000.50\nНазначение платежа: Оплата по договору 1'
    const candidates = buildQuoteSearchCandidates(labeled, [
      'Оплата по договору 1',
      '1000.50',
    ])
    expect(candidates[0]).toBe(labeled)
    expect(candidates).toContain('Оплата по договору 1')
    const tableText = '24.06.20261000.50Оплата по договору 1'
    const hit = findQuoteMatchAmongCandidates(tableText, candidates)
    expect(hit?.matched).toBe('Оплата по договору 1')
  })

  it('scoreTableRowsForCandidates picks the unique description row, not shared amount', () => {
    const rows = [
      '24.06.2026 1000.50 Оплата по договору 1',
      '25.06.2026 1000.50 Оплата по договору 2',
      '26.06.2026 500.00 Комиссия банка',
    ]
    const best = scoreTableRowsForCandidates(rows, [
      'Дата: 25.06.2026\nСумма: 1000.50\nНазначение платежа: Оплата по договору 2',
      'Оплата по договору 2',
      '1000.50',
      '25.06.2026',
    ])
    expect(best).not.toBeNull()
    expect(best!.index).toBe(1)
  })

  it('scoreTableRowsForCandidates uses combined hits when description missing', () => {
    const rows = [
      '24.06.2026 1000.50 AAA',
      '25.06.2026 2500.00 BBB',
    ]
    const best = scoreTableRowsForCandidates(rows, ['25.06.2026', '2500.00'])
    expect(best?.index).toBe(1)
    expect(best!.hits).toBeGreaterThanOrEqual(2)
  })
})
