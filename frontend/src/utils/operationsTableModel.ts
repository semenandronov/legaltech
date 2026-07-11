import type { TabularColumn, TabularRow } from '@/services/tabularReviewApi'
import type { OperationTransaction } from '@/services/operationsApi'
import { applyColumnValueFilters, type ColumnValueFilterCondition } from '@/utils/tabularColumnFilters'
import { columnTypeForOperationsHeader } from '@/utils/tabularNumericUtils'

/** Fallback when Docling did not preserve column headers in row_columns. */
const OPERATIONS_FALLBACK_COLUMNS: TabularColumn[] = [
  {
    id: 'op_date',
    column_label: 'Дата',
    column_type: 'date',
    prompt: '',
    order_index: 0,
  },
  {
    id: 'op_amount',
    column_label: 'Сумма',
    column_type: 'currency',
    prompt: '',
    order_index: 1,
  },
  {
    id: 'op_description',
    column_label: 'Назначение',
    column_type: 'text',
    prompt: '',
    order_index: 2,
  },
]

function cell(value: string | null | undefined) {
  return {
    cell_value: value ?? null,
    status: 'reviewed' as const,
    confidence_score: 1,
  }
}

export function buildOperationsTabularColumns(extraHeaders: string[]): TabularColumn[] {
  if (extraHeaders.length === 0) {
    return OPERATIONS_FALLBACK_COLUMNS
  }

  const dynamic = extraHeaders.map((header, index) => ({
    id: `op_col_${index}`,
    column_label: header,
    column_type: columnTypeForOperationsHeader(header),
    prompt: '',
    order_index: index + 1,
  }))

  return [
    {
      id: 'op_date',
      column_label: 'Дата',
      column_type: 'date',
      prompt: '',
      order_index: 0,
    },
    ...dynamic,
  ]
}

export function buildOperationsTabularRows(
  transactions: OperationTransaction[],
  columns: TabularColumn[],
  extraHeaders: string[],
): TabularRow[] {
  const usePdfColumns = extraHeaders.length > 0

  return transactions.map((tx) => {
    const dateText = tx.operation_datetime_text || tx.operation_date || ''
    const amount = tx.amount_raw || (tx.amount_rub != null ? String(tx.amount_rub) : '')
    const source = tx.source_filename || tx.file_id

    const cells: Record<string, ReturnType<typeof cell>> = {
      op_date: cell(dateText),
      op_amount: cell(amount),
      op_description: cell(tx.description),
    }

    if (usePdfColumns) {
      for (let index = 0; index < extraHeaders.length; index += 1) {
        const header = extraHeaders[index]
        cells[`op_col_${index}`] = cell(tx.row_columns?.[header])
      }
    }

    for (const column of columns) {
      if (!cells[column.id]) {
        cells[column.id] = cell('')
      }
    }

    return {
      file_id: tx.id,
      file_name: source,
      file_type: 'pdf',
      status: 'reviewed',
      cells,
      _transaction: tx,
    } as TabularRow & { _transaction: OperationTransaction }
  })
}

export function filterOperationsRows(
  rows: TabularRow[],
  filters: ColumnValueFilterCondition[],
  columns: TabularColumn[],
): TabularRow[] {
  if (!filters.length) return rows
  return applyColumnValueFilters(rows, filters, columns)
}

export function filterOperationsBySearch(
  rows: TabularRow[],
  search: string,
): TabularRow[] {
  const q = search.trim().toLowerCase()
  if (!q) return rows
  return rows.filter((row) => {
    const values = Object.values(row.cells).map((c) => String(c.cell_value || '').toLowerCase())
    return values.some((value) => value.includes(q))
  })
}

export function formatAmount(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    maximumFractionDigits: 2,
  }).format(value)
}
