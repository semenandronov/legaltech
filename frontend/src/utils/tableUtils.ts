import { ColumnDef } from "@tanstack/react-table"

/**
 * Универсальная функция получения значения ячейки
 */
export function getCellValue<T>(row: T, columnId: string): any {
  const value = (row as any)[columnId]
  if (value && typeof value === 'object' && 'cell_value' in value) {
    return value.cell_value
  }
  return value ?? null
}

/**
 * Форматирование содержимого ячейки для отображения
 */
export function formatCellContent(value: any, emptyValue: string = "-"): string {
  if (value === null || value === undefined || value === "") {
    return emptyValue
  }
  if (typeof value === 'object' && 'cell_value' in value) {
    return value.cell_value ?? emptyValue
  }
  return String(value)
}

/**
 * Сохранение состояния таблицы в localStorage
 */
export function saveTableState(
  tableId: string,
  state: {
    sorting?: any[]
    columnFilters?: any[]
    columnVisibility?: Record<string, boolean>
    columnSizing?: Record<string, number>
    columnPinning?: { left?: string[]; right?: string[] }
    pagination?: { pageIndex: number; pageSize: number }
  }
): void {
  try {
    const key = `table_state_${tableId}`
    localStorage.setItem(key, JSON.stringify(state))
  } catch (error) {
    console.warn('Failed to save table state:', error)
  }
}

/**
 * Загрузка состояния таблицы из localStorage
 */
export function loadTableState<T>(tableId: string): Partial<T> | null {
  try {
    const key = `table_state_${tableId}`
    const saved = localStorage.getItem(key)
    if (saved) {
      return JSON.parse(saved) as T
    }
  } catch (error) {
    console.warn('Failed to load table state:', error)
  }
  return null
}

/**
 * Очистка сохраненного состояния таблицы
 */
export function clearTableState(tableId: string): void {
  try {
    const key = `table_state_${tableId}`
    localStorage.removeItem(key)
  } catch (error) {
    console.warn('Failed to clear table state:', error)
  }
}

/**
 * Создание базовой колонки с сортировкой
 */
export function createSortableColumn<T>(
  accessorKey: string,
  header: string,
  options?: {
    cell?: (value: any, row: T) => React.ReactNode
    width?: number
    minWidth?: number
    maxWidth?: number
  }
): ColumnDef<T> {
  return {
    accessorKey,
    header: ({ column }) => {
      return (
        <div onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {header}
        </div>
      )
    },
    cell: options?.cell
      ? ({ row }) => options.cell!(row.getValue(accessorKey), row.original)
      : ({ row }) => formatCellContent(row.getValue(accessorKey)),
    size: options?.width,
    minSize: options?.minWidth,
    maxSize: options?.maxWidth,
  }
}

/**
 * Debounce функция для фильтров
 */
export function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: NodeJS.Timeout | null = null
  
  return function executedFunction(...args: Parameters<T>) {
    const later = () => {
      timeout = null
      func(...args)
    }
    
    if (timeout) {
      clearTimeout(timeout)
    }
    timeout = setTimeout(later, wait)
  }
}

