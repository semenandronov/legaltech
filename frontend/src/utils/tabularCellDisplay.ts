import type { TabularCell, TabularColumn } from '@/services/tabularReviewApi'

export const TABULAR_DOC_COLUMN_PX = 332
export const TABULAR_DATA_COLUMN_PX = 300
export const TABULAR_GRID_TRAIL_PX = 32

/** Display token for explicit «not found in document» (прочерк). */
export const TABULAR_NA_DISPLAY = '—'
/** Display token for pending / blank cell (no extraction yet). */
export const TABULAR_EMPTY_DISPLAY = '-'

/** Aligns with backend TABULAR_CONFIDENCE_REVIEW_THRESHOLD. */
export const TABULAR_LOW_CONFIDENCE_THRESHOLD = 0.7

const EXPLICIT_NA_VALUES = new Set([
  'N/A',
  'NA',
  'Н/Д',
  'НЕТ ДАННЫХ',
  'ОТСУТСТВУЕТ',
  'НЕ УКАЗАНО',
  'НЕ НАЙДЕНО',
  'NOT FOUND',
  'NONE',
  '—',
  '–',
])

export type TabularCellAttention = 'none' | 'low_confidence' | 'conflict'

function formatIsoDateDisplay(value: string): string {
  const match = value.trim().match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (!match) return value
  return `${match[3]}.${match[2]}.${match[1]}`
}

export function getTabularGridMinWidth(columnCount: number): number {
  return TABULAR_DOC_COLUMN_PX + columnCount * TABULAR_DATA_COLUMN_PX + TABULAR_GRID_TRAIL_PX
}

export function isExplicitTabularNaValue(value: string | null | undefined): boolean {
  if (value == null) return false
  const trimmed = value.trim()
  if (!trimmed) return false
  return EXPLICIT_NA_VALUES.has(trimmed.toUpperCase())
}

function isBlankPlaceholder(value: string): boolean {
  const v = value.trim()
  return (
    !v ||
    v === '—' ||
    v === '-' ||
    v === '–' ||
    /^[_\s\-.]+$/.test(v) ||
    /_{2,}/.test(v)
  )
}

export function getTabularCellAttention(cell: TabularCell | undefined): TabularCellAttention {
  if (!cell || cell.status === 'reviewed') return 'none'
  if (cell.status === 'conflict') return 'conflict'
  if (
    typeof cell.confidence_score === 'number' &&
    cell.confidence_score < TABULAR_LOW_CONFIDENCE_THRESHOLD &&
    (cell.status === 'completed' || cell.status === 'n_a')
  ) {
    return 'low_confidence'
  }
  return 'none'
}

export function formatTabularCellValue(
  cell: TabularCell | undefined,
  column: TabularColumn,
): string {
  const raw = cell?.cell_value
  if (cell?.status === 'skipped') {
    return TABULAR_EMPTY_DISPLAY
  }
  if (cell?.status === 'n_a' || isExplicitTabularNaValue(raw)) {
    return TABULAR_NA_DISPLAY
  }

  let cellValue = raw || TABULAR_EMPTY_DISPLAY

  if (column.column_type === 'yes_no' && typeof cellValue === 'string') {
    const yn = cellValue.trim()
    if (yn === 'Yes') cellValue = 'Да'
    else if (yn === 'No') cellValue = 'Нет'
  }

  if (column.column_type === 'date' && typeof cellValue === 'string') {
    const trimmed = cellValue.trim()
    if (trimmed && !isExplicitTabularNaValue(trimmed)) {
      cellValue = formatIsoDateDisplay(trimmed)
    }
  }

  if (typeof cellValue === 'string' && isBlankPlaceholder(cellValue)) {
    return TABULAR_EMPTY_DISPLAY
  }

  return String(cellValue)
}
