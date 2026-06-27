import type { TabularCell, TabularColumn } from '@/services/tabularReviewApi'

export const TABULAR_DOC_COLUMN_PX = 332
export const TABULAR_DATA_COLUMN_PX = 300
export const TABULAR_GRID_TRAIL_PX = 32

function formatIsoDateDisplay(value: string): string {
  const match = value.trim().match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (!match) return value
  return `${match[3]}.${match[2]}.${match[1]}`
}

export function getTabularGridMinWidth(columnCount: number): number {
  return TABULAR_DOC_COLUMN_PX + columnCount * TABULAR_DATA_COLUMN_PX + TABULAR_GRID_TRAIL_PX
}

export function formatTabularCellValue(
  cell: TabularCell | undefined,
  column: TabularColumn,
): string {
  let cellValue = cell?.cell_value || '-'

  if (column.column_type === 'yes_no' && typeof cellValue === 'string') {
    const yn = cellValue.trim()
    if (yn === 'Yes') cellValue = 'Да'
    else if (yn === 'No') cellValue = 'Нет'
  }

  if (column.column_type === 'date' && typeof cellValue === 'string') {
    const trimmed = cellValue.trim()
    if (trimmed && trimmed.toUpperCase() !== 'N/A') {
      cellValue = formatIsoDateDisplay(trimmed)
    }
  }

  if (typeof cellValue === 'string') {
    const v = cellValue.trim()
    if (
      !v ||
      v.toUpperCase() === 'N/A' ||
      v === '—' ||
      v === '-' ||
      v === '–' ||
      /^[_\s\-.]+$/.test(v) ||
      /_{2,}/.test(v)
    ) {
      return '-'
    }
  }

  return String(cellValue)
}
