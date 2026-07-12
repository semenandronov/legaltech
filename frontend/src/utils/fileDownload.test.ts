import { describe, expect, it } from 'vitest'
import { sanitizeDownloadFilename } from './fileDownload'

describe('sanitizeDownloadFilename', () => {
  it('strips path separators and unsafe characters', () => {
    expect(sanitizeDownloadFilename('../../a/b<c>.xlsx')).toBe('b_c_.xlsx')
  })

  it('falls back for empty names', () => {
    expect(sanitizeDownloadFilename('   ')).toBe('export')
  })
})
