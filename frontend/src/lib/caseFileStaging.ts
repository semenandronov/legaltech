import type { GoogleDrivePickResult, PickedDriveDoc } from './googleDrivePicker'

/** Локальный файл до отправки на сервер (экран «Новое дело»). */
export type StagedLocalFile = {
  kind: 'local'
  key: string
  file: File
}

/** Файл Google Drive до отправки (храним token сессии выбора). */
export type StagedDriveFile = {
  kind: 'drive'
  key: string
  driveFileId: string
  name: string
  mimeType: string
  accessToken: string
}

export type StagedCaseFile = StagedLocalFile | StagedDriveFile

export function newStagingKey(): string {
  return `stg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

export function stagedDisplayName(item: StagedCaseFile): string {
  return item.kind === 'local' ? item.file.name : item.name
}

export function drivePicksToStaged(
  { accessToken, docs }: GoogleDrivePickResult,
): StagedDriveFile[] {
  return docs.map((d: PickedDriveDoc) => ({
    kind: 'drive' as const,
    key: newStagingKey(),
    driveFileId: d.id,
    name: d.name,
    mimeType: d.mimeType,
    accessToken,
  }))
}

export function groupDriveByToken(
  items: StagedDriveFile[],
): Map<string, StagedDriveFile[]> {
  const map = new Map<string, StagedDriveFile[]>()
  for (const item of items) {
    const list = map.get(item.accessToken) ?? []
    list.push(item)
    map.set(item.accessToken, list)
  }
  return map
}

export function dedupeStagedLocal(prev: StagedLocalFile[], incoming: File[]): StagedLocalFile[] {
  const names = new Set(prev.map((p) => p.file.name))
  const added = incoming
    .filter((f) => !names.has(f.name))
    .map((file) => ({ kind: 'local' as const, key: newStagingKey(), file }))
  return [...prev, ...added]
}

export function dedupeStagedDrive(
  prev: StagedDriveFile[],
  incoming: StagedDriveFile[],
): StagedDriveFile[] {
  const ids = new Set(prev.map((p) => p.driveFileId))
  return [...prev, ...incoming.filter((f) => !ids.has(f.driveFileId))]
}
