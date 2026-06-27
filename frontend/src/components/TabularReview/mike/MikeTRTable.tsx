"use client"

import { forwardRef, useCallback, useImperativeHandle, useRef, useState } from 'react'
import { Loader2, Plus, Table2, Upload, LayoutTemplate } from 'lucide-react'
import { MikeTabularCell, type MikeCellColumnMeta } from './MikeTabularCell'
import type { MikeHighlightedCell, MikeTableColumnVM, MikeTableRowVM } from './types'
import {
  COL_W,
  DATA_COL_W_PX,
  DOC_COL_W,
  DOC_COL_W_PX,
  STICKY_CELL_BG,
  SkeletonDot,
  SkeletonLine,
  TABLE_CHECKBOX_CLASS,
  TABLE_BODY_STICKY_DOC_Z,
  TABLE_HEADER_CORNER_Z,
  TABLE_HEADER_ROW_Z,
} from './mikeTablePrimitives'

const SKELETON_COLS = 4
const SKELETON_ROWS = 5
const STICKY_LEFT_PX = DOC_COL_W_PX

export interface MikeTRTableHandle {
  scrollToCell: (columnId: string, fileId: string, columnIds: string[], rowFileIds: string[]) => void
}

export interface MikeTRTableProps {
  loading?: boolean
  reviewId: string
  columns: MikeTableColumnVM[]
  rows: MikeTableRowVM[]
  columnMeta: Record<string, MikeCellColumnMeta>
  openPopoverCell?: { fileId: string; columnId: string } | null
  onPopoverCellChange?: (cell: { fileId: string; columnId: string } | null) => void
  editingCellKey?: string | null
  onEditingCellKeyChange?: (key: string | null) => void
  selectedDocIds?: string[]
  highlightedCell?: MikeHighlightedCell | null
  uploadingFilenames?: string[]
  dragOverFiles?: boolean
  addColumnDisabled?: boolean
  addColumnButtonRef?: React.Ref<HTMLButtonElement>
  onSelectionChange?: (ids: string[]) => void
  onAddColumn?: () => void
  onAddDocuments?: () => void
  onOpenTemplates?: () => void
  onDocumentClick?: (fileId: string, firstColumnId: string) => void
  onViewInDocument?: (fileId: string, columnId: string, citationIndex: number) => void
  onCellSave?: (fileId: string, columnId: string, value: string) => Promise<void>
  scrollRef?: (node: HTMLDivElement | null) => void
  virtualTopSpacer?: number
  virtualBottomSpacer?: number
  virtualRows?: Array<{ index: number }>
  rowRef?: (rowIndex: number) => (node: HTMLDivElement | null) => void
  emptyFilteredMessage?: string
}

/**
 * Mike TRTable — чистый UI-слой (копия willchen96/mike TRTable).
 * Данные и колбэки приходят снаружи через view-model.
 */
export const MikeTRTable = forwardRef<MikeTRTableHandle, MikeTRTableProps>(function MikeTRTable(
  {
    loading = false,
    reviewId,
    columns,
    rows,
    columnMeta,
    openPopoverCell = null,
    onPopoverCellChange,
    editingCellKey: editingCellKeyProp = null,
    onEditingCellKeyChange,
    selectedDocIds = [],
    highlightedCell,
    uploadingFilenames = [],
    dragOverFiles = false,
    addColumnDisabled = false,
    addColumnButtonRef,
    onSelectionChange,
    onAddColumn,
    onAddDocuments,
    onOpenTemplates,
    onDocumentClick,
    onViewInDocument,
    onCellSave,
    scrollRef,
    virtualTopSpacer = 0,
    virtualBottomSpacer = 0,
    virtualRows,
    rowRef,
    emptyFilteredMessage = 'Нет результатов.',
  },
  ref,
) {
  const internalScrollRef = useRef<HTMLDivElement | null>(null) as React.MutableRefObject<
    HTMLDivElement | null
  >
  const firstColumnId = columns[0]?.id
  const rowIndices = virtualRows?.map((entry) => entry.index) ?? rows.map((_, index) => index)
  const [internalEditingCellKey, setInternalEditingCellKey] = useState<string | null>(null)
  const editingCellKey = onEditingCellKeyChange ? editingCellKeyProp : internalEditingCellKey
  const setEditingCellKey = useCallback(
    (key: string | null) => {
      if (onEditingCellKeyChange) onEditingCellKeyChange(key)
      else setInternalEditingCellKey(key)
    },
    [onEditingCellKeyChange],
  )

  const totalContentWidth = DOC_COL_W_PX + columns.length * DATA_COL_W_PX + 32
  const skeletonContentWidth = DOC_COL_W_PX + SKELETON_COLS * DATA_COL_W_PX + 32

  useImperativeHandle(ref, () => ({
    scrollToCell(columnId: string, fileId: string, columnIds: string[], rowFileIds: string[]) {
      const container = internalScrollRef.current
      if (!container) return

      const rowIdx = rowFileIds.indexOf(fileId)
      const colIdx = columnIds.indexOf(columnId)

      const allRows = container.querySelectorAll<HTMLElement>(
        ':scope > div.relative > div.flex[data-index]',
      )
      const targetRow = allRows[rowIdx]
      if (targetRow) {
        container.scrollTo({
          top: Math.max(0, targetRow.offsetTop - 40),
          behavior: 'smooth',
        })
      }

      if (colIdx >= 0) {
        const targetScrollLeft =
          STICKY_LEFT_PX +
          colIdx * DATA_COL_W_PX -
          container.clientWidth / 2 +
          DATA_COL_W_PX / 2
        container.scrollLeft = Math.max(0, targetScrollLeft)
      }
    },
  }))

  const allSelected = rows.length > 0 && rows.every((row) => selectedDocIds.includes(row.fileId))
  const someSelected = !allSelected && rows.some((row) => selectedDocIds.includes(row.fileId))

  function toggleAll() {
    if (!onSelectionChange) return
    onSelectionChange(allSelected ? [] : rows.map((row) => row.fileId))
  }

  function toggleDoc(fileId: string) {
    if (!onSelectionChange) return
    onSelectionChange(
      selectedDocIds.includes(fileId)
        ? selectedDocIds.filter((id) => id !== fileId)
        : [...selectedDocIds, fileId],
    )
  }

  function handleScrollRef(node: HTMLDivElement | null) {
    internalScrollRef.current = node
    scrollRef?.(node)
  }

  if (loading) {
    return (
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className={`flex h-8 ${STICKY_CELL_BG}`} style={{ minWidth: skeletonContentWidth }}>
          <div
            className={`${DOC_COL_W} flex items-center gap-4 border-b border-r border-gray-200 py-2 pl-4 pr-2 text-xs font-medium text-gray-500`}
          >
            <SkeletonDot />
            <span>Документ</span>
          </div>
          {Array.from({ length: SKELETON_COLS }).map((_, i) => (
            <div key={i} className={`${COL_W} flex items-center border-b border-r border-gray-200 p-2`}>
              <SkeletonLine className="h-4 w-28" />
            </div>
          ))}
          <div className="flex-1 border-b border-gray-200 min-w-8" />
        </div>
        {Array.from({ length: SKELETON_ROWS }).map((_, row) => (
          <div
            key={row}
            className={`flex h-10 ${STICKY_CELL_BG}`}
            style={{ minWidth: skeletonContentWidth }}
          >
            <div className={`${DOC_COL_W} flex items-center gap-4 border-b border-r border-gray-200 py-2 pl-4 pr-2`}>
              <SkeletonDot />
              <SkeletonLine className="h-4 w-32" />
            </div>
            {Array.from({ length: SKELETON_COLS }).map((_, col) => (
              <div key={col} className={`${COL_W} flex items-center border-b border-r border-gray-200 p-2`}>
                <SkeletonLine className="h-4" />
              </div>
            ))}
            <div className="flex-1 border-b border-gray-200 min-w-8" />
          </div>
        ))}
      </div>
    )
  }

  if (columns.length === 0 && rows.length === 0 && uploadingFilenames.length === 0) {
    return (
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex items-center border-b border-gray-200">
          <div
            className={`${DOC_COL_W} border-r border-gray-200 py-2 pl-4 pr-2 text-xs font-medium text-gray-500 select-none`}
          >
            Document
          </div>
          <div className="flex-1" />
        </div>
        <div className="relative flex min-h-0 flex-1">
          {dragOverFiles && (
            <div className="absolute inset-0 z-[90] border-2 border-blue-400 bg-blue-50/40 pointer-events-none" />
          )}
          <div className="flex flex-1 flex-col items-start justify-center w-full max-w-xs mx-auto px-4">
            <Table2 className="h-8 w-8 text-gray-300 mb-4" aria-hidden />
            <p className="text-2xl font-medium font-serif text-gray-900">Tabular Review</p>
            <p className="mt-1 text-xs text-gray-400 text-left">
              Добавьте колонки и документы, чтобы начать.
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              {onAddColumn && (
                <button
                  type="button"
                  onClick={onAddColumn}
                  className="inline-flex items-center gap-1 rounded-full bg-gray-900 px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-gray-700 shadow-md"
                >
                  + Добавить колонки
                </button>
              )}
              {onAddDocuments && (
                <button
                  type="button"
                  onClick={onAddDocuments}
                  className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors shadow-sm"
                >
                  <Upload className="h-3.5 w-3.5" aria-hidden />
                  Добавить документы
                </button>
              )}
              {onOpenTemplates && (
                <button
                  type="button"
                  onClick={onOpenTemplates}
                  className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors shadow-sm"
                >
                  <LayoutTemplate className="h-3.5 w-3.5" aria-hidden />
                  Шаблоны
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div ref={handleScrollRef} className="flex flex-1 flex-col overflow-auto">
      <div
        className={`sticky top-0 ${TABLE_HEADER_ROW_Z} flex min-h-8 ${STICKY_CELL_BG}`}
        style={{ minWidth: totalContentWidth }}
      >
        <div
          className={`sticky top-0 left-0 ${TABLE_HEADER_CORNER_Z} ${DOC_COL_W} ${STICKY_CELL_BG} border-b border-r border-gray-200 flex items-center gap-4 py-2 pl-4 pr-2 text-left text-xs font-medium text-gray-500 select-none`}
        >
          {onSelectionChange ? (
            <input
              type="checkbox"
              checked={allSelected}
              ref={(el) => {
                if (el) el.indeterminate = someSelected
              }}
              onChange={toggleAll}
              className={TABLE_CHECKBOX_CLASS}
              aria-label="Выбрать все документы"
            />
          ) : (
            <SkeletonDot className="opacity-0 pointer-events-none" aria-hidden />
          )}
          <span>Документ</span>
        </div>

        {columns.map((column) => (
          <div
            key={column.id}
            className={`sticky top-0 ${TABLE_HEADER_ROW_Z} ${COL_W} ${STICKY_CELL_BG} border-b border-r border-gray-200 p-2 text-left text-xs font-medium text-gray-500 select-none`}
          >
            <div className="flex items-center justify-between gap-3 min-w-0">
              <span className="truncate">{column.label}</span>
              {column.menu}
            </div>
          </div>
        ))}

        <div className={`sticky top-0 ${TABLE_HEADER_ROW_Z} flex-1 border-b border-gray-200 flex items-center justify-start p-2 min-w-8 ${STICKY_CELL_BG}`}>
          {onAddColumn && (
            <button
              type="button"
              ref={addColumnButtonRef}
              onClick={onAddColumn}
              disabled={addColumnDisabled}
              className="flex items-center justify-center text-gray-400 hover:text-gray-700 transition-colors disabled:text-gray-200"
              aria-label="Добавить колонку"
            >
              <Plus className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        {dragOverFiles && (
          <div className="absolute inset-0 z-[90] border-2 border-blue-400 bg-blue-50/40 pointer-events-none" />
        )}

        {virtualTopSpacer > 0 && <div style={{ height: virtualTopSpacer }} aria-hidden />}

        {uploadingFilenames.map((filename) => (
          <div key={`uploading-${filename}`} className="flex h-10" style={{ minWidth: totalContentWidth }}>
            <div
              className={`sticky left-0 ${TABLE_BODY_STICKY_DOC_Z} ${DOC_COL_W} ${STICKY_CELL_BG} border-b border-r border-gray-200 py-2 pl-4 pr-2 text-xs text-gray-400 flex items-center gap-4`}
            >
              <input
                type="checkbox"
                disabled
                className="h-2.5 w-2.5 shrink-0 rounded border-gray-200 cursor-default accent-black disabled:opacity-100"
              />
              <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
              <span className="line-clamp-1">
                {filename}
              </span>
            </div>
            {columns.map((column) => (
              <div key={column.id} className={`${COL_W} border-b border-r border-gray-200 p-2`}>
                <SkeletonLine className="h-4 w-20" />
              </div>
            ))}
            <div className="flex-1 border-b border-gray-200 min-h-8 min-w-8" />
          </div>
        ))}

        {rowIndices.map((rowIndex) => {
          const row = rows[rowIndex]
          if (!row) return null

          const isSelected = selectedDocIds.includes(row.fileId)
          const rowBg = isSelected ? 'bg-gray-100' : 'bg-white'

          return (
            <div
              key={row.fileId}
              data-index={rowIndex}
              ref={rowRef?.(rowIndex)}
              className={`flex items-stretch ${rowBg}`}
              style={{ minWidth: totalContentWidth }}
            >
              <div
                className={`sticky left-0 ${TABLE_BODY_STICKY_DOC_Z} ${DOC_COL_W} border-b border-r border-gray-200 py-2 pl-4 pr-2 text-xs text-gray-800 flex items-start gap-4 cursor-pointer self-stretch ${rowBg}`}
                onClick={() => {
                  if (firstColumnId) onDocumentClick?.(row.fileId, firstColumnId)
                }}
              >
                {onSelectionChange ? (
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleDoc(row.fileId)}
                    onClick={(event) => event.stopPropagation()}
                    className={TABLE_CHECKBOX_CLASS}
                    aria-label={`Выбрать ${row.fileName}`}
                  />
                ) : (
                  <SkeletonDot className="opacity-0 pointer-events-none" aria-hidden />
                )}
                <span className="min-w-0 flex-1 break-words">
                  {row.fileName}
                </span>
              </div>

              {columns.map((column) => {
                const cell = row.cells[column.id]
                const meta = columnMeta[column.id]
                const isHighlighted =
                  highlightedCell?.columnId === column.id &&
                  highlightedCell?.fileId === row.fileId

                return (
                  <div
                    key={column.id}
                    className={`${COL_W} border-b border-r border-gray-200 transition-colors flex flex-col self-stretch ${
                      isHighlighted ? 'bg-blue-200' : ''
                    } ${
                      editingCellKey === `${row.fileId}:${column.id}`
                        ? 'ws-mike-cell-wrapper--editing'
                        : ''
                    }`}
                  >
                    {cell && meta && (
                      <MikeTabularCell
                        cell={cell}
                        columnMeta={meta}
                        reviewId={reviewId}
                        fileId={row.fileId}
                        columnId={column.id}
                        columnLabel={column.label}
                        isPopoverOpen={
                          openPopoverCell?.fileId === row.fileId &&
                          openPopoverCell?.columnId === column.id
                        }
                        isEditing={editingCellKey === `${row.fileId}:${column.id}`}
                        onPopoverOpen={() =>
                          onPopoverCellChange?.({ fileId: row.fileId, columnId: column.id })
                        }
                        onPopoverClose={() => onPopoverCellChange?.(null)}
                        onViewInDocument={(citationIndex) =>
                          onViewInDocument?.(row.fileId, column.id, citationIndex)
                        }
                        onStartEdit={() => {
                          onPopoverCellChange?.(null)
                          setEditingCellKey(`${row.fileId}:${column.id}`)
                        }}
                        onCancelEdit={() => setEditingCellKey(null)}
                        onSave={async (value) => {
                          await onCellSave?.(row.fileId, column.id, value)
                          setEditingCellKey(null)
                        }}
                      />
                    )}
                  </div>
                )
              })}

              <div className="flex-1 border-b border-gray-200 min-h-8 min-w-8" />
            </div>
          )
        })}

        {virtualBottomSpacer > 0 && <div style={{ height: virtualBottomSpacer }} aria-hidden />}

        {rows.length === 0 && columns.length > 0 && (
          <div className="px-4 py-8 text-center text-sm text-gray-500">{emptyFilteredMessage}</div>
        )}
      </div>
    </div>
  )
})
