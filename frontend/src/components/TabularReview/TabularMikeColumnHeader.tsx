"use client"

import type { ReactNode } from 'react'

interface TabularMikeColumnHeaderProps {
  label: string
  menu?: ReactNode
}

export function TabularMikeColumnHeader({ label, menu }: TabularMikeColumnHeaderProps) {
  return (
    <div className="ws-mike-table-col-header-inner">
      <span className="ws-mike-table-header-label truncate">
        {label}
      </span>
      {menu}
    </div>
  )
}
