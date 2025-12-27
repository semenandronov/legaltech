import React, { useState } from 'react'
import {
  Button,
  TextField,
  Chip,
  Box,
  Typography,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  IconButton,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Divider,
  Collapse,
} from '@mui/material'
import {
  Folder as FolderIcon,
  CreateNewFolder as FolderPlusIcon,
  FolderOpen as FolderOpenIcon,
  Description as FileIcon,
  ChevronRight as ChevronRightIcon,
  ExpandMore as ExpandMoreIcon,
  Edit as PencilIcon,
  Delete as TrashIcon,
  Star as StarIcon,
  StarBorder as StarOffIcon,
  CreateNewFolder as CreateFolderIcon,
} from '@mui/icons-material'
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

export const FolderTree = React.memo(({
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
}: FolderTreeProps) => {
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set())
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false)
  const [isRenameDialogOpen, setIsRenameDialogOpen] = useState(false)
  const [newFolderName, setNewFolderName] = useState('')
  const [editingFolder, setEditingFolder] = useState<FolderItem | null>(null)
  const [createInFolder, setCreateInFolder] = useState<string | null>(null)
  const [contextMenu, setContextMenu] = useState<{ mouseX: number; mouseY: number; folderId: string } | null>(null)

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
    setContextMenu(null)
  }

  const getFilesInFolder = (folderId: string | null) => {
    return files.filter((f) => f.folder_id === folderId)
  }

  const handleContextMenu = (event: React.MouseEvent, folderId: string) => {
    event.preventDefault()
    setContextMenu(
      contextMenu === null
        ? {
            mouseX: event.clientX + 2,
            mouseY: event.clientY - 6,
            folderId,
          }
        : null,
    )
  }

  const handleCloseContextMenu = () => {
    setContextMenu(null)
  }

  const renderFolder = (folder: FolderItem, depth: number = 0) => {
    const isExpanded = expandedFolders.has(folder.id)
    const isSelected = selectedFolderId === folder.id
    const folderFiles = getFilesInFolder(folder.id)
    const hasChildren = (folder.children && folder.children.length > 0) || folderFiles.length > 0

    return (
      <Box key={folder.id}>
        <ListItemButton
          selected={isSelected}
          onContextMenu={(e) => handleContextMenu(e, folder.id)}
          onClick={() => onSelectFolder(folder.id)}
          sx={{
            pl: 1 + depth * 2,
            py: 0.5,
            minHeight: 32,
          }}
        >
          <IconButton
            size="small"
            onClick={(e) => {
              e.stopPropagation()
              toggleFolder(folder.id)
            }}
            sx={{ mr: 0.5 }}
          >
            {hasChildren ? (
              isExpanded ? (
                <ExpandMoreIcon fontSize="small" />
              ) : (
                <ChevronRightIcon fontSize="small" />
              )
            ) : (
              <Box sx={{ width: 24 }} />
            )}
          </IconButton>
          <ListItemIcon sx={{ minWidth: 32 }}>
            {isExpanded ? (
              <FolderOpenIcon fontSize="small" color="action" />
            ) : (
              <FolderIcon fontSize="small" color="action" />
            )}
          </ListItemIcon>
          <ListItemText
            primary={folder.name}
            primaryTypographyProps={{
              variant: 'body2',
              noWrap: true,
            }}
          />
          {folder.file_count > 0 && (
            <Chip label={folder.file_count} size="small" sx={{ ml: 1, height: 20 }} />
          )}
        </ListItemButton>

        {/* Children */}
        <Collapse in={isExpanded} timeout="auto" unmountOnExit>
          <Box sx={{ pl: 2 }}>
            {/* Subfolders */}
            {folder.children?.map((child) => renderFolder(child, depth + 1))}

            {/* Files in folder */}
            {folderFiles.map((file) => renderFile(file, depth + 1))}
          </Box>
        </Collapse>

        {/* Context Menu */}
        <Menu
          open={contextMenu?.folderId === folder.id}
          onClose={handleCloseContextMenu}
          anchorReference="anchorPosition"
          anchorPosition={
            contextMenu !== null
              ? { top: contextMenu.mouseY, left: contextMenu.mouseX }
              : undefined
          }
        >
          <MenuItem
            onClick={() => {
              openCreateDialog(folder.id)
              handleCloseContextMenu()
            }}
          >
            <ListItemIcon>
              <CreateFolderIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Создать подпапку</ListItemText>
          </MenuItem>
          <MenuItem
            onClick={() => {
              openRenameDialog(folder)
            }}
          >
            <ListItemIcon>
              <PencilIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Переименовать</ListItemText>
          </MenuItem>
          <Divider />
          <MenuItem
            onClick={() => {
              handleDeleteFolder(folder.id)
              handleCloseContextMenu()
            }}
            sx={{ color: 'error.main' }}
          >
            <ListItemIcon>
              <TrashIcon fontSize="small" sx={{ color: 'error.main' }} />
            </ListItemIcon>
            <ListItemText>Удалить</ListItemText>
          </MenuItem>
        </Menu>
      </Box>
    )
  }

  const renderFile = (file: FileItem, depth: number = 0) => {
    const isSelected = selectedFileIds.includes(file.id)

    return (
      <ListItemButton
        key={file.id}
        selected={isSelected}
        onClick={() => {
          if (isSelected) {
            onSelectFiles(selectedFileIds.filter((id) => id !== file.id))
          } else {
            onSelectFiles([...selectedFileIds, file.id])
          }
        }}
        sx={{
          pl: 3 + depth * 2,
          py: 0.5,
          minHeight: 32,
        }}
      >
        <ListItemIcon sx={{ minWidth: 32 }}>
          <FileIcon fontSize="small" color="action" />
        </ListItemIcon>
        <ListItemText
          primary={file.filename}
          primaryTypographyProps={{
            variant: 'body2',
            noWrap: true,
          }}
        />
        <IconButton
          size="small"
          onClick={(e) => {
            e.stopPropagation()
            handleToggleStar(file.id, file.starred || false)
          }}
          sx={{ ml: 1 }}
        >
          {file.starred ? (
            <StarIcon fontSize="small" sx={{ color: 'warning.main' }} />
          ) : (
            <StarOffIcon fontSize="small" color="action" />
          )}
        </IconButton>
      </ListItemButton>
    )
  }

  // Root level folders
  const rootFolders = folders.filter((f) => !f.parent_id)
  const rootFiles = getFilesInFolder(null)

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', ...(className ? {} : {}) }} className={className}>
      {/* Header */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 2,
          py: 1,
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <Typography variant="body2" fontWeight={500}>
          Файлы
        </Typography>
        <IconButton
          size="small"
          onClick={() => openCreateDialog(null)}
          sx={{ width: 28, height: 28 }}
        >
          <FolderPlusIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* Tree */}
      <Box sx={{ flex: 1, overflow: 'auto', p: 1 }}>
        {/* All files option */}
        <ListItemButton
          selected={selectedFolderId === null}
          onClick={() => onSelectFolder(null)}
          sx={{ borderRadius: 1, mb: 0.5 }}
        >
          <ListItemIcon sx={{ minWidth: 32 }}>
            <FolderIcon fontSize="small" color="action" />
          </ListItemIcon>
          <ListItemText
            primary="Все файлы"
            primaryTypographyProps={{
              variant: 'body2',
            }}
          />
          <Chip label={files.length} size="small" sx={{ ml: 1, height: 20 }} />
        </ListItemButton>

        {/* Starred files */}
        {files.some((f) => f.starred) && (
          <ListItemButton sx={{ borderRadius: 1, mb: 0.5 }}>
            <ListItemIcon sx={{ minWidth: 32 }}>
              <StarIcon fontSize="small" sx={{ color: 'warning.main' }} />
            </ListItemIcon>
            <ListItemText
              primary="Избранное"
              primaryTypographyProps={{
                variant: 'body2',
              }}
            />
            <Chip
              label={files.filter((f) => f.starred).length}
              size="small"
              sx={{ ml: 1, height: 20 }}
            />
          </ListItemButton>
        )}

        <Divider sx={{ my: 1 }} />

        {/* Folders */}
        {rootFolders.map((folder) => renderFolder(folder))}

        {/* Root files */}
        {selectedFolderId === null && rootFiles.map((file) => renderFile(file))}
      </Box>

      {/* Create Folder Dialog */}
      <Dialog open={isCreateDialogOpen} onClose={() => setIsCreateDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Создать папку</DialogTitle>
        <Typography variant="body2" color="text.secondary" sx={{ px: 3, pb: 2 }}>
          {createInFolder
            ? 'Создание подпапки'
            : 'Создание папки в корне проекта'}
        </Typography>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            label="Название папки"
            value={newFolderName}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewFolderName(e.target.value)}
            onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => {
              if (e.key === 'Enter') {
                handleCreateFolder()
              }
            }}
            margin="normal"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setIsCreateDialogOpen(false)} variant="outlined">
            Отмена
          </Button>
          <Button onClick={handleCreateFolder} disabled={!newFolderName.trim()} variant="contained">
            Создать
          </Button>
        </DialogActions>
      </Dialog>

      {/* Rename Folder Dialog */}
      <Dialog open={isRenameDialogOpen} onClose={() => setIsRenameDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Переименовать папку</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            label="Новое название"
            value={newFolderName}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewFolderName(e.target.value)}
            onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => {
              if (e.key === 'Enter') {
                handleRenameFolder()
              }
            }}
            margin="normal"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setIsRenameDialogOpen(false)} variant="outlined">
            Отмена
          </Button>
          <Button onClick={handleRenameFolder} disabled={!newFolderName.trim()} variant="contained">
            Сохранить
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
})

FolderTree.displayName = 'FolderTree'

export default FolderTree
