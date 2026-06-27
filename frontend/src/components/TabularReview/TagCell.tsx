"use client"

import React from "react"
import type { TabularColumn } from "@/services/tabularReviewApi"
import { getTabularPillClass } from "@/utils/tabularPillUtils"

interface TagCellProps {
  value: string | null
  column: TabularColumn
}

export const TagCell: React.FC<TagCellProps> = ({ value, column }) => {
  if (!value || value === "-" || value === "N/A") {
    return <span className="ws-tabular-cell-text" style={{ color: '#9CA3AF', fontStyle: 'italic' }}>—</span>
  }

  const tag = value.trim()
  if (!tag) {
    return <span className="ws-tabular-cell-text" style={{ color: '#9CA3AF', fontStyle: 'italic' }}>—</span>
  }

  return (
    <span className={`ws-tabular-pill ${getTabularPillClass(tag, column)}`}>
      {tag}
    </span>
  )
}
