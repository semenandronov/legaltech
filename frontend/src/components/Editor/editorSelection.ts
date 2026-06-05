import type { Editor } from '@tiptap/react'

export interface PmTextRange {
  from: number
  to: number
}

/** Last non-empty text selection (for toolbar after focus leaves the editor). */
export function capturePmRange(editor: Editor): PmTextRange | null {
  const { from, to } = editor.state.selection
  if (from >= to) return null
  return { from, to }
}

export function clampPmRange(editor: Editor, range: PmTextRange): PmTextRange {
  const size = editor.state.doc.content.size
  const from = Math.max(0, Math.min(range.from, size))
  const to = Math.max(from, Math.min(range.to, size))
  return { from, to }
}

/**
 * Restore saved range, run command, optionally restore caret after.
 */
export function runWithSavedSelection(
  editor: Editor,
  saved: PmTextRange | null,
  run: () => boolean,
  restoreCaretTo?: number,
): boolean {
  if (!editor || editor.isDestroyed) return false

  let chain = editor.chain().focus()

  if (saved && saved.from < saved.to) {
    const { from, to } = clampPmRange(editor, saved)
    chain = chain.setTextSelection({ from, to })
  }

  const ok = run()

  if (ok && saved && restoreCaretTo !== undefined) {
    const pos = Math.max(saved.from, Math.min(restoreCaretTo, editor.state.doc.content.size))
    editor.chain().focus().setTextSelection(pos).run()
  }

  return ok
}
