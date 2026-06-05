import type { Node as ProseMirrorNode } from '@tiptap/pm/model'
import type { Editor } from '@tiptap/react'
import type { Mark } from '@tiptap/pm/model'

/** Inclusive start or exclusive end of a range in doc.textContent coordinates. */
export type TextOffsetBound = 'start' | 'end'

/**
 * Map a plain-text offset (same coordinate system as Node.textContent) to a
 * ProseMirror document position.
 */
export function textOffsetToPos(
  doc: ProseMirrorNode,
  charIndex: number,
  bound: TextOffsetBound = 'start',
): number {
  const textLen = doc.textContent.length
  const target = Math.max(0, Math.min(charIndex, textLen))

  if (textLen === 0) {
    return 0
  }

  if (bound === 'end' && target === textLen) {
    return posAfterLastTextChar(doc)
  }

  let charCount = 0
  let result = -1

  doc.descendants((node, pos) => {
    if (result !== -1) return false
    if (!node.isText || !node.text) return true

    const nodeLen = node.text.length
    const nodeStart = charCount
    const nodeEnd = charCount + nodeLen

    if (bound === 'start') {
      if (target >= nodeStart && target < nodeEnd) {
        result = pos + (target - nodeStart)
        return false
      }
      if (target === nodeEnd) {
        result = pos + nodeLen
        return false
      }
    } else {
      if (target > nodeStart && target <= nodeEnd) {
        result = pos + (target - nodeStart)
        return false
      }
    }

    charCount = nodeEnd
    return true
  })

  return result
}

/** Exclusive ProseMirror range for a plain-text span [start, end). */
export function textSpanToPmRange(
  doc: ProseMirrorNode,
  start: number,
  end: number,
): { from: number; to: number } | null {
  const from = textOffsetToPos(doc, start, 'start')
  const to = textOffsetToPos(doc, end, 'end')
  if (from === -1 || to === -1 || from > to) return null
  return { from, to }
}

function posAfterLastTextChar(doc: ProseMirrorNode): number {
  let last: number | null = null
  doc.descendants((node, pos) => {
    if (node.isText && node.text) {
      last = pos + node.text.length
    }
    return true
  })
  return last ?? 0
}

/** Replace plain-text span with new text, preserving marks at range start. */
export function replaceTextSpanPreservingMarks(
  editor: Editor,
  start: number,
  end: number,
  newText: string,
): boolean {
  const range = textSpanToPmRange(editor.state.doc, start, end)
  if (!range) return false

  const { from, to } = range
  const $from = editor.state.doc.resolve(from)
  const marks: readonly Mark[] = $from.marks()
  const newNode =
    marks.length > 0
      ? editor.state.schema.text(newText, marks)
      : editor.state.schema.text(newText)

  const tr = editor.state.tr.replaceWith(from, to, newNode)
  editor.view.dispatch(tr)
  editor.commands.focus()
  return true
}

export interface ResolvedTextOccurrence {
  charStart: number
  charEnd: number
  matchedText: string
}

/**
 * Locate plain-text in doc.textContent (case-insensitive, prefix fallbacks, nth match).
 */
export function resolveTextOccurrenceInDoc(
  docText: string,
  searchText: string,
  nthOccurrence = 0,
): ResolvedTextOccurrence | null {
  const trimmed = searchText.trim()
  if (!trimmed) return null

  const docLower = docText.toLowerCase()
  const searchLower = trimmed.toLowerCase()

  const findNth = (needleLower: string, n: number): number => {
    let found = 0
    let searchFrom = 0
    while (true) {
      const idx = docLower.indexOf(needleLower, searchFrom)
      if (idx === -1) return -1
      if (found === n) return idx
      found++
      searchFrom = idx + 1
    }
  }

  let charIndex = findNth(searchLower, nthOccurrence)
  let matchedText = trimmed

  if (charIndex === -1) {
    const tries = [
      trimmed.slice(0, 200),
      trimmed.slice(0, 100),
      trimmed.slice(0, 50),
      trimmed.split(/\s+/).slice(0, 5).join(' '),
    ].filter(Boolean)

    for (const t of tries) {
      const idx = findNth(t.toLowerCase(), nthOccurrence)
      if (idx !== -1) {
        charIndex = idx
        matchedText = docText.slice(idx, idx + t.length)
        break
      }
    }
  } else {
    matchedText = docText.slice(charIndex, charIndex + trimmed.length)
  }

  if (charIndex === -1) return null

  return {
    charStart: charIndex,
    charEnd: charIndex + matchedText.length,
    matchedText,
  }
}

const WORD_CHAR = /[\p{L}\p{N}_]/u

/** Word boundaries around a document position (for slash / bubble actions). */
export function getWordRangeAtPos(
  doc: ProseMirrorNode,
  pos: number,
): { from: number; to: number } | null {
  const $pos = doc.resolve(pos)
  if (!$pos.parent.isTextblock) return null

  const parentStart = $pos.start()
  const text = $pos.parent.textContent
  const offset = $pos.parentOffset

  if (!text.length) return null

  let from = offset
  let to = offset

  while (from > 0 && WORD_CHAR.test(text[from - 1] ?? '')) from--
  while (to < text.length && WORD_CHAR.test(text[to] ?? '')) to++

  if (from === to) return null

  return {
    from: parentStart + from,
    to: parentStart + to,
  }
}
