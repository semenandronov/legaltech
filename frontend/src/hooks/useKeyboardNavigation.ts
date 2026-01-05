"use client"

import { useEffect, useCallback, useRef } from "react"
import { Table } from "@tanstack/react-table"

export interface KeyboardNavigationOptions {
  table: Table<any>
  enabled?: boolean
  onCellEdit?: (rowId: string, columnId: string) => void
  onCellSelect?: (rowId: string, columnId: string) => void
  onRowDelete?: (rowId: string) => void
  onRowCopy?: (rowId: string) => void
  onRowPaste?: (rowId: string) => void
  onSave?: () => void
  onUndo?: () => void
  onRedo?: () => void
  onSearch?: () => void
  onFilter?: () => void
  onExport?: () => void
  onSelectAll?: () => void
  onDeselectAll?: () => void
  onNextPage?: () => void
  onPreviousPage?: () => void
  onFirstPage?: () => void
  onLastPage?: () => void
}

/**
 * Hook for keyboard navigation in tables
 * 
 * Shortcuts:
 * - Arrow keys: Navigate between cells
 * - Enter: Edit cell
 * - Delete/Backspace: Delete row (with confirmation)
 * - Ctrl/Cmd + C: Copy row
 * - Ctrl/Cmd + V: Paste row
 * - Ctrl/Cmd + S: Save
 * - Ctrl/Cmd + Z: Undo
 * - Ctrl/Cmd + Shift + Z: Redo
 * - Ctrl/Cmd + F: Search
 * - Ctrl/Cmd + Shift + F: Advanced filters
 * - Ctrl/Cmd + E: Export
 * - Ctrl/Cmd + A: Select all
 * - Ctrl/Cmd + Shift + A: Deselect all
 * - Page Up/Down: Navigate pages
 * - Home/End: First/Last page
 * - Escape: Cancel edit/close modals
 */
export function useKeyboardNavigation(options: KeyboardNavigationOptions) {
  const {
    table,
    enabled = true,
    onCellEdit,
    onCellSelect,
    onRowDelete,
    onRowCopy,
    onRowPaste,
    onSave,
    onUndo,
    onRedo,
    onSearch,
    onFilter,
    onExport,
    onSelectAll,
    onDeselectAll,
    onNextPage,
    onPreviousPage,
    onFirstPage,
    onLastPage,
  } = options

  const currentRowIndex = useRef<number>(0)
  const currentColumnIndex = useRef<number>(0)
  const isEditing = useRef<boolean>(false)

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (!enabled) return

      // Don't handle shortcuts when typing in inputs
      const target = event.target as HTMLElement
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
      ) {
        // Allow Escape to cancel editing
        if (event.key === "Escape" && isEditing.current) {
          isEditing.current = false
          return
        }
        // Allow Enter to submit (but not navigate)
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
          return
        }
        // Don't handle other keys when editing
        return
      }

      const rows = table.getRowModel().rows
      const columns = table.getVisibleLeafColumns()

      // Arrow keys navigation
      if (event.key === "ArrowUp" || event.key === "ArrowDown" || event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault()

        if (rows.length === 0 || columns.length === 0) return

        if (event.key === "ArrowUp") {
          currentRowIndex.current = Math.max(0, currentRowIndex.current - 1)
        } else if (event.key === "ArrowDown") {
          currentRowIndex.current = Math.min(rows.length - 1, currentRowIndex.current + 1)
        } else if (event.key === "ArrowLeft") {
          currentColumnIndex.current = Math.max(0, currentColumnIndex.current - 1)
        } else if (event.key === "ArrowRight") {
          currentColumnIndex.current = Math.min(columns.length - 1, currentColumnIndex.current + 1)
        }

        const row = rows[currentRowIndex.current]
        const column = columns[currentColumnIndex.current]

        if (row && column && onCellSelect) {
          onCellSelect(row.id, column.id)
        }

        // Scroll to cell
        const cellElement = document.querySelector(
          `[data-row-id="${row.id}"][data-column-id="${column.id}"]`
        )
        if (cellElement) {
          cellElement.scrollIntoView({ behavior: "smooth", block: "nearest" })
        }
        return
      }

      // Enter: Edit cell
      if (event.key === "Enter" && !event.ctrlKey && !event.metaKey) {
        event.preventDefault()
        const row = rows[currentRowIndex.current]
        const column = columns[currentColumnIndex.current]
        if (row && column && onCellEdit) {
          isEditing.current = true
          onCellEdit(row.id, column.id)
        }
        return
      }

      // Delete/Backspace: Delete row
      if ((event.key === "Delete" || event.key === "Backspace") && !event.ctrlKey && !event.metaKey) {
        const row = rows[currentRowIndex.current]
        if (row && onRowDelete) {
          if (window.confirm("Вы уверены, что хотите удалить эту строку?")) {
            onRowDelete(row.id)
            // Adjust row index if needed
            if (currentRowIndex.current >= rows.length - 1) {
              currentRowIndex.current = Math.max(0, currentRowIndex.current - 1)
            }
          }
        }
        return
      }

      // Ctrl/Cmd + C: Copy row
      if ((event.ctrlKey || event.metaKey) && event.key === "c" && !event.shiftKey) {
        event.preventDefault()
        const row = rows[currentRowIndex.current]
        if (row && onRowCopy) {
          onRowCopy(row.id)
        }
        return
      }

      // Ctrl/Cmd + V: Paste row
      if ((event.ctrlKey || event.metaKey) && event.key === "v" && !event.shiftKey) {
        event.preventDefault()
        const row = rows[currentRowIndex.current]
        if (row && onRowPaste) {
          onRowPaste(row.id)
        }
        return
      }

      // Ctrl/Cmd + S: Save
      if ((event.ctrlKey || event.metaKey) && event.key === "s") {
        event.preventDefault()
        if (onSave) {
          onSave()
        }
        return
      }

      // Ctrl/Cmd + Z: Undo
      if ((event.ctrlKey || event.metaKey) && event.key === "z" && !event.shiftKey) {
        event.preventDefault()
        if (onUndo) {
          onUndo()
        }
        return
      }

      // Ctrl/Cmd + Shift + Z: Redo
      if ((event.ctrlKey || event.metaKey) && event.key === "z" && event.shiftKey) {
        event.preventDefault()
        if (onRedo) {
          onRedo()
        }
        return
      }

      // Ctrl/Cmd + F: Search
      if ((event.ctrlKey || event.metaKey) && event.key === "f") {
        event.preventDefault()
        if (onSearch) {
          onSearch()
        }
        return
      }

      // Ctrl/Cmd + Shift + F: Advanced filters
      if ((event.ctrlKey || event.metaKey) && event.key === "f" && event.shiftKey) {
        event.preventDefault()
        if (onFilter) {
          onFilter()
        }
        return
      }

      // Ctrl/Cmd + E: Export
      if ((event.ctrlKey || event.metaKey) && event.key === "e") {
        event.preventDefault()
        if (onExport) {
          onExport()
        }
        return
      }

      // Ctrl/Cmd + A: Select all
      if ((event.ctrlKey || event.metaKey) && event.key === "a" && !event.shiftKey) {
        event.preventDefault()
        if (onSelectAll) {
          onSelectAll()
        }
        return
      }

      // Ctrl/Cmd + Shift + A: Deselect all
      if ((event.ctrlKey || event.metaKey) && event.key === "a" && event.shiftKey) {
        event.preventDefault()
        if (onDeselectAll) {
          onDeselectAll()
        }
        return
      }

      // Page Up: Previous page
      if (event.key === "PageUp") {
        event.preventDefault()
        if (onPreviousPage) {
          onPreviousPage()
        } else {
          table.previousPage()
        }
        return
      }

      // Page Down: Next page
      if (event.key === "PageDown") {
        event.preventDefault()
        if (onNextPage) {
          onNextPage()
        } else {
          table.nextPage()
        }
        return
      }

      // Home: First page
      if (event.key === "Home" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault()
        if (onFirstPage) {
          onFirstPage()
        } else {
          table.setPageIndex(0)
        }
        return
      }

      // End: Last page
      if (event.key === "End" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault()
        if (onLastPage) {
          onLastPage()
        } else {
          table.setPageIndex(table.getPageCount() - 1)
        }
        return
      }

      // Escape: Cancel edit/close modals
      if (event.key === "Escape") {
        if (isEditing.current) {
          isEditing.current = false
        }
        return
      }
    },
    [
      enabled,
      table,
      onCellEdit,
      onCellSelect,
      onRowDelete,
      onRowCopy,
      onRowPaste,
      onSave,
      onUndo,
      onRedo,
      onSearch,
      onFilter,
      onExport,
      onSelectAll,
      onDeselectAll,
      onNextPage,
      onPreviousPage,
      onFirstPage,
      onLastPage,
    ]
  )

  useEffect(() => {
    if (!enabled) return

    window.addEventListener("keydown", handleKeyDown)
    return () => {
      window.removeEventListener("keydown", handleKeyDown)
    }
  }, [enabled, handleKeyDown])

  return {
    currentRowIndex: currentRowIndex.current,
    currentColumnIndex: currentColumnIndex.current,
    isEditing: isEditing.current,
  }
}

