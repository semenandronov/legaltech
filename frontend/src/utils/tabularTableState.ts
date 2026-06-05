import type { TableData, TabularColumn, TabularCell } from '../services/tabularReviewApi'

export const emptyPendingCell = (): TabularCell => ({
  cell_value: null,
  status: 'pending',
})

/** Stable key for a cell currently being extracted: `${columnId}:${fileId}` */
export function processingCellKey(columnId: string, fileId: string): string {
  return `${columnId}:${fileId}`
}

export function buildProcessingCellKeys(columnId: string, fileIds: string[]): Set<string> {
  return new Set(fileIds.map((fileId) => processingCellKey(columnId, fileId)))
}

export function clearProcessingCellKey(
  keys: Set<string>,
  columnId: string,
  fileId: string,
): Set<string> {
  const key = processingCellKey(columnId, fileId)
  if (!keys.has(key)) {
    return keys
  }
  const next = new Set(keys)
  next.delete(key)
  return next
}

export function clearProcessingCellKeysForColumn(keys: Set<string>, columnId: string): Set<string> {
  const prefix = `${columnId}:`
  let changed = false
  const next = new Set<string>()
  for (const key of keys) {
    if (key.startsWith(prefix)) {
      changed = true
      continue
    }
    next.add(key)
  }
  return changed ? next : keys
}

/** API cell payload from POST /columns/{id}/run */
export interface RunColumnCellPayload {
  file_id: string
  column_id: string
  cell_value?: string | null
  normalized_value?: string | null
  verbatim_extract?: string | null
  reasoning?: string | null
  confidence_score?: number | null
  source_page?: number | null
  source_section?: string | null
  source_references?: TabularCell['source_references']
  status?: TabularCell['status']
  candidates?: TabularCell['candidates']
}

export interface TabularCellRealtimeUpdate extends RunColumnCellPayload {
  cell_id?: string
}

export function runPayloadToTabularCell(payload: RunColumnCellPayload): TabularCell {
  return {
    cell_value: payload.cell_value ?? null,
    normalized_value: payload.normalized_value ?? undefined,
    verbatim_extract: payload.verbatim_extract ?? undefined,
    reasoning: payload.reasoning ?? undefined,
    confidence_score: payload.confidence_score ?? undefined,
    source_page: payload.source_page ?? undefined,
    source_section: payload.source_section ?? undefined,
    source_references: payload.source_references,
    status: payload.status ?? 'completed',
    candidates: payload.candidates,
  }
}

/** Merge saved cells from run response into table state (no table-data fetch). */
export function applyColumnCellsToTableData(
  prev: TableData,
  columnId: string,
  cells: RunColumnCellPayload[],
): TableData {
  if (!cells.length) {
    return prev
  }
  const byFile = new Map(cells.map((c) => [c.file_id, c]))
  return {
    ...prev,
    rows: prev.rows.map((row) => {
      const payload = byFile.get(row.file_id)
      if (!payload) {
        return row
      }
      return {
        ...row,
        cells: {
          ...row.cells,
          [columnId]: runPayloadToTabularCell(payload),
        },
      }
    }),
  }
}

/** Apply one realtime cell update (WebSocket) into local table state. */
export function applySingleColumnCellToTableData(
  prev: TableData,
  update: TabularCellRealtimeUpdate,
): TableData {
  if (!update.column_id || !update.file_id) {
    return prev
  }
  return applyColumnCellsToTableData(prev, update.column_id, [update])
}

/** Remove a column from local table state (after DELETE /columns/{id}). */
export function removeColumnFromTableData(prev: TableData, columnId: string): TableData {
  const columns = prev.columns.filter((c) => c.id !== columnId)
  if (columns.length === prev.columns.length) {
    return prev
  }
  return {
    ...prev,
    columns,
    rows: prev.rows.map((row) => {
      if (!(columnId in row.cells)) {
        return row
      }
      const { [columnId]: _removed, ...cells } = row.cells
      return { ...row, cells }
    }),
  }
}

/** Add new column(s) to local table state without refetching table-data. */
export function appendColumnsToTableData(
  prev: TableData,
  newColumns: TabularColumn[],
): TableData {
  const existingIds = new Set(prev.columns.map((c) => c.id))
  const toAdd = newColumns.filter((c) => !existingIds.has(c.id))
  if (toAdd.length === 0) {
    return prev
  }
  return {
    ...prev,
    columns: [...prev.columns, ...toAdd],
    rows: prev.rows.map((row) => {
      const cells = { ...row.cells }
      for (const col of toAdd) {
        cells[col.id] = emptyPendingCell()
      }
      return { ...row, cells }
    }),
  }
}
