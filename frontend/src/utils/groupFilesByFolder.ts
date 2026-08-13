import type { FolderItem } from '@/services/api'

export type PickableCaseFile = {
  id: string
  filename: string
  folder_id?: string | null
  dd_doc_type?: string | null
  dd_doc_type_short_label?: string | null
}

export type FolderFileGroup = {
  folderId: string | null
  folderName: string
  orderIndex: number
  files: PickableCaseFile[]
}

const ROOT_GROUP_NAME = 'Без папки'
const UNKNOWN_FOLDER_NAME = 'Другая папка'

function sortFiles(files: PickableCaseFile[]): PickableCaseFile[] {
  return [...files].sort((a, b) => a.filename.localeCompare(b.filename, 'ru'))
}

function topLevelFolders(folders: FolderItem[]): FolderItem[] {
  return folders
    .filter((folder) => !folder.parent_id)
    .sort(
      (a, b) =>
        (a.order_index ?? 0) - (b.order_index ?? 0) ||
        a.name.localeCompare(b.name, 'ru'),
    )
}

export function filterPickableFiles(
  files: PickableCaseFile[],
  searchQuery: string,
): PickableCaseFile[] {
  const q = searchQuery.trim().toLowerCase()
  if (!q) return files
  return files.filter((file) => file.filename.toLowerCase().includes(q))
}

/** Group case files by library folder (data-room buckets), preserving folder order. */
export function groupFilesByFolder(
  files: PickableCaseFile[],
  folders: FolderItem[],
  searchQuery: string = '',
): FolderFileGroup[] {
  const filtered = filterPickableFiles(files, searchQuery)
  if (filtered.length === 0) return []

  const folderById = new Map(folders.map((folder) => [folder.id, folder]))
  const byFolder = new Map<string | null, PickableCaseFile[]>()

  for (const file of filtered) {
    const folderId = file.folder_id ?? null
    const bucket = byFolder.get(folderId) ?? []
    bucket.push(file)
    byFolder.set(folderId, bucket)
  }

  const groups: FolderFileGroup[] = []

  for (const folder of topLevelFolders(folders)) {
    const folderFiles = byFolder.get(folder.id)
    if (!folderFiles?.length) continue
    groups.push({
      folderId: folder.id,
      folderName: folder.name,
      orderIndex: folder.order_index ?? 0,
      files: sortFiles(folderFiles),
    })
    byFolder.delete(folder.id)
  }

  for (const [folderId, folderFiles] of byFolder) {
    if (!folderId || !folderFiles.length) continue
    if (folderById.has(folderId)) continue
    groups.push({
      folderId,
      folderName: UNKNOWN_FOLDER_NAME,
      orderIndex: 9_999,
      files: sortFiles(folderFiles),
    })
    byFolder.delete(folderId)
  }

  const rootFiles = byFolder.get(null)
  if (rootFiles?.length) {
    groups.push({
      folderId: null,
      folderName: ROOT_GROUP_NAME,
      orderIndex: 10_000,
      files: sortFiles(rootFiles),
    })
  }

  return groups
}

export function collectVisibleFileIds(groups: FolderFileGroup[]): string[] {
  return groups.flatMap((group) => group.files.map((file) => file.id))
}
