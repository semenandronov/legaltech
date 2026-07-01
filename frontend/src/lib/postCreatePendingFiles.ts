import type { PostCreateUploadPayload } from './casePostCreateUpload'
import type { UploadedFile } from '../services/api'

export type PendingUploadStatus = 'uploading' | 'error'

export type PostCreatePendingRow = {
  stagingKey: string
  filename: string
  source: 'local' | 'drive'
  status: PendingUploadStatus
  errorDetail?: string
}

export function buildPostCreatePendingRows(
  payload: PostCreateUploadPayload | undefined,
): PostCreatePendingRow[] {
  if (!payload) return []
  const rows: PostCreatePendingRow[] = []
  for (const item of payload.locals) {
    rows.push({
      stagingKey: item.key,
      filename: item.file.name,
      source: 'local',
      status: 'uploading',
    })
  }
  for (const item of payload.drives) {
    rows.push({
      stagingKey: item.key,
      filename: item.name,
      source: 'drive',
      status: 'uploading',
    })
  }
  return rows
}

function normalizeStem(filename: string): string {
  const trimmed = filename.trim()
  const dot = trimmed.lastIndexOf('.')
  const base = dot > 0 ? trimmed.slice(0, dot) : trimmed
  return base.toLowerCase()
}

export function pendingRowMatchesUploaded(
  row: PostCreatePendingRow,
  uploaded: UploadedFile,
): boolean {
  const a = row.filename.trim()
  const b = (uploaded.filename || '').trim()
  if (!a || !b) return false
  if (a === b) return true
  return normalizeStem(a) === normalizeStem(b)
}

export function removePendingRowsForUploads(
  prev: PostCreatePendingRow[],
  uploaded: UploadedFile[],
): PostCreatePendingRow[] {
  if (!uploaded.length) return prev
  const consumed = new Set<number>()
  for (const file of uploaded) {
    const idx = prev.findIndex(
      (row, i) => !consumed.has(i) && pendingRowMatchesUploaded(row, file),
    )
    if (idx >= 0) consumed.add(idx)
  }
  return prev.filter((_, i) => !consumed.has(i))
}

export function formatCaseDocumentCountLabel(
  serverCount: number,
  filesOnPage: number,
  pending: PostCreatePendingRow[],
  isUploading: boolean,
): string {
  const uploadingPending = pending.filter((p) => p.status === 'uploading').length
  const visible = Math.max(serverCount, filesOnPage + uploadingPending, pending.length)

  if (isUploading || uploadingPending > 0) {
    const n = visible || pending.length
    const word =
      n % 10 === 1 && n % 100 !== 11
        ? 'документ'
        : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)
          ? 'документа'
          : 'документов'
    return `${n} ${word} · загрузка…`
  }

  const n = serverCount || filesOnPage
  const word =
    n % 10 === 1 && n % 100 !== 11
      ? 'документ'
      : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)
        ? 'документа'
        : 'документов'
  return `${n} ${word}`
}
