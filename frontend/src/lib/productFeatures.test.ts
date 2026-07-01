import { describe, expect, it } from 'vitest'
import {
  chatHasActiveInstruments,
  chatInstrumentControlsEnabled,
  productFeatures,
} from './productFeatures'

describe('productFeatures', () => {
  it('globalAssistant defaults off (prod surface)', () => {
    expect(typeof productFeatures.globalAssistant).toBe('boolean')
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
