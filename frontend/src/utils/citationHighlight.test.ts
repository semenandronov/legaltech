import { describe, expect, it } from 'vitest'
import {
  findNormSegmentInPlain,
  findQuoteMatchInPlain,
  normalizeForQuoteMatch,
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
})
