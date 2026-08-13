"use client"

import * as React from "react"
import {
  ColumnDef,
  ColumnFiltersState,
  SortingState,
  VisibilityState,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table"
import { useVirtualizer } from "@tanstack/react-virtual"
import { TabularRow, TabularColumn, TabularCell, CellDetails } from "@/services/tabularReviewApi"
import { tabularReviewApi } from "@/services/tabularReviewApi"
import {
  normalizeCellSourceReferences,
  type TabularCellClickPayload,
} from "@/utils/tabularCellViewerData"
import { CellHistoryPanel } from "./CellHistoryPanel"
import { AdvancedFiltersPanel, AdvancedFilters } from "./AdvancedFiltersPanel"
import { useKeyboardNavigation } from "@/hooks/useKeyboardNavigation"
import { FilterPopover } from "./FilterPopover"
import { applyColumnValueFilters } from "@/utils/tabularColumnFilters"
import { compareTabularCellValuesForSort } from "@/utils/tabularDateUtils"
import {
  buildMikeColumnMeta,
  buildMikeTableColumns,
  buildMikeRowsFromGrid,
} from './mike/buildMikeTableViewModel'
import { MikeTRTable } from './mike/MikeTRTable'
import { estimateMikeRowHeight } from './mike/estimateMikeRowHeight'
import { buildCellCitationList } from './mike/buildCellCitationList'
import { TabularEditColumnMenu } from './TabularEditColumnMenu'
import "./TabularReviewTable.css"

interface TabularReviewTableProps {
  reviewId: string
  tableData: {
    review: {
      id: string
      name: string
      description?: string
      status: string
    }
    columns: TabularColumn[]
    rows: TabularRow[]
  }
  documentSearch?: string
  onTableDataUpdate?: (updater: (prev: TabularReviewTableProps['tableData']) => TabularReviewTableProps['tableData']) => void
  onCellClick?: (fileId: string, columnId: string, cellData: TabularCellClickPayload) => void
  onCellSave?: (fileId: string, columnId: string, value: string) => Promise<void>
  onUserFlagChange?: (
    fileId: string,
    columnId: string,
    flag: import('@/services/tabularReviewApi').UserFlagColor | null,
  ) => Promise<void>
  onCommentCountsChange?: (
    fileId: string,
    columnId: string,
    counts: { comment_count: number; unresolved_comment_count: number },
  ) => void
  commentEvent?: import('./mike/MikeTabularCell').MikeCellCommentEvent | null
  onRemoveDocument?: (fileId: string) => void
  onRunColumn?: (columnId: string) => void
  onColumnDelete?: (columnId: string) => void
  onOpenEditColumn?: (columnId: string) => void
  onAddColumnClick?: () => void
  onAddDocumentsClick?: () => void
  onOpenTemplatesClick?: () => void
  selectedDocIds?: string[]
  onSelectionChange?: (ids: string[]) => void
  filterPopoverOpen?: boolean
  filterAnchorEl?: HTMLElement | null
  onCloseFilterPopover?: () => void
  /** Множество ID колонок, которые сейчас заполняет ИИ — спиннер в заголовке колонки */
  runningColumnIds?: Set<string>
  /** `${columnId}:${fileId}` — скелетон только в ячейках, которые ещё обрабатываются */
  processingCellKeys?: Set<string>
  readOnly?: boolean
}

export const TabularReviewTable = React.memo(({ reviewId, tableData, documentSearch = '', onTableDataUpdate: _onTableDataUpdate, onCellClick, onCellSave, onUserFlagChange, onCommentCountsChange, commentEvent = null, onRemoveDocument: _onRemoveDocument, onRunColumn, onColumnDelete, onOpenEditColumn, onAddColumnClick, onAddDocumentsClick, onOpenTemplatesClick, selectedDocIds, onSelectionChange, filterPopoverOpen, filterAnchorEl, onCloseFilterPopover, runningColumnIds, processingCellKeys, readOnly = false }: TabularReviewTableProps) => {
  const addColumnButtonRef = React.useRef<HTMLButtonElement>(null)
  const [sorting, setSorting] = React.useState<SortingState>([])
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([])
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({})
  const [globalFilter, setGlobalFilter] = React.useState("")

  const [historyPanelOpen, setHistoryPanelOpen] = React.useState(false)
  const [historyCellInfo, setHistoryCellInfo] = React.useState<{
    fileId: string
    columnId: string
    columnLabel: string
  } | null>(null)
  const [advancedFilters, setAdvancedFilters] = React.useState<AdvancedFilters>({
    cellStatuses: [],
    documentStatuses: [],
    confidenceMin: null,
    confidenceMax: null,
    hasComments: null,
    hasUnresolvedComments: null,
    isLocked: null,
    columnTypes: [],
    createdAfter: null,
    createdBefore: null,
    updatedAfter: null,
    updatedBefore: null,
    columnTextFilters: {},
    columnValueFilters: [],
    logicOperator: "AND",
  })
  const [filtersPanelOpen, setFiltersPanelOpen] = React.useState(false)
  const [openPopoverCell, setOpenPopoverCell] = React.useState<{
    fileId: string
    columnId: string
  } | null>(null)
  const [editingCellKey, setEditingCellKey] = React.useState<string | null>(null)
  
  const cellDetailsCache = React.useRef<Map<string, CellDetails>>(new Map())

  const openCellSidePanel = React.useCallback(
    async (fileId: string, columnId: string, sourceReferenceIndex = 0) => {
      if (!onCellClick) return
      const cacheKey = `${fileId}_${columnId}`
      const row = tableData.rows.find((r) => r.file_id === fileId)
      const rowCell = row?.cells?.[columnId]
      const cellValue = row?.cells?.[columnId]?.cell_value ?? ''
      const column = tableData.columns.find((c) => c.id === columnId)

      let details: CellDetails | null = null
      // Always load cell details on open: API enriches missing bbox from chunk provenance.
      if (cellDetailsCache.current.has(cacheKey)) {
        details = cellDetailsCache.current.get(cacheKey)!
      } else {
        try {
          details = await tabularReviewApi.getCellDetails(reviewId, fileId, columnId)
          cellDetailsCache.current.set(cacheKey, details)
        } catch (error) {
          console.error('Error loading cell details:', error)
        }
      }

      const citationList = buildCellCitationList(cellValue, details ?? rowCell)
      const refsFromCitations = citationList.map(
        (item) =>
          item.sourceRef ?? {
            page: item.page ?? undefined,
            text: item.quote,
          },
      )

      const refs =
        refsFromCitations.length > 0
          ? refsFromCitations
          : normalizeCellSourceReferences(
              details ?? rowCell ?? {
                source_page: undefined,
                source_references: undefined,
                verbatim_extract: undefined,
                source_section: undefined,
              },
              cellValue,
            )

      let highlightMode: 'verbatim' | 'page' | 'none' = 'none'
      const activeRef = refs[sourceReferenceIndex] ?? refs[0]
      if (activeRef?.text || details?.verbatim_extract || rowCell?.verbatim_extract) {
        highlightMode = 'verbatim'
      } else if (
        activeRef?.page ??
        details?.source_page ??
        details?.source_section ??
        rowCell?.source_page ??
        rowCell?.source_section
      ) {
        highlightMode = 'page'
      }

      onCellClick(fileId, columnId, {
        verbatimExtract: activeRef?.text ?? details?.verbatim_extract ?? rowCell?.verbatim_extract,
        sourcePage: activeRef?.page ?? details?.source_page ?? rowCell?.source_page,
        sourceSection: activeRef?.section ?? details?.source_section ?? rowCell?.source_section,
        columnType: details?.column_type ?? column?.column_type ?? 'text',
        highlightMode,
        sourceReferences: refs,
        sourceReferenceIndex,
        hideDetailPanel: true,
        docId: activeRef?.doc_id ?? details?.primary_source_doc_id ?? rowCell?.primary_source_doc_id ?? fileId,
        charStart:
          activeRef?.char_start ??
          (sourceReferenceIndex === 0
            ? details?.primary_source_char_start ?? rowCell?.primary_source_char_start ?? undefined
            : undefined),
        charEnd:
          activeRef?.char_end ??
          (sourceReferenceIndex === 0
            ? details?.primary_source_char_end ?? rowCell?.primary_source_char_end ?? undefined
            : undefined),
      })
    },
    [onCellClick, reviewId, tableData.rows, tableData.columns],
  )

  // Debounced глобальный фильтр (оставлен для внутренней логики фильтрации)

  // Apply advanced filters to rows
  const applyAdvancedFilters = React.useCallback((rows: typeof tableData.rows, filters: AdvancedFilters, columns: TabularColumn[]) => {
    // Check if any filters are active
    const hasActiveFilters = 
      filters.cellStatuses.length > 0 ||
      filters.documentStatuses.length > 0 ||
      filters.confidenceMin !== null ||
      filters.confidenceMax !== null ||
      filters.hasComments !== null ||
      filters.hasUnresolvedComments !== null ||
      filters.isLocked !== null ||
      filters.columnTypes.length > 0 ||
      filters.createdAfter !== null ||
      filters.createdBefore !== null ||
      filters.updatedAfter !== null ||
      filters.updatedBefore !== null ||
      Object.keys(filters.columnTextFilters).length > 0 ||
      (filters.columnValueFilters && filters.columnValueFilters.length > 0)

    if (!hasActiveFilters) return rows

    let filtered = rows
    if (filters.columnValueFilters?.length) {
      filtered = applyColumnValueFilters(filtered, filters.columnValueFilters, columns)
    }

    return filtered.filter((row) => {
      const conditions: boolean[] = []

      // Cell status filter
      if (filters.cellStatuses.length > 0) {
        const hasMatchingStatus = columns.some((col) => {
          const cell = row.cells[col.id]
          return cell && filters.cellStatuses.includes(cell.status)
        })
        conditions.push(hasMatchingStatus)
      }

      // Document status filter
      if (filters.documentStatuses.length > 0) {
        conditions.push(filters.documentStatuses.includes(row.status))
      }

      // Confidence filter
      if (filters.confidenceMin !== null || filters.confidenceMax !== null) {
        const hasMatchingConfidence = columns.some((col) => {
          const cell = row.cells[col.id]
          if (!cell || cell.confidence_score === null || cell.confidence_score === undefined) return false
          const score = cell.confidence_score
          const minMatch = filters.confidenceMin === null || score >= filters.confidenceMin
          const maxMatch = filters.confidenceMax === null || score <= filters.confidenceMax
          return minMatch && maxMatch
        })
        conditions.push(hasMatchingConfidence)
      }

      if (filters.hasComments !== null) {
        const hasAny = columns.some((col) => (row.cells[col.id]?.comment_count ?? 0) > 0)
        conditions.push(filters.hasComments ? hasAny : !hasAny)
      }

      if (filters.hasUnresolvedComments !== null) {
        const hasOpen = columns.some(
          (col) => (row.cells[col.id]?.unresolved_comment_count ?? 0) > 0,
        )
        conditions.push(filters.hasUnresolvedComments ? hasOpen : !hasOpen)
      }

      // Column type filter
      if (filters.columnTypes.length > 0) {
        const hasMatchingColumnType = columns.some((col) => {
          return filters.columnTypes.includes(col.column_type)
        })
        conditions.push(hasMatchingColumnType)
      }

      // Column text filters
      if (Object.keys(filters.columnTextFilters).length > 0) {
        const textMatches = Object.entries(filters.columnTextFilters).some(([columnId, searchText]) => {
          if (!searchText) return false
          const cell = row.cells[columnId]
          if (!cell || !cell.cell_value) return false
          return cell.cell_value.toLowerCase().includes(searchText.toLowerCase())
        })
        conditions.push(textMatches)
      }

      // If no conditions, include row
      if (conditions.length === 0) return true

      // Apply logic operator
      if (filters.logicOperator === "AND") {
        return conditions.every((c) => c)
      } else {
        return conditions.some((c) => c)
      }
    })
  }, [])

  // Transform data for table
  const tableRows = React.useMemo(() => {
    let rows = tableData.rows

    const searchQuery = documentSearch.trim().toLowerCase()
    if (searchQuery) {
      rows = rows.filter((row) => row.file_name.toLowerCase().includes(searchQuery))
    }

    // Apply advanced filters
    rows = applyAdvancedFilters(rows, advancedFilters, tableData.columns)

    const transformedRows = rows.map((row) => {
      const rowData: Record<string, any> = {
        file_id: row.file_id,
        file_name: row.file_name,
        file_type: row.file_type || null,
        status: row.status,
      }
      
      // CRITICAL: Only add cells for columns that exist in tableData.columns
      // DO NOT add any other keys - TanStack Table will auto-create columns from any key in rowData
      tableData.columns.forEach((col) => {
        rowData[col.id] = row.cells[col.id] || {
          cell_value: null,
          status: 'pending',
        }
      })
      
      // DO NOT add any other keys from row.cells - they will cause auto-creation of columns
      // If row.cells contains keys not in tableData.columns, they are orphaned and should be ignored
      
      return rowData
    })
    
    return transformedRows
  }, [tableData, advancedFilters, applyAdvancedFilters, documentSearch])

  const columns = React.useMemo<ColumnDef<Record<string, unknown>>[]>(() => {
    const sortDescFor = (columnId: string) =>
      sorting.find((entry) => entry.id === columnId)?.desc ?? false

    const fileColumn: ColumnDef<Record<string, unknown>> = {
      id: "file_name",
      accessorKey: "file_name",
      enableSorting: true,
      sortingFn: (rowA, rowB, columnId) =>
        compareTabularCellValuesForSort(
          String(rowA.getValue(columnId) ?? ""),
          String(rowB.getValue(columnId) ?? ""),
          "text",
          "file_name",
          sortDescFor(columnId),
        ),
    }

    const dynamicColumns: ColumnDef<Record<string, unknown>>[] = tableData.columns.map((col) => ({
      id: col.id,
      accessorKey: col.id,
      enableSorting: true,
      sortingFn: (rowA, rowB, columnId) => {
        const cellA = rowA.getValue(columnId) as TabularCell | undefined
        const cellB = rowB.getValue(columnId) as TabularCell | undefined
        return compareTabularCellValuesForSort(
          cellA?.cell_value || "",
          cellB?.cell_value || "",
          col.column_type,
          col.column_label,
          sortDescFor(columnId),
        )
      },
    }))

    return [fileColumn, ...dynamicColumns]
  }, [tableData.columns, sorting])

  const table = useReactTable({
    data: tableRows,
    columns,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    onColumnVisibilityChange: setColumnVisibility,
    onGlobalFilterChange: setGlobalFilter,
    globalFilterFn: "includesString",
    defaultColumn: {
      enableHiding: false,
      enableColumnFilter: false,
    },
    initialState: {
      pagination: { pageSize: 10000, pageIndex: 0 },
    },
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      globalFilter,
    },
  })

  const sortedRows = table.getRowModel().rows

  const gridRows = React.useMemo(
    () =>
      sortedRows.map((row) => ({
        fileId: row.original.file_id as string,
        fileName: row.original.file_name as string,
        cells: Object.fromEntries(
          tableData.columns.map((col) => [
            col.id,
            row.original[col.id] as TabularCell | undefined,
          ]),
        ),
      })),
    [sortedRows, tableData.columns],
  )

  const mikeRows = React.useMemo(
    () => buildMikeRowsFromGrid(gridRows, tableData.columns, processingCellKeys),
    [gridRows, tableData.columns, processingCellKeys],
  )

  const mikeColumnMeta = React.useMemo(
    () => buildMikeColumnMeta(tableData.columns),
    [tableData.columns],
  )

  // Keyboard navigation
  useKeyboardNavigation({
    table,
    enabled: !filtersPanelOpen && !historyPanelOpen,
    onCellEdit: (rowId) => {
      const row = table.getRowModel().rows.find((r) => r.id === rowId)
      if (row) {
        // TODO: Implement cell editing
      }
    },
    onCellSelect: () => {
      // Focus cell visually (could add highlight)
    },
    onRowDelete: (rowId) => {
      const row = table.getRowModel().rows.find((r) => r.id === rowId)
      if (row && _onRemoveDocument) {
        _onRemoveDocument(row.original.file_id)
      }
    },
    onSearch: () => {
      // Focus search input
      const searchInput = document.querySelector('input[placeholder*="Поиск"]') as HTMLInputElement
      if (searchInput) {
        searchInput.focus()
      }
    },
    onFilter: () => {
      setFiltersPanelOpen(true)
    },
    onNextPage: () => {
      table.nextPage()
    },
    onPreviousPage: () => {
      table.previousPage()
    },
    onFirstPage: () => {
      table.setPageIndex(0)
    },
    onLastPage: () => {
      table.setPageIndex(table.getPageCount() - 1)
    },
  })
  
  const shouldVirtualize = sortedRows.length > 100
  const scrollContainerRef = React.useRef<HTMLDivElement | null>(null)
  const handleScrollContainerRef = React.useCallback((node: HTMLDivElement | null) => {
    scrollContainerRef.current = node
  }, [])

  const columnIds = React.useMemo(
    () => tableData.columns.map((column) => column.id),
    [tableData.columns],
  )

  const estimateRowHeight = React.useCallback(
    (index: number) => estimateMikeRowHeight(mikeRows[index], columnIds),
    [mikeRows, columnIds],
  )

  const virtualizer = useVirtualizer({
    count: sortedRows.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: estimateRowHeight,
    overscan: 8,
    measureElement:
      typeof window !== 'undefined'
        ? (element) => element.getBoundingClientRect().height
        : undefined,
  })

  React.useEffect(() => {
    if (!shouldVirtualize) return
    virtualizer.measure()
  }, [shouldVirtualize, mikeRows, editingCellKey, virtualizer.measure])

  const virtualRows = virtualizer.getVirtualItems()
  const virtualTopSpacer = virtualRows[0]?.start ?? 0
  const virtualBottomSpacer =
    sortedRows.length > 0
      ? virtualizer.getTotalSize() - (virtualRows[virtualRows.length - 1]?.end ?? 0)
      : 0

  const getColumnApi = React.useCallback(
    (columnId: string) => table.getColumn(columnId),
    [table],
  )

  const mikeColumns = React.useMemo(
    () =>
      buildMikeTableColumns(tableData.columns, (column) => {
        if (!onColumnDelete && !onOpenEditColumn) return null
        const sortDirection = getColumnApi(column.id)?.getIsSorted() ?? false
        const isRunning = runningColumnIds?.has(column.id)
        return (
          <TabularEditColumnMenu
            column={column}
            disabled={isRunning}
            isRunning={isRunning}
            sortDirection={sortDirection}
            onSortAsc={() => getColumnApi(column.id)?.toggleSorting(false)}
            onSortDesc={() => getColumnApi(column.id)?.toggleSorting(true)}
            onClearSort={() => getColumnApi(column.id)?.clearSorting()}
            onRun={
              onRunColumn && column.column_type !== 'manual_input'
                ? () => onRunColumn(column.id)
                : undefined
            }
            onOpenEdit={onOpenEditColumn ? () => onOpenEditColumn(column.id) : undefined}
            onDelete={() => onColumnDelete?.(column.id)}
          />
        )
      }),
    [
      tableData.columns,
      onOpenEditColumn,
      onRunColumn,
      onColumnDelete,
      runningColumnIds,
      getColumnApi,
    ],
  )

  return (
    <div className="ws-tabular-table-inner">
      <MikeTRTable
        reviewId={reviewId}
        columns={mikeColumns}
        rows={mikeRows}
        columnMeta={mikeColumnMeta}
        openPopoverCell={openPopoverCell}
        onPopoverCellChange={setOpenPopoverCell}
        editingCellKey={editingCellKey}
        onEditingCellKeyChange={setEditingCellKey}
        addColumnButtonRef={addColumnButtonRef}
        onAddColumn={readOnly ? undefined : onAddColumnClick}
        onAddDocuments={readOnly ? undefined : onAddDocumentsClick}
        onOpenTemplates={readOnly ? undefined : onOpenTemplatesClick}
        selectedDocIds={selectedDocIds}
        onSelectionChange={onSelectionChange}
        scrollRef={handleScrollContainerRef}
        virtualRows={shouldVirtualize ? virtualRows : undefined}
        virtualTopSpacer={shouldVirtualize ? virtualTopSpacer : 0}
        virtualBottomSpacer={shouldVirtualize ? virtualBottomSpacer : 0}
        onViewInDocument={(fileId, columnId, citationIndex) => {
          void openCellSidePanel(fileId, columnId, citationIndex)
        }}
        onCellSave={readOnly ? undefined : onCellSave}
        onUserFlagChange={readOnly ? undefined : onUserFlagChange}
        onCommentCountsChange={onCommentCountsChange}
        commentEvent={commentEvent}
        readOnly={readOnly}
        onDocumentClick={(fileId, firstColumnId) => {
          onCellClick?.(fileId, firstColumnId, { highlightMode: 'none' })
        }}
        rowMeasureRef={shouldVirtualize ? virtualizer.measureElement : undefined}
      />
      <CellHistoryPanel
        reviewId={reviewId}
        fileId={historyCellInfo?.fileId || ""}
        columnId={historyCellInfo?.columnId || ""}
        columnLabel={historyCellInfo?.columnLabel || ""}
        open={historyPanelOpen}
        onClose={() => {
          setHistoryPanelOpen(false)
          setHistoryCellInfo(null)
        }}
        onRevert={() => {
          // Reload table data after revert
          // This would typically trigger a data refresh
        }}
      />

      {filterPopoverOpen && onCloseFilterPopover && (
        <FilterPopover
          open={true}
          anchorEl={filterAnchorEl}
          onClose={onCloseFilterPopover}
          columns={tableData.columns}
          rows={tableData.rows}
          valueFilters={advancedFilters.columnValueFilters}
          onApply={(newColumnValueFilters) => {
            setAdvancedFilters((prev) => ({ ...prev, columnValueFilters: newColumnValueFilters }))
          }}
        />
      )}

      {/* Advanced Filters Panel */}
      <AdvancedFiltersPanel
        open={filtersPanelOpen}
        onClose={() => setFiltersPanelOpen(false)}
        filters={advancedFilters}
        onFiltersChange={setAdvancedFilters}
        columns={tableData.columns}
      />
    </div>
  )
})

TabularReviewTable.displayName = 'TabularReviewTable'
