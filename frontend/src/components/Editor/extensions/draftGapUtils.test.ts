import { describe, expect, it } from 'vitest'
import {
  countDraftGapsInText,
  DRAFT_GAP_FULL_PATTERN,
  findUnmarkedDraftGaps,
} from './draftGapUtils'
import { Schema } from '@tiptap/pm/model'
import { DraftGap } from './DraftGap'

const schema = new Schema({
  nodes: {
    doc: { content: 'block+' },
    paragraph: { group: 'block', content: 'inline*' },
    text: { group: 'inline' },
  },
  marks: {
    draftGap: {
      attrs: { label: { default: '' } },
      inclusive: false,
      parseDOM: [{ tag: 'span[data-draft-gap]' }],
      toDOM(mark) {
        return ['span', { 'data-draft-gap': mark.attrs.label, class: 'draft-gap-bubble' }, 0]
      },
    },
  },
})

describe('draftGapUtils', () => {
  it('counts gap markers in plain text', () => {
    expect(countDraftGapsInText('ИНН [ИНН должника] и сумма [сумма]')).toBe(2)
  })

  it('matches full gap pattern', () => {
    expect(DRAFT_GAP_FULL_PATTERN.test('[ИНН]')).toBe(true)
    expect(DRAFT_GAP_FULL_PATTERN.test('частично [x] текст')).toBe(false)
  })

  it('finds unmarked gaps in ProseMirror doc', () => {
    const doc = schema.node('doc', null, [
      schema.node('paragraph', null, [
        schema.text('Должник [наименование]'),
      ]),
    ])
    const ranges = findUnmarkedDraftGaps(doc, schema.marks.draftGap)
    expect(ranges).toHaveLength(1)
    expect(ranges[0].label).toBe('наименование')
  })
})

describe('DraftGap extension', () => {
  it('exports mark with expected name', () => {
    expect(DraftGap.name).toBe('draftGap')
  })
})
