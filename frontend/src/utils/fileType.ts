/** Resolve viewer file type from filename / stored file_type. */
export function fileTypeFromName(name?: string | null): string {
  const lower = (name || '').toLowerCase().trim()
  if (lower.endsWith('.pdf') || lower === 'pdf') return 'pdf'
  if (lower.endsWith('.docx') || lower === 'docx') return 'docx'
  if (
    lower.endsWith('.xlsx') ||
    lower.endsWith('.xlsm') ||
    lower.endsWith('.xls') ||
    lower === 'xlsx' ||
    lower === 'xlsm' ||
    lower === 'xls'
  ) {
    return 'xlsx'
  }
  if (lower.endsWith('.txt') || lower === 'txt') return 'txt'
  if (lower.endsWith('.html') || lower.endsWith('.htm') || lower === 'html') return 'html'
  if (lower.endsWith('.md') || lower === 'md') return 'md'
  if (lower.endsWith('.json') || lower === 'json') return 'json'
  if (lower.endsWith('.xml') || lower === 'xml') return 'xml'
  if (lower.endsWith('.csv') || lower === 'csv') return 'csv'
  return 'txt'
}

/** Types rendered via server HTML conversion (preview + citation highlight). */
export function isHtmlPreviewFileType(fileType?: string | null): boolean {
  const t = (fileType || '').toLowerCase()
  return t === 'docx' || t === 'xlsx' || t === 'xls' || t === 'xlsm'
}
