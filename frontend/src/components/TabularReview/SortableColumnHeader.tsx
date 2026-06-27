"use client"

import { Box } from "@mui/material"
import {
  ArrowDownward as ArrowDownwardIcon,
  ArrowUpward as ArrowUpwardIcon,
} from "@mui/icons-material"

interface SortableColumnHeaderProps {
  label: string
  sortDirection: false | "asc" | "desc"
  onToggleSort: () => void
}

export function SortableColumnHeader({
  label,
  sortDirection,
  onToggleSort,
}: SortableColumnHeaderProps) {
  return (
    <Box
      component="span"
      role="button"
      tabIndex={0}
      onClick={(e) => {
        e.stopPropagation()
        onToggleSort()
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          e.stopPropagation()
          onToggleSort()
        }
      }}
      className="ws-tabular-col-header-label"
      sx={{
        display: 'block',
        flex: 1,
        minWidth: 0,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        cursor: 'pointer',
        userSelect: 'none',
      }}
      aria-label={`Сортировать: ${label}`}
    >
      {label}
      {sortDirection === "asc" && (
        <ArrowUpwardIcon
          sx={{
            fontSize: 12,
            color: '#9CA3AF',
            flexShrink: 0,
            ml: 0.25,
            verticalAlign: 'middle',
          }}
        />
      )}
      {sortDirection === "desc" && (
        <ArrowDownwardIcon
          sx={{
            fontSize: 12,
            color: '#9CA3AF',
            flexShrink: 0,
            ml: 0.25,
            verticalAlign: 'middle',
          }}
        />
      )}
    </Box>
  )
}
