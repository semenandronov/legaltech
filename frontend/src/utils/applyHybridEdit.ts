import type { StructuredEdit } from '@/services/documentEditorApi'

export interface HybridEditHandlers {
  onReplaceNodeById?: (nodeId: string, newText: string) => boolean
  onReplaceRange?: (from: number, to: number, text: string) => void
  onReplaceText?: (original: string, newText: string) => boolean
  onReplaceTextFuzzy?: (original: string, newText: string) => boolean
  onReplaceAllText?: (original: string, newText: string) => number
}

export interface ApplyHybridEditResult {
  success: boolean
  copyText?: string
  failureMessage?: string
}

function normalizeForMatch(text: string): string {
  return text.replace(/\s+/g, ' ').trim().toLowerCase()
}

/**
 * Multi-level apply: node_id → selection_range → exact text → fuzzy text.
 */
export function applyHybridEdit(
  edit: StructuredEdit,
  msg: { selectionRange?: { from: number; to: number } } | undefined,
  handlers: HybridEditHandlers,
): boolean {
  if (edit.node_id && handlers.onReplaceNodeById) {
    if (handlers.onReplaceNodeById(edit.node_id, edit.new_text)) return true
  }

  const range = edit.selection_range ?? msg?.selectionRange
  if (range && handlers.onReplaceRange) {
    handlers.onReplaceRange(range.from, range.to, edit.new_text)
    return true
  }

  if (edit.replace_all && edit.original_text && handlers.onReplaceAllText) {
    if (handlers.onReplaceAllText(edit.original_text, edit.new_text) > 0) return true
  }

  if (edit.original_text && handlers.onReplaceText) {
    if (handlers.onReplaceText(edit.original_text, edit.new_text)) return true
  }

  if (edit.original_text && handlers.onReplaceTextFuzzy) {
    if (handlers.onReplaceTextFuzzy(edit.original_text, edit.new_text)) return true
  }

  return false
}

export function applyHybridEditWithFeedback(
  edit: StructuredEdit,
  msg: { selectionRange?: { from: number; to: number } } | undefined,
  handlers: HybridEditHandlers,
): ApplyHybridEditResult {
  if (applyHybridEdit(edit, msg, handlers)) {
    return { success: true }
  }
  return {
    success: false,
    copyText: edit.new_text,
    failureMessage:
      'Не удалось применить правку автоматически. Скопируйте новый текст из чата и вставьте вручную.',
  }
}

/** Client-side fuzzy match helper (used when editor has no dedicated fuzzy method). */
export function fuzzyFindInPlainText(docText: string, originalText: string): string | null {
  if (!originalText?.trim()) return null
  const doc = docText
  const candidates = [
    originalText,
    originalText.slice(0, 200),
    originalText.slice(0, 100),
    originalText.slice(0, 50),
    originalText.split(/\s+/).slice(0, 8).join(' '),
  ].filter(Boolean)

  for (const c of candidates) {
    if (doc.includes(c)) return c
    const idx = doc.toLowerCase().indexOf(c.toLowerCase())
    if (idx !== -1) return doc.slice(idx, idx + c.length)
  }

  const normDoc = normalizeForMatch(doc)
  for (const c of candidates) {
    const normC = normalizeForMatch(c)
    const idx = normDoc.indexOf(normC)
    if (idx === -1) continue
    // Map back approximately: use first occurrence in original doc with same length
    const rough = doc.toLowerCase().indexOf(c.toLowerCase().slice(0, Math.min(20, c.length)))
    if (rough !== -1) return doc.slice(rough, rough + c.length)
  }
  return null
}
