import { useCallback, useEffect, useState } from 'react'
import {
  onCourtPracticeChange,
  onDraftModeChange,
  onLegalResearchChange,
} from '../lib/chatInstrumentPolicy'
import { productFeatures } from '../lib/productFeatures'

/** Устаревшие ключи: настройки чата больше не сохраняются между визитами. */
const LEGACY_INSTRUMENT_STORAGE_KEYS = [
  'case_assistant_use_legal_corpus',
  'case_assistant_use_court_practice',
  'ga_use_legal_corpus',
  'ga_use_court_practice',
] as const

let legacyInstrumentStorageCleared = false

function clearLegacyInstrumentStorage(): void {
  if (legacyInstrumentStorageCleared || typeof window === 'undefined') return
  legacyInstrumentStorageCleared = true
  for (const key of LEGACY_INSTRUMENT_STORAGE_KEYS) {
    try {
      localStorage.removeItem(key)
    } catch {
      /* ignore */
    }
  }
}

export interface ChatInstrumentSettings {
  legalResearch: boolean
  courtPractice: boolean
  draftMode: boolean
  setLegalResearch: (enabled: boolean) => void
  setCourtPractice: (enabled: boolean) => void
  setDraftMode: (enabled: boolean) => void
  reset: () => void
}

/**
 * Настройки инструментов чата (справочник, суд. практика, draft).
 * Эфемерны: не пишутся в localStorage; при каждом входе в чат — сброс.
 */
export function useChatInstrumentSettings(): ChatInstrumentSettings {
  const [legalResearch, setLegalResearch] = useState(false)
  const [courtPractice, setCourtPractice] = useState(false)
  const [draftMode, setDraftMode] = useState(false)

  useEffect(() => {
    clearLegacyInstrumentStorage()
  }, [])

  useEffect(() => {
    if (!productFeatures.legalCorpus) setLegalResearch(false)
    if (!productFeatures.courtPractice) setCourtPractice(false)
    if (!productFeatures.draftMode) setDraftMode(false)
  }, [])

  const reset = useCallback(() => {
    setLegalResearch(false)
    setCourtPractice(false)
    setDraftMode(false)
  }, [])

  const setLegalResearchHandler = useCallback((enabled: boolean) => {
    onLegalResearchChange(enabled, setLegalResearch, setDraftMode, setCourtPractice)
  }, [])

  const setCourtPracticeHandler = useCallback((enabled: boolean) => {
    onCourtPracticeChange(enabled, setCourtPractice, setDraftMode, setLegalResearch)
  }, [])

  const setDraftModeHandler = useCallback((enabled: boolean) => {
    onDraftModeChange(enabled, setDraftMode, setLegalResearch, setCourtPractice)
  }, [])

  return {
    legalResearch,
    courtPractice,
    draftMode,
    setLegalResearch: setLegalResearchHandler,
    setCourtPractice: setCourtPracticeHandler,
    setDraftMode: setDraftModeHandler,
    reset,
  }
}
