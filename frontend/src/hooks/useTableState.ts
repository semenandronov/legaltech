import { useState, useEffect, useCallback } from 'react'
import { SortingState, ColumnFiltersState, VisibilityState, ColumnSizingState, ColumnPinningState } from '@tanstack/react-table'
import { saveTableState, loadTableState, clearTableState } from '@/utils/tableUtils'

interface TableState {
  sorting?: SortingState
  columnFilters?: ColumnFiltersState
  columnVisibility?: VisibilityState
  columnSizing?: ColumnSizingState
  columnPinning?: ColumnPinningState
  pagination?: {
    pageIndex: number
    pageSize: number
  }
}

interface UseTableStateOptions {
  tableId: string
  autoSave?: boolean
  debounceMs?: number
}

/**
 * Хук для управления состоянием таблицы с сохранением в localStorage
 */
export function useTableState(options: UseTableStateOptions) {
  const { tableId, autoSave = true, debounceMs = 300 } = options
  
  // Загружаем сохраненное состояние при монтировании
  const savedState = loadTableState<TableState>(tableId)
  
  const [sorting, setSorting] = useState<SortingState>(savedState?.sorting || [])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>(savedState?.columnFilters || [])
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(savedState?.columnVisibility || {})
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>(savedState?.columnSizing || {})
  const [columnPinning, setColumnPinning] = useState<ColumnPinningState>(savedState?.columnPinning || { left: [], right: [] })
  const [pagination, setPagination] = useState(savedState?.pagination || { pageIndex: 0, pageSize: 25 })
  
  // Функция сохранения состояния
  const saveState = useCallback(() => {
    if (!autoSave) return
    
    saveTableState(tableId, {
      sorting,
      columnFilters,
      columnVisibility,
      columnSizing,
      columnPinning,
      pagination,
    })
  }, [tableId, autoSave, sorting, columnFilters, columnVisibility, columnSizing, columnPinning, pagination])
  
  // Debounced сохранение
  useEffect(() => {
    if (!autoSave) return
    
    const timeoutId = setTimeout(() => {
      saveState()
    }, debounceMs)
    
    return () => clearTimeout(timeoutId)
  }, [saveState, debounceMs, autoSave])
  
  // Функция сброса состояния
  const resetState = useCallback(() => {
    setSorting([])
    setColumnFilters([])
    setColumnVisibility({})
    setColumnSizing({})
    setColumnPinning({ left: [], right: [] })
    setPagination({ pageIndex: 0, pageSize: 25 })
    clearTableState(tableId)
  }, [tableId])
  
  // Функция загрузки сохраненного состояния
  const loadSavedState = useCallback(() => {
    const saved = loadTableState<TableState>(tableId)
    if (saved) {
      if (saved.sorting) setSorting(saved.sorting)
      if (saved.columnFilters) setColumnFilters(saved.columnFilters)
      if (saved.columnVisibility) setColumnVisibility(saved.columnVisibility)
      if (saved.columnSizing) setColumnSizing(saved.columnSizing)
      if (saved.columnPinning) setColumnPinning(saved.columnPinning)
      if (saved.pagination) setPagination(saved.pagination)
    }
  }, [tableId])
  
  return {
    // Состояния
    sorting,
    columnFilters,
    columnVisibility,
    columnSizing,
    columnPinning,
    pagination,
    
    // Сеттеры
    setSorting,
    setColumnFilters,
    setColumnVisibility,
    setColumnSizing,
    setColumnPinning,
    setPagination,
    
    // Утилиты
    saveState,
    resetState,
    loadSavedState,
  }
}

