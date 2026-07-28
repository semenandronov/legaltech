import { describe, expect, it } from 'vitest'
import {
  caseHomePath,
  chatHasActiveInstruments,
  chatInstrumentControlsEnabled,
  productFeatures,
} from './productFeatures'

describe('productFeatures', () => {
  it('globalAssistant defaults off (prod surface)', () => {
    expect(typeof productFeatures.globalAssistant).toBe('boolean')
  })

  it('caseAssistant defaults off (prod surface)', () => {
    expect(typeof productFeatures.caseAssistant).toBe('boolean')
  })

  it('operationsAssistant defaults on (agent-first ops chat)', () => {
    expect(productFeatures.operationsAssistant).toBe(true)
  })

  it('caseHomePath lands on overview when caseAssistant is off', () => {
    if (!productFeatures.caseAssistant) {
      expect(caseHomePath('abc')).toBe('/cases/abc')
    } else {
      expect(caseHomePath('abc')).toBe('/cases/abc/chat')
    }
  })

  it('chatInstrumentControlsEnabled reflects instrument flags', () => {
    const anyOn =
      productFeatures.draftMode ||
      productFeatures.legalCorpus ||
      productFeatures.courtPractice
    expect(chatInstrumentControlsEnabled()).toBe(anyOn)
  })

  it('legalCorpusPages exposes page surface flags', () => {
    expect(typeof productFeatures.legalCorpusPages).toBe('boolean')
    expect(typeof productFeatures.courtPracticePages).toBe('boolean')
  })

  it('chatHasActiveInstruments respects disabled features', () => {
    const state = { draftMode: true, legalResearch: true, courtPractice: true }
    const expected =
      (productFeatures.draftMode && state.draftMode) ||
      (productFeatures.legalCorpus && state.legalResearch) ||
      (productFeatures.courtPractice && state.courtPractice)
    expect(chatHasActiveInstruments(state)).toBe(expected)
  })
})
