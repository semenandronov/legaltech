import type { Editor } from '@tiptap/react'
import type { PmTextRange } from './editorSelection'
import { clampPmRange, capturePmRange } from './editorSelection'

function resolveToolbarRange(editor: Editor, saved: PmTextRange | null): PmTextRange | null {
  if (saved && saved.from < saved.to) return saved
  return capturePmRange(editor)
}

function chainWithSavedSelection(editor: Editor, saved: PmTextRange | null) {
  const range = resolveToolbarRange(editor, saved)
  let chain = editor.chain().focus()
  if (range) {
    const { from, to } = clampPmRange(editor, range)
    chain = chain.setTextSelection({ from, to })
  }
  return chain
}

export function applyFontFamily(editor: Editor, fontFamily: string, saved: PmTextRange | null): boolean {
  return chainWithSavedSelection(editor, saved).setFontFamily(fontFamily).run()
}

export function applyFontSize(editor: Editor, fontSize: string, saved: PmTextRange | null): boolean {
  return chainWithSavedSelection(editor, saved).setFontSize(fontSize).run()
}

export function toggleBulletList(editor: Editor, saved: PmTextRange | null): boolean {
  let chain = chainWithSavedSelection(editor, saved)
  if (editor.isActive('heading')) {
    chain = chain.setParagraph()
  }
  return chain.toggleBulletList().run()
}

export function toggleOrderedList(editor: Editor, saved: PmTextRange | null): boolean {
  let chain = chainWithSavedSelection(editor, saved)
  if (editor.isActive('heading')) {
    chain = chain.setParagraph()
  }
  return chain.toggleOrderedList().run()
}
