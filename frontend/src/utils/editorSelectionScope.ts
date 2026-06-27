export type EditorChatMode = 'edit' | 'ask' | 'draft'

/** Запрос явно указывает на раздел/пункт документа, а не на выделение. */
const BROADER_DOCUMENT_SIGNALS = [
  'просительн',
  'пункт',
  'подпункт',
  'раздел',
  'шапк',
  'преамбул',
  'таблиц',
  'абзац',
  'в части',
  'в разделе',
  'по документ',
  'в заявлен',
  'в договор',
  'приложен',
  'реквизит',
  'оглавлен',
] as const

/** Запрос затрагивает несколько мест в документе. */
const MULTI_LOCATION_SIGNALS = [
  'везде',
  'все ',
  'всех',
  'кажд',
  'остальн',
  'других мест',
  'другие места',
  'во всём',
  'во всем',
  'согласован',
  'соответств',
  'привед',
  'унифиц',
  'единобраз',
  'несоответств',
] as const

export function instructionTargetsBroaderDocument(question: string): boolean {
  const q = (question || '').trim().toLowerCase()
  if (!q) return false
  return BROADER_DOCUMENT_SIGNALS.some((signal) => q.includes(signal))
}

export function instructionTargetsMultipleLocations(question: string): boolean {
  const q = (question || '').trim().toLowerCase()
  if (!q) return false
  return MULTI_LOCATION_SIGNALS.some((signal) => q.includes(signal))
}

export function instructionIsDialogueContinuation(question: string): boolean {
  const q = (question || '').trim().toLowerCase()
  if (!q || q.length > 120) return false
  if (['да', 'ок', 'окей', 'хорошо', 'согласен', 'согласна', 'давай', 'верно'].includes(q)) {
    return true
  }
  return (
    q.startsWith('да,') ||
    q.startsWith('да ') ||
    q.includes('сделай так') ||
    q.includes('сделай это') ||
    q.includes('как ты') ||
    q.includes('как вы') ||
    q.includes('как написал') ||
    q.includes('как сказал') ||
    q.includes('исправь это') ||
    q.includes('исправь как') ||
    q.includes('приведи в соответствие') ||
    q.includes('приведи к')
  )
}

/**
 * Привязать запрос к выделению (иначе — поиск по всему документу).
 * Выделение — подсказка фокуса; не ограничивает при широком запросе или продолжении диалога.
 */
export function shouldScopeRequestToSelection(
  question: string,
  mode: EditorChatMode,
  selectedText: string | undefined,
  hasDialogueHistory = false,
): boolean {
  const selection = (selectedText || '').trim()
  if (!selection) return false
  if (mode === 'draft') return false
  if (instructionTargetsBroaderDocument(question)) return false
  if (instructionTargetsMultipleLocations(question)) return false
  if (hasDialogueHistory && instructionIsDialogueContinuation(question)) return false
  return mode === 'edit' || mode === 'ask'
}

export function truncateSelectionPreview(text: string, maxLen = 120): string {
  const t = text.replace(/\s+/g, ' ').trim()
  if (t.length <= maxLen) return t
  return `${t.slice(0, maxLen)}…`
}
