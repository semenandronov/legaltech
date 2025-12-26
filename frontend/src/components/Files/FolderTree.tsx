import React, { useState } from 'react'
import { Button } from '@/components/UI/Button'
import Input from '@/components/UI/Input'
import { Badge } from '@/components/UI/Badge'
import { ScrollArea } from '@/components/UI/scroll-area'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/UI/context-menu'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/UI/dialog'
import {
  Folder,
  FolderPlus,
  FolderOpen,
  File,
  ChevronRight,
  ChevronDown,
  Pencil,
  Trash2,
  Star,
  StarOff,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { motion, AnimatePresence } from 'framer-motion'
import api from '@/services/api'

export interface FolderItem {
  id: string
  name: string
  parent_id: string | null
  file_count: number
  color?: string
  icon?: string
  children?: FolderItem[]
}

export interface FileItem {
  id: string
  filename: string
  file_type: string
  folder_id: string | null
  starred?: boolean
  order_index?: number
}

interface FolderTreeProps {
  caseId: string
  folders: FolderItem[]
  files: FileItem[]
  selectedFolderId: string | null
  selectedFileIds: string[]
  onSelectFolder: (folderId: string | null) => void
  onSelectFiles: (fileIds: string[]) => void
  onFoldersChange: () => void
  onFilesChange: () => void
  className?: string
}

export function FolderTree({
  caseId,
  folders,
  files,
  selectedFolderId,
  selectedFileIds,
  onSelectFolder,
  onSelectFiles,
  onFoldersChange,
  onFilesChange,
  className,
}: FolderTreeProps) {
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set())
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false)
  const [isRenameDialogOpen, setIsRenameDialogOpen] = useState(false)
  const [newFolderName, setNewFolderName] = useState('')
  const [editingFolder, setEditingFolder] = useState<FolderItem | null>(null)
  const [createInFolder, setCreateInFolder] = useState<string | null>(null)

  const toggleFolder = (folderId: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev)
      if (next.has(folderId)) {
        next.delete(folderId)
      } else {
        next.add(folderId)
      }
      return next
    })
  }

  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) return

    try {
      await api.post(`/cases/${caseId}/folders`, {
        name: newFolderName,
        parent_id: createInFolder,
      })
      setNewFolderName('')
      setCreateInFolder(null)
      setIsCreateDialogOpen(false)
      onFoldersChange()
    } catch (error) {
      console.error('Error creating folder:', error)
    }
  }

  const handleRenameFolder = async () => {
    if (!editingFolder || !newFolderName.trim()) return

    try {
      await api.put(`/cases/${caseId}/folders/${editingFolder.id}`, {
        name: newFolderName,
      })
      setNewFolderName('')
      setEditingFolder(null)
      setIsRenameDialogOpen(false)
      onFoldersChange()
    } catch (error) {
      console.error('Error renaming folder:', error)
    }
  }

  const handleDeleteFolder = async (folderId: string) => {
    try {
      await api.delete(`/cases/${caseId}/folders/${folderId}`)
      onFoldersChange()
    } catch (error) {
      console.error('Error deleting folder:', error)
    }
  }

  const handleToggleStar = async (fileId: string, starred: boolean) => {
    try {
      await api.put(`/files/${fileId}`, { starred: !starred })
      onFilesChange()
    } catch (error) {
      console.error('Error toggling star:', error)
    }
  }

  const openCreateDialog = (parentId: string | null = null) => {
    setCreateInFolder(parentId)
    setNewFolderName('')
    setIsCreateDialogOpen(true)
  }

  const openRenameDialog = (folder: FolderItem) => {
    setEditingFolder(folder)
    setNewFolderName(folder.name)
    setIsRenameDialogOpen(true)
  }

  const getFilesInFolder = (folderId: string | null) => {
    return files.filter((f) => f.folder_id === folderId)
  }

  const renderFolder = (folder: FolderItem, depth: number = 0) => {
    const isExpanded = expandedFolders.has(folder.id)
    const isSelected = selectedFolderId === folder.id
    const folderFiles = getFilesInFolder(folder.id)
    const hasChildren = (folder.children && folder.children.length > 0) || folderFiles.length > 0

    return (
      <div key={folder.id}>
        <ContextMenu>
          <ContextMenuTrigger>
            <div
              className={cn(
                'flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors',
                'hover:bg-muted/50',
                isSelected && 'bg-primary/10 text-primary'
              )}
              style={{ paddingLeft: `${8 + depth * 16}px` }}
              onClick={() => onSelectFolder(folder.id)}
            >
              <button
                className="p-0.5 hover:bg-muted rounded"
                onClick={(e) => {
                  e.stopPropagation()
                  toggleFolder(folder.id)
                }}
              >
                {hasChildren ? (
                  isExpanded ? (
                    <ChevronDown className="h-4 w-4" />
                  ) : (
                    <ChevronRight className="h-4 w-4" />
                  )
                ) : (
                  <div className="w-4" />
                )}
              </button>
              {isExpanded ? (
                <FolderOpen className="h-4 w-4 text-muted-foreground" />
              ) : (
                <Folder className="h-4 w-4 text-muted-foreground" />
              )}
              <span className="flex-1 truncate text-sm">{folder.name}</span>
              {folder.file_count > 0 && (
                <Badge variant="secondary" className="text-xs">
                  {folder.file_count}
                </Badge>
              )}
            </div>
          </ContextMenuTrigger>
          <ContextMenuContent>
            <ContextMenuItem onClick={() => openCreateDialog(folder.id)}>
              <FolderPlus className="mr-2 h-4 w-4" />
              Создать подпапку
            </ContextMenuItem>
            <ContextMenuItem onClick={() => openRenameDialog(folder)}>
              <Pencil className="mr-2 h-4 w-4" />
              Переименовать
            </ContextMenuItem>
            <ContextMenuSeparator />
            <ContextMenuItem
              className="text-destructive"
              onClick={() => handleDeleteFolder(folder.id)}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Удалить
            </ContextMenuItem>
          </ContextMenuContent>
        </ContextMenu>

        {/* Children */}
        <AnimatePresence>
          {isExpanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="overflow-hidden"
            >
              {/* Subfolders */}
              {folder.children?.map((child) => renderFolder(child, depth + 1))}

              {/* Files in folder */}
              {folderFiles.map((file) => renderFile(file, depth + 1))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    )
  }

  const renderFile = (file: FileItem, depth: number = 0) => {
    const isSelected = selectedFileIds.includes(file.id)

    return (
      <div
        key={file.id}
        className={cn(
          'flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors',
          'hover:bg-muted/50',
          isSelected && 'bg-primary/10'
        )}
        style={{ paddingLeft: `${24 + depth * 16}px` }}
        onClick={() => {
          if (isSelected) {
            onSelectFiles(selectedFileIds.filter((id) => id !== file.id))
          } else {
            onSelectFiles([...selectedFileIds, file.id])
          }
        }}
      >
        <File className="h-4 w-4 text-muted-foreground" />
        <span className="flex-1 truncate text-sm">{file.filename}</span>
        <button
          className="p-0.5 hover:bg-muted rounded opacity-0 group-hover:opacity-100 transition-opacity"
          onClick={(e) => {
            e.stopPropagation()
            handleToggleStar(file.id, file.starred || false)
          }}
        >
          {file.starred ? (
            <Star className="h-4 w-4 text-yellow-500 fill-yellow-500" />
          ) : (
            <StarOff className="h-4 w-4 text-muted-foreground" />
          )}
        </button>
      </div>
    )
  }

  // Root level folders
  const rootFolders = folders.filter((f) => !f.parent_id)
  const rootFiles = getFilesInFolder(null)

  return (
    <div className={cn('flex flex-col', className)}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b">
        <span className="text-sm font-medium">Файлы</span>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 p-0"
          onClick={() => openCreateDialog(null)}
        >
          <FolderPlus className="h-4 w-4" />
        </Button>
      </div>

      {/* Tree */}
      <ScrollArea className="flex-1">
        <div className="p-2">
          {/* All files option */}
          <div
            className={cn(
              'flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors',
              'hover:bg-muted/50',
              selectedFolderId === null && 'bg-primary/10 text-primary'
            )}
            onClick={() => onSelectFolder(null)}
          >
            <Folder className="h-4 w-4" />
            <span className="text-sm">Все файлы</span>
            <Badge variant="secondary" className="ml-auto text-xs">
              {files.length}
            </Badge>
          </div>

          {/* Starred files */}
          {files.some((f) => f.starred) && (
            <div
              className={cn(
                'flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors',
                'hover:bg-muted/50'
              )}
            >
              <Star className="h-4 w-4 text-yellow-500" />
              <span className="text-sm">Избранное</span>
              <Badge variant="secondary" className="ml-auto text-xs">
                {files.filter((f) => f.starred).length}
              </Badge>
            </div>
          )}

          <div className="h-px bg-border my-2" />

          {/* Folders */}
          {rootFolders.map((folder) => renderFolder(folder))}

          {/* Root files */}
          {selectedFolderId === null && rootFiles.map((file) => renderFile(file))}
        </div>
      </ScrollArea>

      {/* Create Folder Dialog */}
      <Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Создать папку</DialogTitle>
            <DialogDescription>
              {createInFolder
                ? 'Создание подпапки'
                : 'Создание папки в корне проекта'}
            </DialogDescription>
          </DialogHeader>
          <Input
            value={newFolderName}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewFolderName(e.target.value)}
            placeholder="Название папки"
            autoFocus
            onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => e.key === 'Enter' && handleCreateFolder()}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateDialogOpen(false)}>
              Отмена
            </Button>
            <Button onClick={handleCreateFolder} disabled={!newFolderName.trim()}>
              Создать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Rename Folder Dialog */}
      <Dialog open={isRenameDialogOpen} onOpenChange={setIsRenameDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Переименовать папку</DialogTitle>
          </DialogHeader>
          <Input
            value={newFolderName}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewFolderName(e.target.value)}
            placeholder="Новое название"
            autoFocus
            onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => e.key === 'Enter' && handleRenameFolder()}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsRenameDialogOpen(false)}>
              Отмена
            </Button>
            <Button onClick={handleRenameFolder} disabled={!newFolderName.trim()}>
              Сохранить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default FolderTree

