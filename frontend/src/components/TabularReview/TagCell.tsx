"use client"

import React from "react"
import { Chip, Stack } from "@mui/material"
import { TabularColumn } from "@/services/tabularReviewApi"

interface TagCellProps {
  value: string | null
  column: TabularColumn
}

export const TagCell: React.FC<TagCellProps> = ({ value, column }) => {
  if (!value || value === "-" || value === "N/A") {
    return <span style={{ color: "#6B7280", fontStyle: "italic" }}>—</span>
  }

  // Get tag options from column config
  const tagOptions = column.column_config?.options || []
  const isMultiple = column.column_type === "multiple_tags"

  // Parse tags (comma-separated for multiple_tags)
  const tags = isMultiple
    ? value.split(",").map((tag) => tag.trim()).filter(Boolean)
    : [value.trim()]

  // Find color for each tag
  const getTagColor = (tagLabel: string): string => {
    const option = tagOptions.find(
      (opt) => opt.label.toLowerCase() === tagLabel.toLowerCase()
    )
    return option?.color || "#6B7280" // Default gray if not found
  }

  if (tags.length === 0) {
    return <span style={{ color: "#6B7280", fontStyle: "italic" }}>—</span>
  }

  return (
    <Stack direction="row" spacing={0.5} flexWrap="wrap" sx={{ py: 0.5 }}>
      {tags.map((tag, idx) => {
        const color = getTagColor(tag)
        return (
          <Chip
            key={idx}
            label={tag}
            size="small"
            sx={{
              bgcolor: color,
              color: "white",
              fontSize: "0.75rem",
              height: 22,
              fontWeight: 500,
              "& .MuiChip-label": {
                px: 1,
              },
            }}
          />
        )
      })}
    </Stack>
  )
}


