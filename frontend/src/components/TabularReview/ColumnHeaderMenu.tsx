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
  ArrowUpward as ArrowUpwardIcon,
  ArrowDownward as ArrowDownwardIcon,
  ClearAll as ClearAllIcon,
} from "@mui/icons-material"

interface ColumnHeaderMenuProps {
  columnId: string
  columnLabel: string
  isPinned?: boolean
  disabled?: boolean
  sortDirection?: "asc" | "desc" | false
  onEdit?: (anchorEl: HTMLElement) => void
  onPin?: () => void
  onUnpin?: () => void
  onDelete?: () => void
  onSortAsc?: () => void
  onSortDesc?: () => void
  onClearSort?: () => void
}

export const ColumnHeaderMenu: React.FC<ColumnHeaderMenuProps> = ({
  columnId: _columnId,
  columnLabel: _columnLabel,
  isPinned = false,
  disabled = false,
  sortDirection = false,
  onEdit,
  onPin,
  onUnpin,
  onDelete,
  onSortAsc,
  onSortDesc,
  onClearSort,
}) => {
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const triggerRef = React.useRef<HTMLButtonElement>(null)
  const open = Boolean(anchorEl)

  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    event.stopPropagation()
    setAnchorEl(event.currentTarget)
  }

  const handleClose = () => {
    setAnchorEl(null)
  }

  const run = (fn?: () => void) => {
    handleClose()
    fn?.()
  }

  const handleEdit = () => {
    handleClose()
    const anchor = triggerRef.current
    if (anchor && onEdit) {
      onEdit(anchor)
    }
  }

  const showSort = onSortAsc || onSortDesc

  return (
    <>
      <IconButton
        ref={triggerRef}
        size="small"
        onClick={handleClick}
        disabled={disabled}
        aria-label={`Меню колонки ${_columnLabel}`}
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
        {showSort && (
          <>
            <MenuItem onClick={() => run(onSortAsc)} selected={sortDirection === "asc"}>
              <ListItemIcon>
                <ArrowUpwardIcon fontSize="small" />
              </ListItemIcon>
              <ListItemText>По возрастанию</ListItemText>
            </MenuItem>
            <MenuItem onClick={() => run(onSortDesc)} selected={sortDirection === "desc"}>
              <ListItemIcon>
                <ArrowDownwardIcon fontSize="small" />
              </ListItemIcon>
              <ListItemText>По убыванию</ListItemText>
            </MenuItem>
            {sortDirection && onClearSort && (
              <MenuItem onClick={() => run(onClearSort)}>
                <ListItemIcon>
                  <ClearAllIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText>Сбросить сортировку</ListItemText>
              </MenuItem>
            )}
            <Divider />
          </>
        )}

        <MenuItem onClick={() => run(isPinned ? onUnpin : onPin)}>
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

        <MenuItem onClick={() => run(onDelete)} disabled={disabled} sx={{ color: "error.main" }}>
          <ListItemIcon>
            <DeleteIcon fontSize="small" color="error" />
          </ListItemIcon>
          <ListItemText>Удалить</ListItemText>
        </MenuItem>
      </Menu>
    </>
  )
}
