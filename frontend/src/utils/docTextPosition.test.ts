import { describe, expect, it } from 'vitest'
import { Schema } from '@tiptap/pm/model'
import { textOffsetToPos, textSpanToPmRange } from './docTextPosition'

const schema = new Schema({
  nodes: {
    doc: { content: 'block+' },
    paragraph: {
      group: 'block',
      content: 'inline*',
      toDOM: () => ['p', 0],
      parseDOM: [{ tag: 'p' }],
    },
    text: { group: 'inline' },
  },
})

function docFromParagraphText(...parts: string[]) {
  const children = parts.map((t) => {
    if (t.includes('|')) {
      const [a, b] = t.split('|')
      return schema.node('paragraph', null, [schema.text(a), schema.text(b)])
    }
    return schema.node('paragraph', null, schema.text(t))
  })
  return schema.node('doc', null, children)
}

describe('textOffsetToPos', () => {
  it('maps start and end of single text node', () => {
    const doc = docFromParagraphText('abc')
    expect(textOffsetToPos(doc, 0, 'start')).toBe(1)
    expect(textOffsetToPos(doc, 3, 'end')).toBe(4)
    expect(textSpanToPmRange(doc, 0, 3)).toEqual({ from: 1, to: 4 })
  })

  it('maps across two text nodes with different marks', () => {
    const doc = docFromParagraphText('ab|cd')
    expect(doc.textContent).toBe('abcd')
    const range = textSpanToPmRange(doc, 1, 3)
    expect(range).not.toBeNull()
    expect(range!.to).toBeGreaterThan(range!.from)
  })

  it('maps exclusive end at document EOF', () => {
    const doc = docFromParagraphText('hello')
    expect(textOffsetToPos(doc, 5, 'end')).toBe(6)
  })
})
