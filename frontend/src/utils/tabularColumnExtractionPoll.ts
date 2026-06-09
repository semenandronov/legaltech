import type { TableData } from '../services/tabularReviewApi'

/** Cells saved to DB during extraction are no longer `pending`. */
export function countResolvedColumnCells(data: TableData, columnId: string): number {
  return data.rows.reduce((count, row) => {
    const cell = row.cells[columnId]
    if (cell?.status && cell.status !== 'pending') {
      return count + 1
    }
    return count
  }, 0)
}

export function isColumnExtractionDone(
  data: TableData,
  columnId: string,
  expectedTasks: number,
): boolean {
  if (expectedTasks <= 0) {
    return true
  }
  return countResolvedColumnCells(data, columnId) >= expectedTasks
}

export interface ColumnExtractionPollController {
  stop: () => void
}

export interface ColumnExtractionPollOptions {
  columnId: string
  expectedTasks: number
  fetchTableData: () => Promise<TableData | null>
  onTableData: (data: TableData) => void
  onProgress?: (resolved: number, total: number) => void
  onComplete: () => void
  onTimeout: () => void
  intervalMs?: number
  maxAttempts?: number
}

/** Poll table-data until column cells leave `pending` (fallback when WebSocket is down). */
export function startColumnExtractionPoll(
  options: ColumnExtractionPollOptions,
): ColumnExtractionPollController {
  const {
    columnId,
    expectedTasks,
    fetchTableData,
    onTableData,
    onProgress,
    onComplete,
    onTimeout,
    intervalMs = 3000,
    maxAttempts = 200,
  } = options

  let attempts = 0
  let stopped = false

  const tick = async () => {
    if (stopped) {
      return
    }
    attempts += 1
    if (attempts > maxAttempts) {
      stopped = true
      clearInterval(timer)
      onTimeout()
      return
    }

    const data = await fetchTableData()
    if (!data || stopped) {
      return
    }

    onTableData(data)
    const resolved = countResolvedColumnCells(data, columnId)
    onProgress?.(resolved, expectedTasks)

    if (isColumnExtractionDone(data, columnId, expectedTasks)) {
      stopped = true
      clearInterval(timer)
      onComplete()
    }
  }

  const timer = setInterval(() => {
    void tick()
  }, intervalMs)
  void tick()

  return {
    stop: () => {
      if (stopped) {
        return
      }
      stopped = true
      clearInterval(timer)
    },
  }
}
