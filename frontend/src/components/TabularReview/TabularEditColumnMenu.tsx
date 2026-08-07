"use client"

import { useEffect, useRef, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  Loader2,
  MoreHorizontal,
  Pencil,
  Play,
  Trash2,
  XCircle,
} from 'lucide-react'
import type { TabularColumn } from '@/services/tabularReviewApi'

interface TabularEditColumnMenuProps {
  column: TabularColumn
  disabled?: boolean
  isRunning?: boolean
  sortDirection?: 'asc' | 'desc' | false
  onOpenEdit?: () => void
  onDelete: () => void
  onRun?: () => void
  onSortAsc?: () => void
  onSortDesc?: () => void
  onClearSort?: () => void
}

export function TabularEditColumnMenu({
  column,
  disabled = false,
  isRunning = false,
  sortDirection = false,
  onOpenEdit,
  onDelete,
  onRun,
  onSortAsc,
  onSortDesc,
  onClearSort,
}: TabularEditColumnMenuProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const showSort = Boolean(onSortAsc || onSortDesc)

  useEffect(() => {
    if (!open) return

    function handlePointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false)
      }
    }

    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  const runAndClose = (fn?: () => void) => {
    setOpen(false)
    fn?.()
  }

  return (
    <div className="ws-mike-col-menu-actions">
      {onRun && column.column_type !== 'manual_input' && (
        <button
          type="button"
          className="ws-mike-col-run-btn"
          disabled={disabled || isRunning}
          onClick={(event) => {
            event.stopPropagation()
            if (disabled || isRunning) return
            onRun()
          }}
          title={isRunning ? 'Заполнение…' : 'Запустить ИИ для колонки'}
          aria-label={isRunning ? 'Заполнение колонки' : 'Запустить ИИ для колонки'}
        >
          {isRunning ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <Play className="h-3.5 w-3.5" aria-hidden />
          )}
        </button>
      )}
      <div
        ref={rootRef}
        className="ws-mike-col-menu"
        onClick={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          disabled={disabled}
          onClick={(event) => {
            event.stopPropagation()
            if (disabled) return
            setOpen((value) => !value)
          }}
          className={`ws-mike-col-menu-trigger ${disabled ? 'ws-mike-col-menu-trigger--disabled' : ''}`}
          aria-label={`Меню колонки ${column.column_label}`}
          aria-expanded={open}
        >
          <MoreHorizontal className="h-4 w-4" />
        </button>

        {open && (
          <div className="ws-mike-col-menu-dropdown" role="menu">
            {onOpenEdit && (
              <button
                type="button"
                className="ws-mike-col-menu-item"
                onClick={() => runAndClose(onOpenEdit)}
              >
                <Pencil className="h-3.5 w-3.5" aria-hidden />
                Редактировать колонку
              </button>
            )}

            {showSort && (
              <>
                {onOpenEdit && <div className="ws-mike-col-menu-divider" role="separator" />}
                <button
                  type="button"
                  className="ws-mike-col-menu-item"
                  onClick={() => runAndClose(onSortAsc)}
                >
                  <ArrowUp className="h-3.5 w-3.5" aria-hidden />
                  По возрастанию
                </button>
                <button
                  type="button"
                  className="ws-mike-col-menu-item"
                  onClick={() => runAndClose(onSortDesc)}
                >
                  <ArrowDown className="h-3.5 w-3.5" aria-hidden />
                  По убыванию
                </button>
                {sortDirection && onClearSort && (
                  <button
                    type="button"
                    className="ws-mike-col-menu-item"
                    onClick={() => runAndClose(onClearSort)}
                  >
                    <XCircle className="h-3.5 w-3.5" aria-hidden />
                    Сбросить сортировку
                  </button>
                )}
              </>
            )}

            <div className="ws-mike-col-menu-divider" role="separator" />
            <button
              type="button"
              className="ws-mike-col-menu-item ws-mike-col-menu-item--danger"
              onClick={() => runAndClose(onDelete)}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
              Удалить колонку
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export type { TabularColumnSavePayload } from './TabularEditColumnMenu.types'
