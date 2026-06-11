"use client"

import { Box, Typography } from "@mui/material"
import {
  UnfoldMore as UnfoldMoreIcon,
  ArrowUpward as ArrowUpwardIcon,
  ArrowDownward as ArrowDownwardIcon,
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
      sx={{
        display: "flex",
        alignItems: "center",
        gap: 0.5,
        flex: 1,
        minWidth: 0,
        cursor: "pointer",
        userSelect: "none",
        "&:hover": { opacity: 0.85 },
      }}
      aria-label={`Сортировать: ${label}`}
    >
      <Typography
        noWrap
        sx={{
          fontWeight: 600,
          fontSize: "0.75rem",
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          color: "var(--text-secondary, #6B7280)",
        }}
      >
        {label}
      </Typography>
      {sortDirection === "asc" && (
        <ArrowUpwardIcon sx={{ fontSize: 16, color: "#6B7280", flexShrink: 0 }} />
      )}
      {sortDirection === "desc" && (
        <ArrowDownwardIcon sx={{ fontSize: 16, color: "#6B7280", flexShrink: 0 }} />
      )}
      {sortDirection === false && (
        <UnfoldMoreIcon sx={{ fontSize: 16, color: "#9CA3AF", flexShrink: 0 }} />
      )}
    </Box>
  )
}
