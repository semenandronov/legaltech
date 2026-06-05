import { describe, expect, it } from 'vitest'
import type { SourceInfo } from '@/services/api'
import {
  citationPersistedFileId,
  filePreviewFromCitation,
  shouldOpenOriginalByCitationId,
} from './caseCitationViewer'

describe('caseCitationViewer', () => {
  const caseBase = '/api/cases/abc-123'

  it('opens by UUID source_id for case files', () => {
    const source: SourceInfo = {
      source_id: '550e8400-e29b-41d4-a716-446655440000',
      file: 'доверенность.pdf',
      source_type: 'document',
    }
    expect(citationPersistedFileId(source)).toBe(source.source_id)
    expect(shouldOpenOriginalByCitationId(source, caseBase)).toBe(true)
    expect(filePreviewFromCitation(source, () => 'pdf')?.id).toBe(source.source_id)
  })

  it('rejects synthetic doc_N labels', () => {
    const source: SourceInfo = { source_id: 'doc_1', file: 'x.pdf' }
    expect(citationPersistedFileId(source)).toBeUndefined()
    expect(shouldOpenOriginalByCitationId(source, caseBase)).toBe(false)
  })

  it('skips external URLs', () => {
    const source: SourceInfo = {
      source_id: '550e8400-e29b-41d4-a716-446655440000',
      url: 'https://pravo.gov.ru/x',
      file: 'act.pdf',
    }
    expect(shouldOpenOriginalByCitationId(source, caseBase)).toBe(false)
  })
})
