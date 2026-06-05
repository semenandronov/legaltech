import type { SourceInfo } from '@/services/api'

/**
 * Путь цитат для внутреннего (case) ассистента: как у глобального — замена [N] на месте,
 * без linkCitationsInline (который режет текст по точкам в «п. / ст.»).
 *
 * Откат: VITE_CASE_ASSISTANT_LEGACY_CITATIONS=false в .env фронта.
 */
export function caseAssistantLegacyCitationsEnabled(): boolean {
  const v = import.meta.env.VITE_CASE_ASSISTANT_LEGACY_CITATIONS
  if (v === 'false' || v === '0') return false
  return true
}

const SYNTHETIC_DOC_ID_RE = /^doc_?\d+$/i
const PASSPORT_FILE_LINE_RE = /^Файл:\s*(.+?)\s*$/m

export function isSyntheticCitationSourceId(sourceId?: string | null): boolean {
  const s = (sourceId || '').trim()
  if (!s || s.toLowerCase() === 'unknown') return true
  return SYNTHETIC_DOC_ID_RE.test(s)
}

function passportFilenameFromSource(source: SourceInfo): string | undefined {
  const text = source.quote_anchor || source.quote || source.text_preview || ''
  const m = text.match(PASSPORT_FILE_LINE_RE)
  const name = m?.[1]?.trim()
  if (!name || SYNTHETIC_DOC_ID_RE.test(name)) return undefined
  return name
}

/** Привязать цитату к реальному file.id дела (страховка, если бэкенд прислал doc_N). */
export function resolveCaseCitationSource(
  source: SourceInfo,
  caseFiles: Array<{ id: string; filename: string }>,
  caseId?: string,
): SourceInfo {
  const withCase = { ...source, case_id: source.case_id ?? caseId }
  if (!caseFiles.length) return withCase

  const known = new Set(caseFiles.map((f) => f.id))
  if (withCase.source_id && known.has(withCase.source_id)) {
    const f = caseFiles.find((x) => x.id === withCase.source_id)
    return {
      ...withCase,
      file: f?.filename || withCase.file,
      title: f?.filename || withCase.title,
    }
  }

  const tryName = (name?: string) => {
    if (!name || SYNTHETIC_DOC_ID_RE.test(name)) return undefined
    return caseFiles.find((f) => f.filename === name)
  }

  let match = tryName(withCase.file)
  if (!match) match = tryName(passportFilenameFromSource(withCase))

  if (match) {
    return {
      ...withCase,
      source_id: match.id,
      file: match.filename,
      title: match.filename,
    }
  }

  if (withCase.source_id && isSyntheticCitationSourceId(withCase.source_id)) {
    return { ...withCase, source_id: undefined }
  }

  return withCase
}
