"use client"

import * as React from "react"
import {
  ColumnDef,
  ColumnFiltersState,
  SortingState,
  VisibilityState,
  ColumnSizingState,
  ColumnPinningState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table"
import { useVirtualizer } from "@tanstack/react-virtual"
import {
  Box,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Stack,
  Typography,
  IconButton,
  Chip,
} from '@mui/material'
import {
  Description as FileTextIcon,
  Close as CloseIcon,
  Add as AddIcon,
  ExpandMore as ExpandMoreIcon,
  UnfoldMore as UnfoldMoreIcon,
  ArrowUpward as ArrowUpwardIcon,
  ArrowDownward as ArrowDownwardIcon,
} from '@mui/icons-material'
import { TabularRow, TabularColumn, TabularCell, CellDetails } from "@/services/tabularReviewApi"
import { tabularReviewApi } from "@/services/tabularReviewApi"
import { TagCell } from "./TagCell"
import { CellHistoryPanel } from "./CellHistoryPanel"
import { AdvancedFiltersPanel, AdvancedFilters } from "./AdvancedFiltersPanel"
import { useKeyboardNavigation } from "@/hooks/useKeyboardNavigation"
import { ColumnHeaderMenu } from "./ColumnHeaderMenu"

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
  onTableDataUpdate?: (updater: (prev: TabularReviewTableProps['tableData']) => TabularReviewTableProps['tableData']) => void
  onCellClick?: (fileId: string, columnId: string, cellData: {
    verbatimExtract?: string | null
    sourcePage?: number | null
    sourceSection?: string | null
    columnType?: string
    highlightMode?: 'verbatim' | 'page' | 'none'
    sourceReferences?: Array<{ page?: number | null; section?: string | null; text: string }>
    // Phase 4: Deep link fields
    docId?: string | null
    charStart?: number | null
    charEnd?: number | null
  }) => void
  onCellEdit?: (fileId: string, columnId: string, cell: TabularCell) => void
  onRemoveDocument?: (fileId: string) => void
  onRunColumn?: (columnId: string) => void
  onColumnEdit?: (columnId: string) => void
  onColumnDelete?: (columnId: string) => void
  onAddColumnClick?: () => void
}

export const TabularReviewTable = React.memo(({ reviewId, tableData, onTableDataUpdate: _onTableDataUpdate, onCellClick, onCellEdit, onRemoveDocument, onRunColumn, onColumnEdit, onColumnDelete, onAddColumnClick }: TabularReviewTableProps) => {
  const [sorting, setSorting] = React.useState<SortingState>([])
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([])
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({})
  const [columnSizing, setColumnSizing] = React.useState<ColumnSizingState>({})
  const [columnPinning, setColumnPinning] = React.useState<ColumnPinningState>({ left: ['row_index', 'file_name'], right: [] })
  const [globalFilter, setGlobalFilter] = React.useState("")
  const [_loadingCell, setLoadingCell] = React.useState(false)
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
    logicOperator: "AND",
  })
  const [filtersPanelOpen, setFiltersPanelOpen] = React.useState(false)
  
  // Кеш для cellDetails
  const cellDetailsCache = React.useRef<Map<string, CellDetails>>(new Map())
  
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
      Object.keys(filters.columnTextFilters).length > 0

    if (!hasActiveFilters) return rows

    return rows.filter((row) => {
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
  }, [tableData, advancedFilters, applyAdvancedFilters])

  // Build columns dynamically
  const columns = React.useMemo<ColumnDef<any>[]>(() => {
    // Row number column (first)
    const rowIndexColumn: ColumnDef<any> = {
      id: "row_index",
      size: 48,
      minSize: 40,
      maxSize: 56,
      enableResizing: false,
      enableSorting: false,
      enableHiding: false,
      header: () => null,
      cell: ({ row }) => (
        <Typography component="span" sx={{ fontSize: '0.875rem', color: '#6B7280' }}>
          {row.index + 1}
        </Typography>
      ),
    }

    // File name column
    const fileColumn: ColumnDef<any> = {
      id: "file_name",
      accessorKey: "file_name",
      size: 250,
      minSize: 150,
      maxSize: 500,
      enableSorting: true,
      meta: { columnLabel: "Name" },
      header: ({ column }) => {
        const sortDir = column.getIsSorted()
        return (
          <Box
            sx={{ display: 'flex', alignItems: 'center', gap: 0.5, cursor: column.getCanSort() ? 'pointer' : 'default' }}
            onClick={column.getToggleSortingHandler()}
          >
            <Typography sx={{ fontWeight: 600, fontSize: '0.875rem', color: '#1F2937' }}>
              Name
            </Typography>
            {sortDir === 'asc' && <ArrowUpwardIcon sx={{ fontSize: 16, color: '#6B7280' }} />}
            {sortDir === 'desc' && <ArrowDownwardIcon sx={{ fontSize: 16, color: '#6B7280' }} />}
            {sortDir === false && <UnfoldMoreIcon sx={{ fontSize: 16, color: '#9CA3AF' }} />}
          </Box>
        )
      },
      cell: ({ row }) => (
        <Stack 
          direction="row" 
          spacing={1} 
          alignItems="center" 
          sx={{ 
            cursor: 'pointer',
            '&:hover': { bgcolor: 'transparent' },
          }}
          onClick={async () => {
            if (onCellClick) {
              const fileId = row.original.file_id
              const columnId = tableData.columns.length > 0 ? tableData.columns[0].id : ""
              onCellClick(fileId, columnId, { highlightMode: 'none' })
            }
          }}
        >
          <FileTextIcon fontSize="small" sx={{ color: '#6B7280', flexShrink: 0 }} />
          <Typography
            variant="body2"
            sx={{
              fontSize: '0.875rem',
              color: '#374151',
              flex: 1,
              minWidth: 0,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {row.getValue("file_name")}
          </Typography>
          {onRemoveDocument && (
              <IconButton
                size="small"
                onClick={(e) => {
                  e.stopPropagation()
                onRemoveDocument(row.original.file_id)
                }}
                sx={{ 
                  p: 0.5,
                  color: '#6B7280',
                '&:hover': { color: '#DC2626', bgcolor: 'error.light' }
                }}
              >
              <CloseIcon fontSize="small" />
              </IconButton>
          )}
        </Stack>
      ),
    }

    // All columns from tableData.columns (all dynamic, no filtering)
    const dynamicColumns: ColumnDef<any>[] = tableData.columns.map((col) => ({
      id: col.id, // Explicitly set id to column.id
      accessorKey: col.id,
      size: 200, // Default column width
      minSize: 100,
      maxSize: 800,
      meta: {
        columnLabel: col.column_label, // Store column label in meta for dropdown
      },
      // Custom sorting function for date columns and cells with cell_value
      sortingFn: (rowA, rowB, columnId) => {
        const cellA: TabularCell | undefined = rowA.getValue(columnId)
        const cellB: TabularCell | undefined = rowB.getValue(columnId)
        
        const valueA = cellA?.cell_value || ""
        const valueB = cellB?.cell_value || ""
        
        // Try to parse as dates if column type is date or column label contains date keywords
        const isDateColumn = col.column_type === 'date' || 
          col.column_label.toLowerCase().includes('дат') ||
          col.column_label.toLowerCase().includes('date') ||
          col.column_label.toLowerCase().includes('срок')
        
        if (isDateColumn) {
          // Try multiple date formats
          const parseDate = (str: string): number => {
            if (!str || str === '-' || str === 'N/A') return 0
            
            // Try DD.MM.YYYY format
            const dotMatch = str.match(/(\d{1,2})\.(\d{1,2})\.(\d{4})/)
            if (dotMatch) {
              return new Date(parseInt(dotMatch[3]), parseInt(dotMatch[2]) - 1, parseInt(dotMatch[1])).getTime()
            }
            
            // Try YYYY-MM-DD format
            const isoMatch = str.match(/(\d{4})-(\d{2})-(\d{2})/)
            if (isoMatch) {
              return new Date(parseInt(isoMatch[1]), parseInt(isoMatch[2]) - 1, parseInt(isoMatch[3])).getTime()
            }
            
            // Try to extract any date-like pattern
            const anyDateMatch = str.match(/(\d{1,2})[\.\/\-](\d{1,2})[\.\/\-](\d{2,4})/)
            if (anyDateMatch) {
              const year = anyDateMatch[3].length === 2 ? 2000 + parseInt(anyDateMatch[3]) : parseInt(anyDateMatch[3])
              return new Date(year, parseInt(anyDateMatch[2]) - 1, parseInt(anyDateMatch[1])).getTime()
            }
            
            // Fallback to Date.parse
            const parsed = Date.parse(str)
            return isNaN(parsed) ? 0 : parsed
          }
          
          const dateA = parseDate(valueA)
          const dateB = parseDate(valueB)
          
          if (dateA !== 0 || dateB !== 0) {
            return dateA - dateB
          }
        }
        
        // Default string comparison
        return valueA.localeCompare(valueB, 'ru')
      },
      header: ({ column }) => {
        const isPinned = column.getIsPinned() === 'left'
        const sortDirection = column.getIsSorted() === false ? null : (column.getIsSorted() === "asc" ? "asc" : "desc")
        
        return (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
            <Box
              component="span"
              onClick={(e) => {
                e.stopPropagation()
                onColumnEdit?.(col.id)
              }}
              sx={{
                flex: 1,
                cursor: onColumnEdit ? 'pointer' : 'default',
                '&:hover': onColumnEdit ? { opacity: 0.8 } : {},
              }}
            >
              <Typography sx={{ fontWeight: 600, color: '#1F2937' }}>
                {col.column_label}
              </Typography>
            </Box>
            <ColumnHeaderMenu
              columnId={col.id}
              columnLabel={col.column_label}
              isPinned={isPinned}
              sortDirection={sortDirection}
              onEdit={() => onColumnEdit?.(col.id)}
              onPin={() => column.pin('left')}
              onUnpin={() => column.pin(false)}
              onDelete={() => onColumnDelete?.(col.id)}
              onSortAsc={() => column.toggleSorting(false)}
              onSortDesc={() => column.toggleSorting(true)}
            />
          </Box>
        )
      },
      cell: ({ row }) => {
        const cell: TabularCell = row.getValue(col.id)
        let cellValue = cell?.cell_value || "-"
        
        // Parse JSON if cell_value is a JSON string
        if (cellValue !== "-" && typeof cellValue === "string" && cellValue.trim().startsWith("{")) {
          try {
            const parsed = JSON.parse(cellValue)
            if (parsed && typeof parsed === "object" && "cell_value" in parsed) {
              cellValue = parsed.cell_value || cellValue
            }
          } catch (e) {
            // Not valid JSON, keep original value
          }
        }
        
        const cellStatus = cell?.status || "pending"
        const isTagType = col.column_type === "tag"
        
        return (
          <Box
            sx={{
                cursor: cellValue !== "-" ? 'pointer' : 'default',
                py: 1,
              px: 1,
                minHeight: 40,
              display: 'flex',
              alignItems: 'center',
              transition: (theme) => theme.transitions.create(['background-color', 'transform'], {
                duration: theme.transitions.duration.shorter,
              }),
                '&:hover': cellValue !== "-" ? {
                bgcolor: 'action.hover',
                transform: 'translateX(2px)',
                } : {},
              position: 'relative',
            }}
            onDoubleClick={(e) => {
              e.stopPropagation()
              // Start editing cell
              if (onCellEdit) {
                onCellEdit(row.original.file_id, col.id, cell)
              }
            }}
            onClick={async (e) => {
                if (cellValue === "-") return
                // Don't open document if double-clicking (editing)
                if (e.detail === 2) return
                
              const cacheKey = `${row.original.file_id}_${col.id}`
              
              // Проверяем кеш
              if (cellDetailsCache.current.has(cacheKey)) {
                const cachedDetails = cellDetailsCache.current.get(cacheKey)!
                
                // Определяем highlight mode из кеша
                let highlightMode: 'verbatim' | 'page' | 'none' = 'none'
                if (cachedDetails.verbatim_extract) {
                  highlightMode = 'verbatim'
                } else if (cachedDetails.source_page || cachedDetails.source_section) {
                  highlightMode = 'page'
                }
                
                // Call onCellClick callback to open document immediately (no modal)
                if (onCellClick) {
                  onCellClick(row.original.file_id, col.id, {
                    verbatimExtract: cachedDetails.verbatim_extract,
                    sourcePage: cachedDetails.source_page,
                    sourceSection: cachedDetails.source_section,
                    columnType: cachedDetails.column_type,
                    highlightMode,
                    sourceReferences: cachedDetails.source_references,
                    // Phase 4: Deep link fields
                    docId: cachedDetails.primary_source_doc_id || row.original.file_id,
                    charStart: cachedDetails.primary_source_char_start || undefined,
                    charEnd: cachedDetails.primary_source_char_end || undefined,
                  })
                }
                return
              }
              
              // Load cell details and open document immediately
              setLoadingCell(true)
              try {
                const details = await tabularReviewApi.getCellDetails(
                  reviewId,
                  row.original.file_id,
                  col.id
                )
                
                // Сохраняем в кеш
                cellDetailsCache.current.set(cacheKey, details)
                
                // Determine highlight mode
                let highlightMode: 'verbatim' | 'page' | 'none' = 'none'
                if (details.verbatim_extract) {
                  highlightMode = 'verbatim'
                } else if (details.source_page || details.source_section) {
                  highlightMode = 'page'
                }
                
                // Call onCellClick callback to open document immediately (no modal)
                if (onCellClick) {
                  onCellClick(row.original.file_id, col.id, {
                    verbatimExtract: details.verbatim_extract,
                    sourcePage: details.source_page,
                    sourceSection: details.source_section,
                    columnType: details.column_type,
                    highlightMode,
                    sourceReferences: details.source_references,
                    // Phase 4: Deep link fields
                    docId: details.primary_source_doc_id || row.original.file_id,
                    charStart: details.primary_source_char_start || undefined,
                    charEnd: details.primary_source_char_end || undefined,
                  })
                }
              } catch (error) {
                console.error("Error loading cell details:", error)
              } finally {
                setLoadingCell(false)
              }
            }}
          >
            {/* Status indicator */}
            {cellStatus === "processing" && (
              <Box
                sx={{
                  position: 'absolute',
                  left: 4,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  width: 4,
                  height: 4,
                  borderRadius: '50%',
                  bgcolor: 'warning.main',
                  animation: 'pulse 1.5s ease-in-out infinite',
                  '@keyframes pulse': {
                    '0%, 100%': { opacity: 1 },
                    '50%': { opacity: 0.5 },
                  },
                }}
              />
            )}
            
            {/* Cell content */}
            {isTagType ? (
              <TagCell value={cellValue} column={col} />
            ) : (
                <Typography
                  variant="body2"
                  sx={{
                    flex: 1,
                    fontStyle: cellValue === "-" ? 'italic' : 'normal',
                  color: cellValue === "-" ? '#6B7280' : '#1F2937',
                  whiteSpace: "normal",
                  }}
                >
                  {cellValue === "-" ? "—" : cellValue}
                </Typography>
            )}
            
            {/* Status badge */}
            {cellStatus === "reviewed" && (
              <Chip
                label="✓"
                size="small"
                sx={{
                  ml: 1,
                  height: 18,
                  width: 18,
                  minWidth: 18,
                  bgcolor: 'success.main',
                  color: 'white',
                  fontSize: '0.7rem',
                }}
              />
            )}
          </Box>
        )
      },
    }))

    // "+ Add column" column (last, header only)
    const addColumnColumn: ColumnDef<any> = {
      id: "add_column",
      size: 140,
      minSize: 120,
      maxSize: 160,
      enableResizing: false,
      enableSorting: false,
      enableHiding: false,
      header: () =>
        onAddColumnClick ? (
          <Box
            component="button"
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onAddColumnClick()
            }}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.5,
              border: 'none',
              background: 'none',
              cursor: 'pointer',
              fontSize: '0.875rem',
              color: '#6B7280',
              fontWeight: 500,
              '&:hover': { color: '#1F2937' },
            }}
          >
            <AddIcon sx={{ fontSize: 18 }} />
            Add column
          </Box>
        ) : null,
      cell: () => null,
    }

    const baseColumns = [rowIndexColumn, fileColumn, ...dynamicColumns]
    return onAddColumnClick ? [...baseColumns, addColumnColumn] : baseColumns
  }, [tableData.columns, reviewId, onCellClick, onRemoveDocument, onColumnEdit, onColumnDelete, onAddColumnClick])

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
    onColumnSizingChange: setColumnSizing,
    onColumnPinningChange: setColumnPinning,
    onGlobalFilterChange: setGlobalFilter,
    globalFilterFn: "includesString",
    enableColumnResizing: true,
    columnResizeMode: 'onChange',
    enablePinning: true,
    manualPagination: false,
    manualSorting: false,
    manualFiltering: false,
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
      columnSizing,
      columnPinning,
      globalFilter,
    },
  })
  
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
      if (row && onRemoveDocument) {
        onRemoveDocument(row.original.file_id)
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
  
  // Виртуализация для больших таблиц (>100 строк)
  const shouldVirtualize = table.getRowModel().rows.length > 100
  const tableContainerRef = React.useRef<HTMLDivElement>(null)
  
  const virtualizer = useVirtualizer({
    count: table.getRowModel().rows.length,
    getScrollElement: () => tableContainerRef.current,
    estimateSize: () => 50, // Примерная высота строки
    overscan: 10,
  })
  
  const virtualRows = virtualizer.getVirtualItems()
  const totalSize = virtualizer.getTotalSize()


  return (
    <Box sx={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Documents count bar (above table) */}
      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        sx={{
          py: 1,
          px: 0,
          borderBottom: '1px solid #F0F0F0',
          minHeight: 40,
        }}
      >
        <Stack direction="row" alignItems="center" spacing={0.5} sx={{ color: '#6B7280', fontSize: '0.875rem' }}>
          <Typography variant="body2" sx={{ color: '#6B7280', fontSize: '0.875rem' }}>
            {table.getFilteredRowModel().rows.length} documents
          </Typography>
          <ExpandMoreIcon sx={{ fontSize: 20, color: '#9CA3AF' }} />
        </Stack>
      </Stack>
      
      <TableContainer 
        component={Paper} 
        variant="outlined"
        ref={tableContainerRef}
        sx={{
          bgcolor: '#FFFFFF',
          boxShadow: 'none',
          border: '1px solid #E5E7EB',
          borderRadius: '8px',
          overflowX: 'auto',
          overflowY: 'auto',
          maxHeight: shouldVirtualize ? '500px' : '65vh',
          width: '100%',
          flex: 1,
          minWidth: 0,
          '&::-webkit-scrollbar': {
            height: '8px',
            width: '8px',
          },
          '&::-webkit-scrollbar-track': {
            background: '#F9FAFB',
          },
          '&::-webkit-scrollbar-thumb': {
            background: '#D1D5DB',
            borderRadius: '4px',
          },
          '&::-webkit-scrollbar-thumb:hover': {
            background: '#9CA3AF',
          },
        }}
      >
        <Table sx={{ borderCollapse: 'collapse', minWidth: 'max-content', width: '100%' }}>
          <TableHead sx={{ position: 'sticky', top: 0, zIndex: 10, bgcolor: '#FFFFFF' }}>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow 
                key={headerGroup.id}
                sx={{
                  bgcolor: '#F5F5F4',
                  '& th': {
                    borderBottom: '1px solid #E5E7EB',
                    borderRight: '1px solid #EBEBEB',
                    fontWeight: 600,
                    fontSize: '0.875rem',
                    color: '#1F2937',
                    py: '12px',
                    px: '16px',
                  },
                  '& th:last-child': { borderRight: 'none' },
                }}
              >
                {headerGroup.headers.map((header) => (
                  <TableCell
                    key={header.id}
                    sx={{
                      bgcolor: '#F5F5F4',
                      width: header.getSize(),
                      position: header.column.getIsPinned() ? 'sticky' : 'relative',
                      left: header.column.getIsPinned() === 'left' 
                        ? `${header.getStart('left')}px` 
                        : undefined,
                      right: header.column.getIsPinned() === 'right' 
                        ? `${header.getStart('right')}px` 
                        : undefined,
                      zIndex: header.column.getIsPinned() ? 15 : 1,
                    }}
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                    <Box
                      onMouseDown={header.getResizeHandler()}
                      onTouchStart={header.getResizeHandler()}
                      sx={{
                        position: 'absolute',
                        right: 0,
                        top: 0,
                        bottom: 0,
                        width: '4px',
                        cursor: 'col-resize',
                        userSelect: 'none',
                        touchAction: 'none',
                        bgcolor: header.column.getIsResizing() ? '#2563EB' : 'transparent',
                        '&:hover': { bgcolor: '#9CA3AF' },
                        zIndex: 2,
                      }}
                    />
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableHead>
          <TableBody>
            {table.getRowModel().rows?.length ? (
              shouldVirtualize ? (
                <>
                  <tr style={{ height: `${virtualRows[0]?.start ?? 0}px` }} />
                  {virtualRows.map((virtualRow) => {
                    const row = table.getRowModel().rows[virtualRow.index]
                    return (
                      <TableRow
                        key={row.id}
                        data-index={virtualRow.index}
                        ref={(node) => {
                          if (node) {
                            virtualizer.measureElement(node)
                          }
                        }}
                        sx={{
                          bgcolor: '#FAFAF9',
                          '&:hover': { bgcolor: '#F5F5F4' },
                          '& td': {
                            borderBottom: '1px solid #F0F0F0',
                            borderRight: '1px solid #EBEBEB',
                            py: '12px',
                            px: '16px',
                            fontSize: '0.875rem',
                            color: '#1F2937',
                          },
                          '& td:last-child': { borderRight: 'none' },
                        }}
                      >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell
                        key={cell.id}
                        sx={{
                          width: cell.column.getSize(),
                          position: cell.column.getIsPinned() ? 'sticky' : 'static',
                          left: cell.column.getIsPinned() === 'left' 
                            ? `${cell.column.getStart('left')}px` 
                            : undefined,
                          right: cell.column.getIsPinned() === 'right' 
                            ? `${cell.column.getStart('right')}px` 
                            : undefined,
                          zIndex: cell.column.getIsPinned() ? 10 : 1,
                          bgcolor: 'transparent',
                        }}
                      >
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext()
                        )}
                      </TableCell>
                    ))}
                      </TableRow>
                    )
                  })}
                  <tr style={{ height: `${totalSize - (virtualRows[virtualRows.length - 1]?.end ?? 0)}px` }} />
                </>
              ) : (
                table.getRowModel().rows.map((row) => (
                  <TableRow
                    key={row.id}
                    sx={{
                      bgcolor: '#FAFAF9',
                      '&:hover': { bgcolor: '#F5F5F4' },
                      '& td': {
                        borderBottom: '1px solid #F0F0F0',
                        borderRight: '1px solid #EBEBEB',
                        py: '12px',
                        px: '16px',
                        fontSize: '0.875rem',
                        color: '#1F2937',
                      },
                      '& td:last-child': { borderRight: 'none' },
                    }}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell
                        key={cell.id}
                        sx={{
                          width: cell.column.getSize(),
                          position: cell.column.getIsPinned() ? 'sticky' : 'static',
                          left: cell.column.getIsPinned() === 'left' 
                            ? `${cell.column.getStart('left')}px` 
                            : undefined,
                          right: cell.column.getIsPinned() === 'right' 
                            ? `${cell.column.getStart('right')}px` 
                            : undefined,
                          zIndex: cell.column.getIsPinned() ? 10 : 1,
                          bgcolor: 'transparent',
                        }}
                      >
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext()
                        )}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              )
            ) : (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  align="center"
                  sx={{ height: 96, py: 4 }}
                >
                  <Typography sx={{ color: '#6B7280' }}>
                    Нет результатов.
                  </Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Cell History Panel */}
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

      {/* Advanced Filters Panel */}
      <AdvancedFiltersPanel
        open={filtersPanelOpen}
        onClose={() => setFiltersPanelOpen(false)}
        filters={advancedFilters}
        onFiltersChange={setAdvancedFilters}
        columns={tableData.columns}
      />
    </Box>
  )
})

TabularReviewTable.displayName = 'TabularReviewTable'
