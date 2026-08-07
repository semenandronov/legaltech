"use client"

import { useEffect, useRef, useState } from 'react'
import { ChevronDown, FileUp, Plus, Upload } from 'lucide-react'
import { MikeTableToolbar } from './mike/MikeTableToolbar'

interface TabularReviewToolbarProps {
  onAddColumns?: () => void
  onImportChecklist?: () => void
  onUpdateDocuments?: () => void
  processing?: boolean
  selectedCount?: number
  onDeleteSelected?: () => void
}

export function TabularReviewToolbar({
  onAddColumns,
  onImportChecklist,
  onUpdateDocuments,
  processing = false,
  selectedCount = 0,
  onDeleteSelected,
}: TabularReviewToolbarProps) {
  const [actionsOpen, setActionsOpen] = useState(false)
  const actionsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!actionsOpen) return
    function handleClickOutside(event: MouseEvent) {
      if (actionsRef.current && !actionsRef.current.contains(event.target as Node)) {
        setActionsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [actionsOpen])

  return (
    <MikeTableToolbar
      actions={
        <>
          {selectedCount > 0 && onDeleteSelected && (
            <div ref={actionsRef} className="relative">
              <button
                type="button"
                onClick={() => setActionsOpen((value) => !value)}
                className="flex items-center gap-1 text-xs font-medium text-gray-600 hover:text-gray-900 transition-colors"
              >
                Действия
                <ChevronDown className="h-3.5 w-3.5" aria-hidden />
              </button>
              {actionsOpen && (
                <div className="absolute top-full right-0 mt-1 w-36 rounded-lg border border-gray-100 bg-white shadow-lg z-50 overflow-hidden">
                  <button
                    type="button"
                    className="w-full px-3 py-1.5 text-left text-xs text-red-600 hover:bg-red-50 transition-colors"
                    onClick={() => {
                      setActionsOpen(false)
                      onDeleteSelected()
                    }}
                  >
                    Удалить
                  </button>
                </div>
              )}
            </div>
          )}

          {onUpdateDocuments && (
            <button
              type="button"
              onClick={onUpdateDocuments}
              disabled={processing}
              className={`flex items-center gap-1 text-xs font-medium transition-colors ${
                processing
                  ? 'text-gray-300 cursor-default'
                  : 'text-gray-700 hover:text-gray-900'
              }`}
            >
              <Upload className="h-3.5 w-3.5" aria-hidden />
              Добавить документы
            </button>
          )}
          {onImportChecklist && (
            <button
              type="button"
              onClick={onImportChecklist}
              disabled={processing}
              className={`flex items-center gap-1 text-xs font-medium transition-colors ${
                processing
                  ? 'text-gray-300 cursor-default'
                  : 'text-gray-700 hover:text-gray-900'
              }`}
            >
              <FileUp className="h-3.5 w-3.5" aria-hidden />
              Импорт чек-листа
            </button>
          )}
          {onAddColumns && (
          <button
            type="button"
            onClick={onAddColumns}
            disabled={processing}
            className={`flex items-center gap-1 text-xs font-medium transition-colors ${
              processing
                ? 'text-gray-300 cursor-default'
                : 'text-gray-700 hover:text-gray-900'
            }`}
          >
            <Plus className="h-3.5 w-3.5" aria-hidden />
            Добавить колонки
          </button>
          )}
        </>
      }
    />
  )
}
