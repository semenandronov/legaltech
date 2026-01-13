"use client"

import React, { useState } from "react"
import {
  IconButton,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
  Divider,
} from "@mui/material"
import {
  MoreVert as MoreVertIcon,
  Edit as EditIcon,
  PushPin as PinIcon,
  Delete as DeleteIcon,
} from "@mui/icons-material"

interface ColumnHeaderMenuProps {
  columnId: string
  columnLabel: string
  isPinned?: boolean
  sortDirection?: "asc" | "desc" | null
  onEdit?: () => void
  onPin?: () => void
  onUnpin?: () => void
  onMarkAllReviewed?: () => void
  onDelete?: () => void
  onSortAsc?: () => void
  onSortDesc?: () => void
  onFilter?: () => void
}

export const ColumnHeaderMenu: React.FC<ColumnHeaderMenuProps> = ({
  columnId: _columnId,
  columnLabel: _columnLabel,
  isPinned = false,
  onEdit,
  onPin,
  onUnpin,
  onDelete,
}) => {
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const open = Boolean(anchorEl)

  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    event.stopPropagation()
    setAnchorEl(event.currentTarget)
  }

  const handleClose = () => {
    setAnchorEl(null)
  }

  const handleEdit = () => {
    handleClose()
    onEdit?.()
  }

  const handlePin = () => {
    handleClose()
    if (isPinned) {
      onUnpin?.()
    } else {
      onPin?.()
    }
  }

  const handleDelete = () => {
    handleClose()
    onDelete?.()
  }

  return (
    <>
      <IconButton
        size="small"
        onClick={handleClick}
        sx={{
          p: 0.5,
          color: "#6B7280",
          "&:hover": { color: "#1F2937", bgcolor: "action.hover" },
        }}
      >
        <MoreVertIcon fontSize="small" />
      </IconButton>
      <Menu
        anchorEl={anchorEl}
        open={open}
        onClose={handleClose}
        onClick={(e) => e.stopPropagation()}
        transformOrigin={{ horizontal: "right", vertical: "top" }}
        anchorOrigin={{ horizontal: "right", vertical: "bottom" }}
      >
        <MenuItem onClick={handlePin}>
          <ListItemIcon>
            <PinIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{isPinned ? "Открепить колонку" : "Закрепить колонку"}</ListItemText>
        </MenuItem>
        
        <MenuItem onClick={handleEdit}>
          <ListItemIcon>
            <EditIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Редактировать</ListItemText>
        </MenuItem>
        
        <Divider />
        
        <MenuItem onClick={handleDelete} sx={{ color: "error.main" }}>
          <ListItemIcon>
            <DeleteIcon fontSize="small" color="error" />
          </ListItemIcon>
          <ListItemText>Удалить</ListItemText>
        </MenuItem>
      </Menu>
    </>
  )
}

