import type { MikeTableRowVM } from './types'

const MIN_ROW_HEIGHT = 40
const MAX_ROW_HEIGHT = 800
const LINE_HEIGHT_PX = 18
const VERTICAL_PADDING_PX = 16
const CHARS_PER_LINE = 42

function countTextLines(text: string): number {
  if (!text || text === '-' || text === '—') return 0
  const explicitLines = text.split('\n').length
  const wrappedLines = Math.ceil(text.replace(/\s+/g, ' ').trim().length / CHARS_PER_LINE)
  return Math.max(explicitLines, wrappedLines, 1)
}

/** Оценка высоты строки для виртуализации при многострочных ячейках. */
export function estimateMikeRowHeight(
  row: MikeTableRowVM | undefined,
  columnIds: string[],
): number {
  if (!row) return MIN_ROW_HEIGHT

  let maxLines = countTextLines(row.fileName)

  for (const columnId of columnIds) {
    const value = row.cells[columnId]?.displayValue ?? ''
    maxLines = Math.max(maxLines, countTextLines(value))
  }

  const estimated = maxLines * LINE_HEIGHT_PX + VERTICAL_PADDING_PX
  return Math.min(MAX_ROW_HEIGHT, Math.max(MIN_ROW_HEIGHT, estimated))
}
