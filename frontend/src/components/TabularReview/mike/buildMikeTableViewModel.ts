import type { ReactNode } from 'react'
import type { TabularCell, TabularColumn, TabularRow } from '@/services/tabularReviewApi'
import { formatTabularCellValue } from '@/utils/tabularCellDisplay'
import type { MikeCellColumnMeta } from './MikeTabularCell'
import type { MikeTableCellVM, MikeTableColumnVM, MikeTableRowVM } from './types'

export interface MikeGridRowInput {
  fileId: string
  fileName: string
  cells: Record<string, TabularCell | undefined>
}

export function buildMikeColumnMeta(columns: TabularColumn[]): Record<string, MikeCellColumnMeta> {
  const meta: Record<string, MikeCellColumnMeta> = {}
  for (const column of columns) {
    meta[column.id] = {
      column_type: column.column_type,
      column_config: column.column_config,
    }
  }
  return meta
}

export function buildMikeRowsFromGrid(
  gridRows: MikeGridRowInput[],
  columns: TabularColumn[],
  processingCellKeys?: Set<string>,
): MikeTableRowVM[] {
  return gridRows.map((row) => {
    const cells: Record<string, MikeTableCellVM> = {}

    for (const column of columns) {
      const raw = row.cells[column.id]
      const displayValue = formatTabularCellValue(raw, column)
      const isProcessing = processingCellKeys?.has(`${column.id}:${row.fileId}`) ?? false

      cells[column.id] = {
        displayValue,
        rawValue: raw?.cell_value ?? '',
        status: raw?.status ?? 'pending',
        isProcessing,
        flag: raw?.status === 'reviewed' ? 'reviewed' : undefined,
      }
    }

    return {
      fileId: row.fileId,
      fileName: row.fileName,
      cells,
    }
  })
}

export function buildMikeTableRows(
  rows: TabularRow[],
  columns: TabularColumn[],
  cellsByRow: Map<string, Record<string, TabularCell | undefined>>,
  processingCellKeys?: Set<string>,
): MikeTableRowVM[] {
  return rows.map((row) => {
    const rowCells = cellsByRow.get(row.file_id) ?? {}
    const cells: Record<string, MikeTableCellVM> = {}

    for (const column of columns) {
      const raw = rowCells[column.id]
      const displayValue = formatTabularCellValue(raw, column)
      const isProcessing = processingCellKeys?.has(`${column.id}:${row.file_id}`) ?? false

      cells[column.id] = {
        displayValue,
        rawValue: raw?.cell_value ?? '',
        status: raw?.status ?? 'pending',
        isProcessing,
        flag: raw?.status === 'reviewed' ? 'reviewed' : undefined,
      }
    }

    return {
      fileId: row.file_id,
      fileName: row.file_name,
      cells,
    }
  })
}

export function buildMikeTableColumns(
  columns: TabularColumn[],
  renderColumnMenu: (column: TabularColumn) => ReactNode,
): MikeTableColumnVM[] {
  return columns.map((column) => ({
    id: column.id,
    label: column.column_label,
    menu: renderColumnMenu(column),
  }))
}
