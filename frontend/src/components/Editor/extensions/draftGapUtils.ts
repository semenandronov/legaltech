import type { MarkType, Node as ProseMirrorNode } from '@tiptap/pm/model'

/** Matches backend draft_pipeline.markers: [label] (legacy [? label ?] supported) */
export const DRAFT_GAP_PATTERN = /\[\?\s*(.+?)\s*\?\]|\[([^\[\]]+)\]/g

export const DRAFT_GAP_FULL_PATTERN = /^\[\?\s*(.+?)\s*\?\]$|^\[([^\[\]]+)\]$/

export interface DraftGapRange {
  from: number
  to: number
  label: string
}

export function findUnmarkedDraftGaps(doc: ProseMirrorNode, markType: MarkType): DraftGapRange[] {
  const out: DraftGapRange[] = []
  const re = new RegExp(DRAFT_GAP_PATTERN.source, 'g')

  doc.descendants((node, pos) => {
    if (!node.isText || !node.text) return
    re.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = re.exec(node.text)) !== null) {
      const from = pos + m.index
      const to = from + m[0].length
      const $inside = doc.resolve(from + 1)
      if (!markType.isInSet($inside.marks())) {
        out.push({ from, to, label: ((m[1] || m[2] || '').trim()) || 'поле' })
      }
    }
  })

  return out
}

export function findStaleDraftGapMarks(doc: ProseMirrorNode, markType: MarkType): Array<{ from: number; to: number }> {
  const out: Array<{ from: number; to: number }> = []

  doc.descendants((node, pos) => {
    if (!node.isText || !node.text) return
    if (!markType.isInSet(node.marks)) return
    if (!DRAFT_GAP_FULL_PATTERN.test(node.text.trim())) {
      out.push({ from: pos, to: pos + node.text.length })
    }
  })

  return out
}

export function countDraftGapsInText(text: string): number {
  const re = new RegExp(DRAFT_GAP_PATTERN.source, 'g')
  let n = 0
  while (re.exec(text) !== null) n += 1
  return n
}
