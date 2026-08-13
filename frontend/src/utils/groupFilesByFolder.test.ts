import { describe, expect, it } from 'vitest'
import { groupFilesByFolder, type PickableCaseFile } from '@/utils/groupFilesByFolder'
import type { FolderItem } from '@/services/api'

const folders: FolderItem[] = [
  { id: 'f-lease', name: 'Аренда', parent_id: null, file_count: 2, order_index: 0 },
  { id: 'f-finance', name: 'Финансы', parent_id: null, file_count: 1, order_index: 4 },
]

const files: PickableCaseFile[] = [
  { id: '1', filename: 'dogovor.pdf', folder_id: 'f-lease', dd_doc_type: 'lease_commercial' },
  { id: '2', filename: 'ds.pdf', folder_id: 'f-lease', dd_doc_type: 'addendum' },
  { id: '3', filename: 'pp.pdf', folder_id: 'f-finance', dd_doc_type: 'payment_order' },
  { id: '4', filename: 'root.pdf', folder_id: null, dd_doc_type: 'unknown' },
]

describe('groupFilesByFolder', () => {
  it('groups by folder order and keeps root last', () => {
    const groups = groupFilesByFolder(files, folders)
    expect(groups.map((g) => g.folderName)).toEqual(['Аренда', 'Финансы', 'Без папки'])
    expect(groups[0]?.files.map((f) => f.id)).toEqual(['1', '2'])
  })

  it('filters by search query', () => {
    const groups = groupFilesByFolder(files, folders, 'pp')
    expect(groups).toHaveLength(1)
    expect(groups[0]?.folderName).toBe('Финансы')
  })
})
