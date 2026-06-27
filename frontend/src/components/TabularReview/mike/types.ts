import type { ReactNode } from 'react'

/** View-model колонки для Mike TRTable (только отображение). */
export interface MikeTableColumnVM {
  id: string
  label: string
  menu?: ReactNode
}

/** View-model ячейки для Mike TabularCell. */
export interface MikeTableCellVM {
  displayValue: string
  /** Сырое значение для inline-редактирования */
  rawValue: string
  status: string
  isProcessing: boolean
  flag?: 'green' | 'grey' | 'yellow' | 'red' | 'reviewed'
}

/** View-model строки документа. */
export interface MikeTableRowVM {
  fileId: string
  fileName: string
  cells: Record<string, MikeTableCellVM>
}

export interface MikeHighlightedCell {
  fileId: string
  columnId: string
}
