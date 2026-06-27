"use client"

import { useEffect, useRef, useState } from 'react'
import { Filter, HelpCircle, MoreHorizontal } from 'lucide-react'

interface TabularHeaderMenuProps {
  disabled?: boolean
  onOpenHelp?: () => void
  onOpenFilter?: (anchorEl: HTMLElement) => void
}

export function TabularHeaderMenu({
  disabled = false,
  onOpenHelp,
  onOpenFilter,
}: TabularHeaderMenuProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function handlePointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [open])

  if (!onOpenHelp && !onOpenFilter) return null

  return (
    <div ref={rootRef} className="relative" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        className="ws-tabular-pill-btn ws-tabular-pill-btn--icon"
        aria-label="Дополнительные действия"
        aria-expanded={open}
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>

      {open && (
        <div className="ws-mike-col-menu-dropdown ws-tabular-header-overflow" role="menu">
          {onOpenHelp && (
            <button
              type="button"
              role="menuitem"
              className="ws-mike-col-menu-item"
              onClick={() => {
                setOpen(false)
                onOpenHelp()
              }}
            >
              <HelpCircle className="h-3.5 w-3.5" aria-hidden />
              Справка
            </button>
          )}
          {onOpenFilter && (
            <button
              type="button"
              role="menuitem"
              className="ws-mike-col-menu-item"
              onClick={(event) => {
                setOpen(false)
                onOpenFilter(event.currentTarget)
              }}
            >
              <Filter className="h-3.5 w-3.5" aria-hidden />
              Фильтр
            </button>
          )}
        </div>
      )}
    </div>
  )
}
