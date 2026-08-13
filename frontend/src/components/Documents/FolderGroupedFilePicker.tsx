import { useEffect, useMemo, useState } from 'react'
import { ChevronRight, FolderOpen } from 'lucide-react'
import type { FolderItem } from '@/services/api'
import { DdDocTypeBadge } from '@/components/Documents/DdDocTypeBadge'
import {
  collectVisibleFileIds,
  groupFilesByFolder,
  type PickableCaseFile,
} from '@/utils/groupFilesByFolder'

export type FolderGroupedFilePickerProps = {
  files: PickableCaseFile[]
  folders: FolderItem[]
  selectedIds: Set<string>
  onSelectedIdsChange: (next: Set<string>) => void
  searchQuery: string
  showTypeBadges?: boolean
  listClassName?: string
}

export function FolderGroupedFilePicker({
  files,
  folders,
  selectedIds,
  onSelectedIdsChange,
  searchQuery,
  showTypeBadges = true,
  listClassName = 'max-h-64',
}: FolderGroupedFilePickerProps) {
  const groups = useMemo(
    () => groupFilesByFolder(files, folders, searchQuery),
    [files, folders, searchQuery],
  )

  const [expandedFolderIds, setExpandedFolderIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    setExpandedFolderIds(new Set(groups.map((group) => group.folderId ?? '__root__')))
  }, [groups])

  const visibleIds = useMemo(() => collectVisibleFileIds(groups), [groups])
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id))

  const toggleFolderExpand = (folderKey: string) => {
    setExpandedFolderIds((prev) => {
      const next = new Set(prev)
      if (next.has(folderKey)) next.delete(folderKey)
      else next.add(folderKey)
      return next
    })
  }

  const toggleFile = (fileId: string) => {
    onSelectedIdsChange(
      (() => {
        const next = new Set(selectedIds)
        if (next.has(fileId)) next.delete(fileId)
        else next.add(fileId)
        return next
      })(),
    )
  }

  const toggleGroup = (groupFiles: PickableCaseFile[]) => {
    const ids = groupFiles.map((file) => file.id)
    const allSelected = ids.length > 0 && ids.every((id) => selectedIds.has(id))
    onSelectedIdsChange(
      (() => {
        const next = new Set(selectedIds)
        if (allSelected) ids.forEach((id) => next.delete(id))
        else ids.forEach((id) => next.add(id))
        return next
      })(),
    )
  }

  const toggleAllVisible = () => {
    if (allVisibleSelected) {
      onSelectedIdsChange(new Set())
      return
    }
    onSelectedIdsChange(new Set(visibleIds))
  }

  if (groups.length === 0) {
    return (
      <div
        className="px-3 py-6 text-center text-sm rounded-lg border"
        style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
      >
        {files.length === 0 ? 'Нет файлов в деле' : 'Файлы не найдены'}
      </div>
    )
  }

  return (
    <div>
      <button
        type="button"
        onClick={toggleAllVisible}
        className="text-xs mb-2 hover:underline"
        style={{ color: 'var(--color-accent)' }}
      >
        {allVisibleSelected ? 'Снять выделение' : 'Выбрать все'}
      </button>

      <div
        className={`overflow-y-auto rounded-lg border divide-y ${listClassName}`}
        style={{ borderColor: 'var(--color-border)' }}
      >
        {groups.map((group) => {
          const folderKey = group.folderId ?? '__root__'
          const isExpanded = expandedFolderIds.has(folderKey)
          const groupIds = group.files.map((file) => file.id)
          const groupAllSelected =
            groupIds.length > 0 && groupIds.every((id) => selectedIds.has(id))
          const groupSomeSelected =
            !groupAllSelected && groupIds.some((id) => selectedIds.has(id))

          return (
            <div key={folderKey}>
              <div
                className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-[var(--color-bg-hover)]"
                style={{ backgroundColor: 'var(--color-bg-primary)' }}
              >
                <input
                  type="checkbox"
                  checked={groupAllSelected}
                  ref={(el) => {
                    if (el) el.indeterminate = groupSomeSelected
                  }}
                  onChange={() => toggleGroup(group.files)}
                  onClick={(event) => event.stopPropagation()}
                  className="rounded shrink-0"
                  aria-label={`Выбрать папку ${group.folderName}`}
                />
                <button
                  type="button"
                  className="flex flex-1 items-center gap-2 min-w-0 text-left"
                  onClick={() => toggleFolderExpand(folderKey)}
                >
                  <ChevronRight
                    className="w-3.5 h-3.5 shrink-0 transition-transform"
                    style={{
                      color: 'var(--color-text-muted)',
                      transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
                    }}
                  />
                  <FolderOpen className="w-3.5 h-3.5 shrink-0 text-amber-400" />
                  <span
                    className="text-sm font-medium truncate"
                    style={{ color: 'var(--color-text-primary)' }}
                  >
                    {group.folderName}
                  </span>
                  <span className="text-xs shrink-0" style={{ color: 'var(--color-text-muted)' }}>
                    ({group.files.length})
                  </span>
                </button>
              </div>

              {isExpanded &&
                group.files.map((file) => (
                  <label
                    key={file.id}
                    className="flex items-center gap-3 pl-9 pr-3 py-2.5 cursor-pointer hover:bg-[var(--color-bg-hover)] border-t"
                    style={{ borderColor: 'var(--color-border)' }}
                  >
                    <input
                      type="checkbox"
                      checked={selectedIds.has(file.id)}
                      onChange={() => toggleFile(file.id)}
                      className="rounded shrink-0"
                    />
                    <span
                      className="text-sm truncate flex-1 min-w-0"
                      style={{ color: 'var(--color-text-primary)' }}
                      title={file.filename}
                    >
                      {file.filename}
                    </span>
                    {showTypeBadges && file.dd_doc_type && (
                      <DdDocTypeBadge
                        docType={file.dd_doc_type}
                        shortLabel={file.dd_doc_type_short_label ?? undefined}
                        size="sm"
                      />
                    )}
                  </label>
                ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}
