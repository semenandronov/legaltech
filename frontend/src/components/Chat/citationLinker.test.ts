import { describe, expect, it } from 'vitest'
import type { SourceInfo } from '@/services/api'
import {
  encodeCitationMarker,
  encodeLegacyCitationMarker,
  lastIndicesPerConsecutiveRuns,
  linkCitationsInline,
  segmentPlainTextForCitations,
  splitMarkdownTextAndFences,
  stripBracketCitationNumbers,
} from './citationLinker'

describe('stripBracketCitationNumbers', () => {
  it('удаляет числовые сноски', () => {
    expect(stripBracketCitationNumbers('Тезис [1] и ещё [2].')).toBe('Тезис  и ещё .')
  })
})

describe('splitMarkdownTextAndFences', () => {
  it('оставляет fenced code отдельным куском', () => {
    const parts = splitMarkdownTextAndFences('Hello\n\n```js\nx\n```\n\nWorld.')
    expect(parts.map((p) => p.kind)).toEqual(['text', 'code', 'text'])
    expect(parts[1]).toMatchObject({ kind: 'code', value: expect.stringContaining('```') })
  })
})

describe('segmentPlainTextForCitations', () => {
  it('режет по предложениям', () => {
    const s = segmentPlainTextForCitations('Первое предложение. Второе! Третье?')
    expect(s.length).toBeGreaterThanOrEqual(3)
  })
})

describe('lastIndicesPerConsecutiveRuns', () => {
  it('оставляет только последний индекс в каждом проходе подряд', () => {
    expect([...lastIndicesPerConsecutiveRuns([0, 1, 2, 5, 6])]).toEqual([2, 6])
  })
})

describe('encodeCitationMarker', () => {
  it('парсится регексом MessageContent (cit_ + display)', () => {
    const ZW = '\u200B\u200B'
    const m = encodeCitationMarker('cit_abcdef012345', 1)
    const re = new RegExp(
      `${ZW}(?:CITE_(cit_[a-f0-9]{12})_(\\d+)_ENDCITE|CITE_(\\d+)_ENDCITE)${ZW}`,
      'i',
    )
    const x = re.exec(m)
    expect(x?.[1]).toBe('cit_abcdef012345')
    expect(x?.[2]).toBe('1')
  })

  it('legacy маркер — один номер', () => {
    const ZW = '\u200B\u200B'
    const m = encodeLegacyCitationMarker(3)
    const re = new RegExp(
      `${ZW}(?:CITE_(cit_[a-f0-9]{12})_(\\d+)_ENDCITE|CITE_(\\d+)_ENDCITE)${ZW}`,
      'i',
    )
    const x = re.exec(m)
    expect(x?.[3]).toBe('3')
  })
})

describe('linkCitationsInline', () => {
  it('вставляет маркер при заметном пересечении токенов с цитатой', () => {
    const sources: SourceInfo[] = [
      {
        file: 'a.pdf',
        citation_id: 'cit_aaaaaaaaaaaa',
        quote_anchor: 'стороны обязаны исполнить договор в полном объёме',
      },
    ]
    const md =
      'Стороны обязаны исполнить договор в полном объёме без задержек. Это важное условие сделки.'
    const { markdown, orderedSources } = linkCitationsInline({ markdown: md, sources })
    expect(markdown).toContain('cit_aaaaaaaaaaaa')
    expect(orderedSources[0]?.citation_id).toBe('cit_aaaaaaaaaaaa')
  })

  it('стабильная нумерация: два id — порядок по первому появлению маркера', () => {
    const sources: SourceInfo[] = [
      {
        file: 'b.pdf',
        citation_id: 'cit_bbbbbbbbbbbb',
        quote_anchor: 'уникальный термин альфа для теста',
      },
      {
        file: 'c.pdf',
        citation_id: 'cit_cccccccccccc',
        quote_anchor: 'уникальный термин бета для теста',
      },
    ]
    const md =
      'Уникальный термин альфа для теста подтверждается документом. Уникальный термин бета для теста также указан.'
    const { markdown } = linkCitationsInline({ markdown: md, sources })
    const idxA = markdown.indexOf('cit_bbbbbbbbbbbb')
    const idxB = markdown.indexOf('cit_cccccccccccc')
    expect(idxA).toBeGreaterThan(-1)
    expect(idxB).toBeGreaterThan(-1)
    const nA = markdown.match(/cit_bbbbbbbbbbbb_(\d+)/)?.[1]
    const nB = markdown.match(/cit_cccccccccccc_(\d+)/)?.[1]
    expect(Number(nA)).toBeLessThan(Number(nB))
  })
})
