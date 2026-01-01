"use client"

import React, { useState } from "react"
import {
  IconButton,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
  Divider,
  Checkbox,
} from "@mui/material"
import {
  MoreVert as MoreVertIcon,
  Edit as EditIcon,
  PushPin as PinIcon,
  CheckCircle as CheckCircleIcon,
  Delete as DeleteIcon,
  ArrowUpward as ArrowUpIcon,
  ArrowDownward as ArrowDownIcon,
  FilterList as FilterIcon,
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
  columnId,
  columnLabel,
  isPinned = false,
  sortDirection,
  onEdit,
  onPin,
  onUnpin,
  onMarkAllReviewed,
  onDelete,
  onSortAsc,
  onSortDesc,
  onFilter,
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

  const handleMarkAllReviewed = () => {
    handleClose()
    onMarkAllReviewed?.()
  }

  const handleDelete = () => {
    handleClose()
    onDelete?.()
  }

  const handleSortAsc = () => {
    handleClose()
    onSortAsc?.()
  }

  const handleSortDesc = () => {
    handleClose()
    onSortDesc?.()
  }

  const handleFilter = () => {
    handleClose()
    onFilter?.()
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
        <MenuItem onClick={handleEdit}>
          <ListItemIcon>
            <EditIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Edit column</ListItemText>
        </MenuItem>
        
        <MenuItem onClick={handlePin}>
          <ListItemIcon>
            <PinIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{isPinned ? "Unpin column" : "Pin column"}</ListItemText>
          {isPinned && <Checkbox checked size="small" sx={{ ml: "auto" }} />}
        </MenuItem>
        
        <Divider />
        
        <MenuItem onClick={handleMarkAllReviewed}>
          <ListItemIcon>
            <CheckCircleIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Mark all as reviewed</ListItemText>
        </MenuItem>
        
        <Divider />
        
        <MenuItem onClick={handleSortAsc} disabled={sortDirection === "asc"}>
          <ListItemIcon>
            <ArrowUpIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Sort ascending</ListItemText>
          {sortDirection === "asc" && <Checkbox checked size="small" sx={{ ml: "auto" }} />}
        </MenuItem>
        
        <MenuItem onClick={handleSortDesc} disabled={sortDirection === "desc"}>
          <ListItemIcon>
            <ArrowDownIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Sort descending</ListItemText>
          {sortDirection === "desc" && <Checkbox checked size="small" sx={{ ml: "auto" }} />}
        </MenuItem>
        
        <MenuItem onClick={handleFilter}>
          <ListItemIcon>
            <FilterIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Filter</ListItemText>
        </MenuItem>
        
        <Divider />
        
        <MenuItem onClick={handleDelete} sx={{ color: "error.main" }}>
          <ListItemIcon>
            <DeleteIcon fontSize="small" color="error" />
          </ListItemIcon>
          <ListItemText>Delete column</ListItemText>
        </MenuItem>
      </Menu>
    </>
  )
}

