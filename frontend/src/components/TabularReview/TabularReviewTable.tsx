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
  TextField,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Stack,
  Menu,
  MenuItem,
  Checkbox,
  Typography,
  IconButton,
  Link,
  Chip,
  Pagination,
  Select,
  FormControl,
  InputLabel,
} from '@mui/material'
import {
  SwapVert as ArrowUpDownIcon,
  ExpandMore as ExpandMoreIcon,
  Description as FileTextIcon,
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
  PlayArrow as PlayArrowIcon,
  Close as CloseIcon,
  OpenInNew as OpenInNewIcon,
} from '@mui/icons-material'
import { TabularRow, TabularColumn, TabularCell, CellDetails } from "@/services/tabularReviewApi"
import { tabularReviewApi } from "@/services/tabularReviewApi"
import { CellExpansionModal } from "./CellExpansionModal"
import { TagCell } from "./TagCell"

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
  onCellClick?: (fileId: string, cellData: {
    verbatimExtract?: string | null
    sourcePage?: number | null
    sourceSection?: string | null
    columnType?: string
    highlightMode?: 'verbatim' | 'page' | 'none'
    sourceReferences?: Array<{ page?: number | null; section?: string | null; text: string }>
  }) => void
  onRemoveDocument?: (fileId: string) => void
  onRunColumn?: (columnId: string) => void
}

export const TabularReviewTable = React.memo(({ reviewId, tableData, onCellClick, onRemoveDocument, onRunColumn }: TabularReviewTableProps) => {
  const [sorting, setSorting] = React.useState<SortingState>([])
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([])
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({})
  const [columnSizing, setColumnSizing] = React.useState<ColumnSizingState>({})
  const [columnPinning, setColumnPinning] = React.useState<ColumnPinningState>({ left: ['file_name'], right: [] })
  const [globalFilter, setGlobalFilter] = React.useState("")
  const [globalFilterInput, setGlobalFilterInput] = React.useState("")
  const [selectedCell, setSelectedCell] = React.useState<{
    fileId: string
    columnId: string
    cell: TabularCell
    fileName: string
    columnLabel: string
  } | null>(null)
  const [cellDetails, setCellDetails] = React.useState<CellDetails | null>(null)
  const [loadingCell, setLoadingCell] = React.useState(false)
  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null)
  const [runningColumns, setRunningColumns] = React.useState<Set<string>>(new Set())
  
  // Кеш для cellDetails
  const cellDetailsCache = React.useRef<Map<string, CellDetails>>(new Map())
  
  // Мемоизация findColumnByLabel
  const columnMap = React.useMemo(() => {
    const map = new Map<string, TabularColumn>()
    tableData.columns.forEach(col => {
      map.set(col.column_label.toLowerCase(), col)
    })
    return map
  }, [tableData.columns])
  
  const findColumnByLabel = React.useCallback((label: string): TabularColumn | undefined => {
    return columnMap.get(label.toLowerCase())
  }, [columnMap])
  
  // Debounced глобальный фильтр
  React.useEffect(() => {
    const timer = setTimeout(() => {
      setGlobalFilter(globalFilterInput)
    }, 300)
    return () => clearTimeout(timer)
  }, [globalFilterInput])

  // Transform data for table
  const tableRows = React.useMemo(() => {
    return tableData.rows.map((row) => {
      const rowData: Record<string, any> = {
        file_id: row.file_id,
        file_name: row.file_name,
        file_type: row.file_type,
        status: row.status,
      }
      
      // Add cells as columns
      tableData.columns.forEach((col) => {
        rowData[col.id] = row.cells[col.id] || {
          cell_value: null,
          status: 'pending',
        }
      })
      
      return rowData
    })
  }, [tableData])

  // Helper function to get cell value from dynamic columns
  const getCellValue = (row: any, columnId: string): string | null => {
    const cell: TabularCell = row.getValue(columnId)
    return cell?.cell_value || null
  }


  // Build columns dynamically
  const columns = React.useMemo<ColumnDef<any>[]>(() => {
    const baseColumns: ColumnDef<any>[] = [
      {
        accessorKey: "file_name",
        header: ({ column }) => {
          return (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Button
              variant="text"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
              endIcon={<ArrowUpDownIcon />}
                sx={{ textTransform: 'none', fontWeight: 600, color: '#1F2937' }}
            >
              Document
            </Button>
              <IconButton
                size="small"
                onClick={(e) => {
                  e.stopPropagation()
                  // Run extraction for all columns (or handle as needed)
                  if (onRunColumn) {
                    onRunColumn('document')
                  }
                }}
                sx={{ 
                  p: 0.5,
                  color: '#6B7280',
                  '&:hover': { color: '#1F2937', bgcolor: 'action.hover' }
                }}
              >
                <PlayArrowIcon fontSize="small" />
              </IconButton>
            </Box>
          )
        },
        cell: ({ row }) => (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ py: 1 }}>
            <FileTextIcon fontSize="small" sx={{ color: '#6B7280' }} />
            <Typography variant="body2" sx={{ color: '#1F2937', flex: 1 }}>
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
      },
      {
        id: "date",
        accessorFn: (row) => {
          const dateCol = findColumnByLabel('Date')
          return dateCol ? getCellValue(row, dateCol.id) : null
        },
        header: ({ column }) => {
          return (
            <Button
              variant="text"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
              endIcon={<ArrowUpDownIcon />}
              sx={{ textTransform: 'none', fontWeight: 600, color: '#1F2937' }}
            >
              Date
            </Button>
          )
        },
        cell: ({ row }) => {
          const dateCol = findColumnByLabel('Date')
          const value = dateCol ? getCellValue(row, dateCol.id) : null
          return (
            <Typography variant="body2" sx={{ color: '#1F2937', py: 1 }}>
              {value || "-"}
            </Typography>
          )
        },
      },
      {
        id: "document_type",
        accessorFn: (row) => {
          const docTypeCol = findColumnByLabel('Document type')
          return docTypeCol ? getCellValue(row, docTypeCol.id) : row.original.file_type || null
        },
        header: ({ column }) => {
          return (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Button
                variant="text"
                onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
                endIcon={<ArrowUpDownIcon />}
                sx={{ textTransform: 'none', fontWeight: 600, color: '#1F2937' }}
              >
                Document type
              </Button>
              <IconButton
                size="small"
                onClick={(e) => {
                  e.stopPropagation()
                  const docTypeCol = findColumnByLabel('Document type')
                  if (docTypeCol && onRunColumn) {
                    onRunColumn(docTypeCol.id)
                  }
                }}
                sx={{ 
                  p: 0.5,
                  color: '#6B7280',
                  '&:hover': { color: '#1F2937', bgcolor: 'action.hover' }
                }}
              >
                <PlayArrowIcon fontSize="small" />
              </IconButton>
            </Box>
          )
        },
        cell: ({ row }) => {
          const docTypeCol = findColumnByLabel('Document type')
          const value = docTypeCol ? getCellValue(row, docTypeCol.id) : row.original.file_type
          const displayValue = value || "-"
          
          return (
            <Stack direction="row" spacing={1} alignItems="center" sx={{ py: 1 }}>
              {displayValue !== "-" && (
                <Link
                  component="button"
                  variant="body2"
                  onClick={(e) => {
                    e.stopPropagation()
                    if (onCellClick) {
                      onCellClick(row.original.file_id, { highlightMode: 'none' })
                    }
                  }}
                  sx={{ 
                    color: '#2563EB',
                    textDecoration: 'none',
                    '&:hover': { textDecoration: 'underline' },
                    cursor: 'pointer'
                  }}
                >
                  {displayValue}
                </Link>
              )}
              {displayValue === "-" && (
                <Typography variant="body2" sx={{ color: '#6B7280' }}>
                  {displayValue}
                </Typography>
              )}
              {displayValue !== "-" && (
                <IconButton
                  size="small"
                  onClick={(e) => {
                    e.stopPropagation()
                    if (onCellClick) {
                      onCellClick(row.original.file_id, { highlightMode: 'none' })
                    }
                  }}
                  sx={{ 
                    p: 0.5,
                    color: '#6B7280',
                    '&:hover': { color: '#2563EB', bgcolor: 'action.hover' }
                  }}
                >
                  <OpenInNewIcon fontSize="small" />
                </IconButton>
              )}
            </Stack>
          )
        },
      },
      {
        id: "summary",
        accessorFn: (row) => {
          const summaryCol = findColumnByLabel('Summary')
          return summaryCol ? getCellValue(row, summaryCol.id) : null
        },
        header: ({ column }) => {
          return (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Button
                variant="text"
                onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
                endIcon={<ArrowUpDownIcon />}
                sx={{ textTransform: 'none', fontWeight: 600, color: '#1F2937' }}
              >
                Summary
              </Button>
              <IconButton
                size="small"
                onClick={(e) => {
                  e.stopPropagation()
                  const summaryCol = findColumnByLabel('Summary')
                  if (summaryCol && onRunColumn) {
                    onRunColumn(summaryCol.id)
                  }
                }}
                sx={{ 
                  p: 0.5,
                  color: '#6B7280',
                  '&:hover': { color: '#1F2937', bgcolor: 'action.hover' }
                }}
              >
                <PlayArrowIcon fontSize="small" />
              </IconButton>
            </Box>
          )
        },
        cell: ({ row }) => {
          const summaryCol = findColumnByLabel('Summary')
          const value = summaryCol ? getCellValue(row, summaryCol.id) : null
          return (
            <Typography 
              variant="body2" 
              sx={{ 
                color: '#1F2937', 
                py: 1,
                maxWidth: 400,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                display: '-webkit-box',
                WebkitLineClamp: 3,
                WebkitBoxOrient: 'vertical',
              }}
            >
              {value || "-"}
            </Typography>
          )
        },
      },
      {
        id: "author",
        accessorFn: (row) => {
          const authorCol = findColumnByLabel('Author')
          return authorCol ? getCellValue(row, authorCol.id) : null
        },
        header: ({ column }) => {
          return (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Button
                variant="text"
                onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
                endIcon={<ArrowUpDownIcon />}
                sx={{ textTransform: 'none', fontWeight: 600, color: '#1F2937' }}
              >
                Author
              </Button>
              <IconButton
                size="small"
                onClick={(e) => {
                  e.stopPropagation()
                  const authorCol = findColumnByLabel('Author')
                  if (authorCol && onRunColumn) {
                    onRunColumn(authorCol.id)
                  }
                }}
                sx={{ 
                  p: 0.5,
                  color: '#6B7280',
                  '&:hover': { color: '#1F2937', bgcolor: 'action.hover' }
                }}
              >
                <PlayArrowIcon fontSize="small" />
              </IconButton>
            </Box>
          )
        },
        cell: ({ row }) => {
          const authorCol = findColumnByLabel('Author')
          const value = authorCol ? getCellValue(row, authorCol.id) : null
          return (
            <Typography variant="body2" sx={{ color: '#1F2937', py: 1 }}>
              {value || "-"}
            </Typography>
          )
        },
      },
      {
        id: "persons_mentioned",
        accessorFn: (row) => {
          const persCol = findColumnByLabel('Persons mentioned') || findColumnByLabel('Pers')
          return persCol ? getCellValue(row, persCol.id) : null
        },
        header: ({ column }) => {
          return (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Button
                variant="text"
                onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
                endIcon={<ArrowUpDownIcon />}
                sx={{ textTransform: 'none', fontWeight: 600, color: '#1F2937' }}
              >
                Persons mentioned
              </Button>
              <IconButton
                size="small"
                onClick={(e) => {
                  e.stopPropagation()
                  const persCol = findColumnByLabel('Persons mentioned') || findColumnByLabel('Pers')
                  if (persCol && onRunColumn) {
                    onRunColumn(persCol.id)
                  }
                }}
                sx={{ 
                  p: 0.5,
                  color: '#6B7280',
                  '&:hover': { color: '#1F2937', bgcolor: 'action.hover' }
                }}
              >
                <PlayArrowIcon fontSize="small" />
              </IconButton>
            </Box>
          )
        },
        cell: ({ row }) => {
          const persCol = findColumnByLabel('Persons mentioned') || findColumnByLabel('Pers')
          const value = persCol ? getCellValue(row, persCol.id) : null
          return (
            <Typography variant="body2" sx={{ color: '#1F2937', py: 1 }}>
              {value || "-"}
            </Typography>
          )
        },
      },
      {
        id: "language",
        accessorFn: (row) => {
          const langCol = findColumnByLabel('Language')
          return langCol ? getCellValue(row, langCol.id) : null
        },
        header: ({ column }) => {
          return (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Button
                variant="text"
                onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
                endIcon={<ArrowUpDownIcon />}
                sx={{ textTransform: 'none', fontWeight: 600, color: '#1F2937' }}
              >
                Language
              </Button>
              <IconButton
                size="small"
                onClick={(e) => {
                  e.stopPropagation()
                  const langCol = findColumnByLabel('Language')
                  if (langCol && onRunColumn) {
                    onRunColumn(langCol.id)
                  }
                }}
                sx={{ 
                  p: 0.5,
                  color: '#6B7280',
                  '&:hover': { color: '#1F2937', bgcolor: 'action.hover' }
                }}
              >
                <PlayArrowIcon fontSize="small" />
              </IconButton>
            </Box>
          )
        },
        cell: ({ row }) => {
          const langCol = findColumnByLabel('Language')
          const value = langCol ? getCellValue(row, langCol.id) : null
          return (
            <Typography variant="body2" sx={{ color: '#1F2937', py: 1 }}>
              {value || "-"}
            </Typography>
          )
        },
      },
    ]

    // Add dynamic columns from tableData.columns (excluding base columns)
    const baseColumnLabels = ['Date', 'Document type', 'Summary', 'Author', 'Persons mentioned', 'Pers', 'Language']
    const dynamicColumns: ColumnDef<any>[] = tableData.columns
      .filter(col => !baseColumnLabels.some(label => col.column_label.toLowerCase() === label.toLowerCase()))
      .map((col) => ({
      accessorKey: col.id,
      header: ({ column }) => {
        return (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Button
              variant="text"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
              endIcon={<ArrowUpDownIcon />}
                sx={{ textTransform: 'none', fontWeight: 600, color: '#1F2937' }}
            >
              {col.column_label}
            </Button>
              <IconButton
                size="small"
                onClick={(e) => {
                  e.stopPropagation()
                  if (onRunColumn) {
                    setRunningColumns(prev => new Set(prev).add(col.id))
                    onRunColumn(col.id)
                    // Reset after a delay (you might want to handle this differently)
                    setTimeout(() => {
                      setRunningColumns(prev => {
                        const next = new Set(prev)
                        next.delete(col.id)
                        return next
                      })
                    }, 2000)
                  }
                }}
                disabled={runningColumns.has(col.id)}
                sx={{ 
                  p: 0.5,
                  color: runningColumns.has(col.id) ? '#9CA3AF' : '#6B7280',
                  '&:hover': { color: '#1F2937', bgcolor: 'action.hover' },
                  '&.Mui-disabled': { color: '#9CA3AF' }
                }}
              >
                <PlayArrowIcon fontSize="small" />
              </IconButton>
          </Box>
        )
      },
      cell: ({ row }) => {
        const cell: TabularCell = row.getValue(col.id)
        const cellValue = cell?.cell_value || "-"
        const cellStatus = cell?.status || "pending"
        const isTagType = col.column_type === "tag" || col.column_type === "multiple_tags"
        
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
            onClick={async () => {
                if (cellValue === "-") return
                
              const cacheKey = `${row.original.file_id}_${col.id}`
              
              // Проверяем кеш
              if (cellDetailsCache.current.has(cacheKey)) {
                const cachedDetails = cellDetailsCache.current.get(cacheKey)!
                setSelectedCell({
                  fileId: row.original.file_id,
                  columnId: col.id,
                  cell: cell || { cell_value: null, status: 'pending' },
                  fileName: row.original.file_name,
                  columnLabel: col.column_label,
                })
                setCellDetails(cachedDetails)
                
                // Определяем highlight mode из кеша
                let highlightMode: 'verbatim' | 'page' | 'none' = 'none'
                if (cachedDetails.verbatim_extract) {
                  highlightMode = 'verbatim'
                } else if (cachedDetails.source_page || cachedDetails.source_section) {
                  highlightMode = 'page'
                }
                
                if (onCellClick) {
                  onCellClick(row.original.file_id, {
                    verbatimExtract: cachedDetails.verbatim_extract,
                    sourcePage: cachedDetails.source_page,
                    sourceSection: cachedDetails.source_section,
                    columnType: cachedDetails.column_type,
                    highlightMode,
                    sourceReferences: cachedDetails.source_references,
                  })
                }
                return
              }
              
              setSelectedCell({
                fileId: row.original.file_id,
                columnId: col.id,
                cell: cell || { cell_value: null, status: 'pending' },
                fileName: row.original.file_name,
                columnLabel: col.column_label,
              })
              
              // Load cell details
              setLoadingCell(true)
              try {
                const details = await tabularReviewApi.getCellDetails(
                  reviewId,
                  row.original.file_id,
                  col.id
                )
                
                // Сохраняем в кеш
                cellDetailsCache.current.set(cacheKey, details)
                setCellDetails(details)
                
                // Determine highlight mode
                let highlightMode: 'verbatim' | 'page' | 'none' = 'none'
                if (details.verbatim_extract) {
                  highlightMode = 'verbatim'
                } else if (details.source_page || details.source_section) {
                  highlightMode = 'page'
                }
                
                // Call onCellClick callback to open document
                if (onCellClick) {
                  onCellClick(row.original.file_id, {
                    verbatimExtract: details.verbatim_extract,
                    sourcePage: details.source_page,
                    sourceSection: details.source_section,
                    columnType: details.column_type,
                    highlightMode,
                    sourceReferences: details.source_references,
                  })
                }
              } catch (error) {
                console.error("Error loading cell details:", error)
                setCellDetails(null)
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
                  whiteSpace: col.column_type === "bulleted_list" ? "pre-line" : "normal",
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

    return [...baseColumns, ...dynamicColumns]
  }, [tableData.columns, reviewId, onCellClick, onRunColumn, onRemoveDocument, runningColumns])

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
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      columnSizing,
      columnPinning,
      globalFilter,
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

  const handleMenuOpen = React.useCallback((event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget)
  }, [])

  const handleMenuClose = React.useCallback(() => {
    setAnchorEl(null)
  }, [])

  return (
    <Box sx={{ width: '100%' }}>
      <Stack direction="row" spacing={2} alignItems="center" sx={{ py: 2 }}>
        <TextField
          placeholder="Поиск по всем полям..."
          value={globalFilterInput}
          onChange={(event: React.ChangeEvent<HTMLInputElement>) =>
            setGlobalFilterInput(event.target.value)
          }
          size="small"
          sx={{ maxWidth: 300 }}
        />
        <Button
          variant="outlined"
          endIcon={<ExpandMoreIcon />}
          onClick={handleMenuOpen}
          sx={{ ml: 'auto' }}
        >
          Колонки
        </Button>
        <Menu
          anchorEl={anchorEl}
          open={Boolean(anchorEl)}
          onClose={handleMenuClose}
        >
          {table
            .getAllColumns()
            .filter((column) => column.getCanHide())
            .map((column) => (
              <MenuItem key={column.id} onClick={() => column.toggleVisibility(!column.getIsVisible())}>
                <Checkbox checked={column.getIsVisible()} />
                <Typography sx={{ textTransform: 'capitalize' }}>
                  {column.id}
                </Typography>
              </MenuItem>
            ))}
        </Menu>
      </Stack>
      <TableContainer 
        component={Paper} 
        variant="outlined"
        ref={tableContainerRef}
        sx={{
          border: '1px solid #E5E7EB',
          borderRadius: '8px',
          overflow: shouldVirtualize ? 'auto' : 'hidden',
          maxHeight: shouldVirtualize ? '600px' : 'none',
        }}
      >
        <Table sx={{ borderCollapse: 'separate' }}>
          <TableHead sx={{ position: shouldVirtualize ? 'sticky' : 'static', top: 0, zIndex: 10 }}>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow 
                key={headerGroup.id}
                sx={{
                  bgcolor: '#F9FAFB',
                  borderBottom: '1px solid #E5E7EB',
                }}
              >
                {headerGroup.headers.map((header) => (
                  <TableCell
                    key={header.id}
                    sx={{
                      borderRight: '1px solid #E5E7EB',
                      bgcolor: '#F9FAFB',
                      py: 1.5,
                      px: 2,
                      width: header.getSize(),
                      position: header.column.getIsPinned() ? 'sticky' : 'relative',
                      left: header.column.getIsPinned() === 'left' 
                        ? `${header.getStart('left')}px` 
                        : undefined,
                      right: header.column.getIsPinned() === 'right' 
                        ? `${header.getStart('right')}px` 
                        : undefined,
                      zIndex: header.column.getIsPinned() ? 15 : 1,
                      '&:last-child': {
                        borderRight: 'none',
                      },
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
                        '&:hover': {
                          bgcolor: '#9CA3AF',
                        },
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
                          bgcolor: virtualRow.index % 2 === 0 ? '#FFFFFF' : '#F9FAFB',
                          borderBottom: '1px solid #E5E7EB',
                          '&:hover': {
                            bgcolor: '#F3F4F6',
                          },
                        }}
                      >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell
                        key={cell.id}
                        sx={{
                          borderRight: '1px solid #E5E7EB',
                          px: 2,
                          width: cell.column.getSize(),
                          position: cell.column.getIsPinned() ? 'sticky' : 'static',
                          left: cell.column.getIsPinned() === 'left' 
                            ? `${cell.column.getStart('left')}px` 
                            : undefined,
                          right: cell.column.getIsPinned() === 'right' 
                            ? `${cell.column.getStart('right')}px` 
                            : undefined,
                          zIndex: cell.column.getIsPinned() ? 10 : 1,
                          bgcolor: cell.column.getIsPinned() 
                            ? (virtualRow.index % 2 === 0 ? '#FFFFFF' : '#F9FAFB')
                            : 'transparent',
                          '&:last-child': {
                            borderRight: 'none',
                          },
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
                table.getRowModel().rows.map((row, rowIndex) => (
                  <TableRow
                    key={row.id}
                    sx={{
                      bgcolor: rowIndex % 2 === 0 ? '#FFFFFF' : '#F9FAFB',
                      borderBottom: '1px solid #E5E7EB',
                      '&:hover': {
                        bgcolor: '#F3F4F6',
                      },
                    }}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell
                        key={cell.id}
                        sx={{
                          borderRight: '1px solid #E5E7EB',
                          px: 2,
                          width: cell.column.getSize(),
                          position: cell.column.getIsPinned() ? 'sticky' : 'static',
                          left: cell.column.getIsPinned() === 'left' 
                            ? `${cell.column.getStart('left')}px` 
                            : undefined,
                          right: cell.column.getIsPinned() === 'right' 
                            ? `${cell.column.getStart('right')}px` 
                            : undefined,
                          zIndex: cell.column.getIsPinned() ? 10 : 1,
                          bgcolor: cell.column.getIsPinned() 
                            ? (rowIndex % 2 === 0 ? '#FFFFFF' : '#F9FAFB')
                            : 'transparent',
                          '&:last-child': {
                            borderRight: 'none',
                          },
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
      <Stack direction="row" spacing={2} alignItems="center" justifyContent="space-between" sx={{ py: 2 }}>
        <Typography variant="body2" color="text.secondary">
          Показано {table.getRowModel().rows.length} из {table.getFilteredRowModel().rows.length} строк
        </Typography>
        <Stack direction="row" spacing={2} alignItems="center">
          <FormControl size="small" sx={{ minWidth: 120 }}>
            <InputLabel>Строк на странице</InputLabel>
            <Select
              value={table.getState().pagination.pageSize}
              label="Строк на странице"
              onChange={(e) => {
                table.setPageSize(Number(e.target.value))
              }}
            >
              {[10, 25, 50, 100].map((pageSize) => (
                <MenuItem key={pageSize} value={pageSize}>
                  {pageSize}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Pagination
            count={table.getPageCount()}
            page={table.getState().pagination.pageIndex + 1}
            onChange={(_, page) => table.setPageIndex(page - 1)}
            color="primary"
            showFirstButton
            showLastButton
          />
        </Stack>
      </Stack>
      
      {/* Cell Expansion Modal */}
      {selectedCell && (
        <CellExpansionModal
          isOpen={!!selectedCell}
          onClose={() => {
            setSelectedCell(null)
            setCellDetails(null)
          }}
          cell={selectedCell.cell}
          cellDetails={cellDetails}
          fileName={selectedCell.fileName}
          columnLabel={selectedCell.columnLabel}
          loading={loadingCell}
        />
      )}
    </Box>
  )
})

TabularReviewTable.displayName = 'TabularReviewTable'
