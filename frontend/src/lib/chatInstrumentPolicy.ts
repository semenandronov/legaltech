/**
 * Правила совместимости режима чата и инструментов:
 * - Справочник и судебная практика взаимоисключают друг друга
 * - Draft → инструменты выключены
 */

export function onLegalResearchChange(
  enabled: boolean,
  setLegalResearch: (v: boolean) => void,
  setDraftMode: (v: boolean) => void,
  setCourtPractice?: (v: boolean) => void,
): void {
  if (enabled) {
    setDraftMode(false)
    setCourtPractice?.(false)
  }
  setLegalResearch(enabled)
}

export function onCourtPracticeChange(
  enabled: boolean,
  setCourtPractice: (v: boolean) => void,
  setDraftMode: (v: boolean) => void,
  setLegalResearch?: (v: boolean) => void,
): void {
  if (enabled) {
    setDraftMode(false)
    setLegalResearch?.(false)
  }
  setCourtPractice(enabled)
}

export function onDraftModeChange(
  enabled: boolean,
  setDraftMode: (v: boolean) => void,
  setLegalResearch: (v: boolean) => void,
  setCourtPractice?: (v: boolean) => void,
): void {
  if (enabled) {
    setLegalResearch(false)
    setCourtPractice?.(false)
  }
  setDraftMode(enabled)
}

export function canSelectDraftMode(legalResearch: boolean, courtPractice = false): boolean {
  return !legalResearch && !courtPractice
}

export function canEnableLegalResearch(draftMode: boolean): boolean {
  return !draftMode
}

export function canEnableCourtPractice(draftMode: boolean): boolean {
  return !draftMode
}

/** Режим редактора: при справочнике или судебной практике — только ask. */
export function effectiveEditorChatMode(
  legalResearch: boolean,
  editorChatMode: 'edit' | 'ask',
  courtPractice = false,
): 'edit' | 'ask' {
  return legalResearch || courtPractice ? 'ask' : editorChatMode
}
