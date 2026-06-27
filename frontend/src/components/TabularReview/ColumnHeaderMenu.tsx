"use client"

import React, { useEffect, useRef, useState } from 'react'
import {
  MoreHorizontal,
  ArrowUp,
  ArrowDown,
  XCircle,
  Play,
  Pin,
  Pencil,
  Trash2,
} from 'lucide-react'

interface ColumnHeaderMenuProps {
  columnId: string
  columnLabel: string
  isPinned?: boolean
  disabled?: boolean
  isRunning?: boolean
  sortDirection?: 'asc' | 'desc' | false
  onRun?: () => void
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
  columnLabel,
  isPinned = false,
  disabled = false,
  isRunning = false,
  sortDirection = false,
  onRun,
  onEdit,
  onPin,
  onUnpin,
  onDelete,
  onSortAsc,
  onSortDesc,
  onClearSort,
}) => {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    function handleClickOutside(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const run = (fn?: () => void) => {
    setOpen(false)
    fn?.()
  }

  const handleEdit = () => {
    setOpen(false)
    const anchor = triggerRef.current
    if (anchor && onEdit) {
      onEdit(anchor)
    }
  }

  const showSort = onSortAsc || onSortDesc
  const showPin = onPin || onUnpin
  const hasActions = showSort || onRun || showPin || onEdit || onDelete

  if (!hasActions) return null

  return (
    <div ref={rootRef} className="ws-mike-col-menu" onClick={(e) => e.stopPropagation()}>
      <button
        ref={triggerRef}
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          if (disabled) return
          setOpen((value) => !value)
        }}
        disabled={disabled}
        className={`ws-mike-col-menu-trigger ${disabled ? 'ws-mike-col-menu-trigger--disabled' : ''}`}
        aria-label={`Меню колонки ${columnLabel}`}
        aria-expanded={open}
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>

      {open && (
        <div className="ws-mike-col-menu-dropdown" role="menu">
          {showSort && (
            <>
              <button
                type="button"
                role="menuitem"
                className={`ws-mike-col-menu-item ${sortDirection === 'asc' ? 'ws-mike-col-menu-item--active' : ''}`}
                onClick={() => run(onSortAsc)}
              >
                <ArrowUp className="h-3.5 w-3.5" aria-hidden />
                По возрастанию
              </button>
              <button
                type="button"
                role="menuitem"
                className={`ws-mike-col-menu-item ${sortDirection === 'desc' ? 'ws-mike-col-menu-item--active' : ''}`}
                onClick={() => run(onSortDesc)}
              >
                <ArrowDown className="h-3.5 w-3.5" aria-hidden />
                По убыванию
              </button>
              {sortDirection && onClearSort && (
                <button
                  type="button"
                  role="menuitem"
                  className="ws-mike-col-menu-item"
                  onClick={() => run(onClearSort)}
                >
                  <XCircle className="h-3.5 w-3.5" aria-hidden />
                  Сбросить сортировку
                </button>
              )}
              <div className="ws-mike-col-menu-divider" role="separator" />
            </>
          )}

          {onRun && (
            <button
              type="button"
              role="menuitem"
              className="ws-mike-col-menu-item"
              onClick={() => run(onRun)}
              disabled={disabled || isRunning}
            >
              <Play className="h-3.5 w-3.5" aria-hidden />
              {isRunning ? 'Заполнение…' : 'Запустить ИИ'}
            </button>
          )}

          {showPin && (
            <button
              type="button"
              role="menuitem"
              className="ws-mike-col-menu-item"
              onClick={() => run(isPinned ? onUnpin : onPin)}
            >
              <Pin className="h-3.5 w-3.5" aria-hidden />
              {isPinned ? 'Открепить колонку' : 'Закрепить колонку'}
            </button>
          )}

          {onEdit && (
            <button type="button" role="menuitem" className="ws-mike-col-menu-item" onClick={handleEdit}>
              <Pencil className="h-3.5 w-3.5" aria-hidden />
              Редактировать
            </button>
          )}

          {onDelete && (
            <>
              {(onRun || showPin || onEdit) && <div className="ws-mike-col-menu-divider" role="separator" />}
              <button
                type="button"
                role="menuitem"
                className="ws-mike-col-menu-item ws-mike-col-menu-item--danger"
                onClick={() => run(onDelete)}
                disabled={disabled}
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
                Удалить
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
