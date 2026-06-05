import type { SourceInfo } from '@/services/api'

/** Case file API used by chat citations and document preview. */
export function isCaseFilesApiBase(apiBase: string): boolean {
  return /^\/api\/cases\/[^/]+$/.test(apiBase)
}

export function isAssistantFilesApiBase(apiBase: string): boolean {
  return apiBase === '/api/v2/assistant'
}

/** Citation opens a persisted upload (case or global assistant), not external corpus. */
export function isPersistedFileCitation(
  source: SourceInfo,
  apiBase: string,
): boolean {
  if (source.source_type === 'court_practice') return false
  if (source.source_type === 'legal_corpus') return false
  if (source.url?.startsWith('http')) return false
  if (apiBase === '/api/v2/legal-corpus-preview') return false
  return isCaseFilesApiBase(apiBase) || isAssistantFilesApiBase(apiBase)
}

const SYNTHETIC_DOC_ID = /^doc_?\d+$/i

/** File UUID from citation contract — never doc_1 / placeholder labels. */
export function citationPersistedFileId(source: SourceInfo): string | undefined {
  const id = (source.source_id || '').trim()
  if (!id || id.length < 8 || SYNTHETIC_DOC_ID.test(id)) return undefined
  return id
}

export type CitationFilePreviewTarget = {
  id: string
  file_type: string
  filename: string
  legacy_fallback?: boolean
}

export function filePreviewFromCitation(
  source: SourceInfo,
  inferType: (filename?: string) => string,
): CitationFilePreviewTarget | null {
  const id = citationPersistedFileId(source)
  if (!id) return null
  return {
    id,
    file_type: inferType(source.file || source.title),
    filename: source.file || source.title || 'Документ',
  }
}

/**
 * Open viewer by citation file id immediately; enrich metadata from file list in background.
 */
export function shouldOpenOriginalByCitationId(
  source: SourceInfo,
  apiBase: string,
): boolean {
  return (
    isPersistedFileCitation(source, apiBase) &&
    Boolean(citationPersistedFileId(source))
  )
}
