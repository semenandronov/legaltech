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
  Tooltip,
  CircularProgress,
  Popover,
  Divider,
} from '@mui/material'
import {
  Description as FileTextIcon,
  Close as CloseIcon,
  Add as AddIcon,
  PlayArrow as PlayArrowIcon,
  UnfoldMore as UnfoldMoreIcon,
  ArrowUpward as ArrowUpwardIcon,
  ArrowDownward as ArrowDownwardIcon,
  ContentCopy as ContentCopyIcon,
} from '@mui/icons-material'
// ---------------------------------------------------------------------------
// Inline column creation form (Harvey-style)
// ---------------------------------------------------------------------------
interface InlineColumnFormProps {
  onContinue: (prompt: string) => void
  onCancel: () => void
}

const InlineColumnForm = React.memo(({ onContinue, onCancel }: InlineColumnFormProps) => {
  const [prompt, setPrompt] = React.useState("")
  return (
    <Box
      sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, width: '100%', py: 0.5 }}
      onClick={(e) => e.stopPropagation()}
    >
      <Box>
        <Typography sx={{ fontWeight: 600, fontSize: '0.9375rem', color: '#1F2937', mb: 0.25 }}>
          Создать колонку
        </Typography>
        <Typography sx={{ fontSize: '0.8125rem', color: '#6B7280', lineHeight: 1.4 }}>
          Задайте вопрос для извлечения данных из документов.
        </Typography>
      </Box>
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="Например: какая дата подписания договора?"
        rows={4}
        style={{
          width: '100%',
          padding: '8px',
          border: '1px solid #E5E7EB',
          borderRadius: '6px',
          fontSize: '0.8125rem',
          color: '#1F2937',
          resize: 'none',
          outline: 'none',
          fontFamily: 'inherit',
          backgroundColor: 'white',
          boxSizing: 'border-box',
        }}
        onFocus={(e) => { e.target.style.borderColor = '#3B82F6'; e.target.style.boxShadow = '0 0 0 2px rgba(59,130,246,0.15)' }}
        onBlur={(e) => { e.target.style.borderColor = '#E5E7EB'; e.target.style.boxShadow = 'none' }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault()
            if (prompt.trim()) onContinue(prompt)
          }
        }}
      />
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1 }}>
        <Box
          component="button"
          type="button"
          onClick={onCancel}
          sx={{
            px: 1.5, py: 0.75, border: '1px solid #E5E7EB', borderRadius: '6px',
            background: 'white', fontSize: '0.8125rem', color: '#6B7280',
            cursor: 'pointer', fontFamily: 'inherit',
            '&:hover': { background: '#F3F4F6' },
          }}
        >
          Отмена
        </Box>
        <Box
          component="button"
          type="button"
          onClick={() => { if (prompt.trim()) onContinue(prompt) }}
          sx={{
            px: 1.5, py: 0.75, border: 'none', borderRadius: '6px',
            background: prompt.trim() ? '#1F2937' : '#E5E7EB',
            fontSize: '0.8125rem', color: prompt.trim() ? 'white' : '#9CA3AF',
            cursor: prompt.trim() ? 'pointer' : 'not-allowed', fontFamily: 'inherit',
          }}
        >
          Далее →
        </Box>
      </Box>
    </Box>
  )
})
InlineColumnForm.displayName = 'InlineColumnForm'

import { TabularRow, TabularColumn, TabularCell, CellDetails } from "@/services/tabularReviewApi"
import { tabularReviewApi } from "@/services/tabularReviewApi"
import { TagCell } from "./TagCell"
import { CellHistoryPanel } from "./CellHistoryPanel"
import { AdvancedFiltersPanel, AdvancedFilters } from "./AdvancedFiltersPanel"
import { useKeyboardNavigation } from "@/hooks/useKeyboardNavigation"
import { ColumnBuilder } from "./ColumnBuilder"
import { FilterPopover } from "./FilterPopover"

// Approximate row height used for virtualization and overlay sizing
const ROW_HEIGHT_ESTIMATE = 50
const ADD_COLUMN_OVERLAY_ROWS = 7
const ADD_COLUMN_OVERLAY_WIDTH = 380

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
  onColumnEdit?: (columnId: string, anchorEl?: HTMLElement) => void
  onColumnDelete?: (columnId: string) => void
  onAddColumnClick?: () => void
  showAddColumnPopover?: boolean
  onCloseAddColumnPopover?: () => void
  onSaveNewColumn?: (column: { column_label: string; column_type: string; prompt: string; column_config?: { options?: Array<{ label: string; color: string }>; allow_custom?: boolean } }) => Promise<void>
  /** Вызывается когда пользователь нажал "Далее →" в inline-форме — открывает BulkColumnBuilder */
  onInlinePromptSubmit?: (prompt: string) => void
  filterPopoverOpen?: boolean
  filterAnchorEl?: HTMLElement | null
  onCloseFilterPopover?: () => void
  /** Множество ID колонок, которые сейчас заполняет ИИ — показывается индикатор и скелетон */
  runningColumnIds?: Set<string>
}

export const TabularReviewTable = React.memo(({ reviewId, tableData, onTableDataUpdate: _onTableDataUpdate, onCellClick, onCellEdit, onRemoveDocument, onRunColumn, onColumnEdit, onColumnDelete, onAddColumnClick, showAddColumnPopover, onCloseAddColumnPopover, onSaveNewColumn, onInlinePromptSubmit, filterPopoverOpen, filterAnchorEl, onCloseFilterPopover, runningColumnIds }: TabularReviewTableProps) => {
  const addColumnButtonRef = React.useRef<HTMLElement | null>(null)
  const [sorting, setSorting] = React.useState<SortingState>([])
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([])
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({})
  const [columnSizing, setColumnSizing] = React.useState<ColumnSizingState>({})
  const [columnPinning, setColumnPinning] = React.useState<ColumnPinningState>({ left: ['row_index', 'file_name'], right: [] })
  const [globalFilter, setGlobalFilter] = React.useState("")
  const [_loadingCell, setLoadingCell] = React.useState(false)

  // Step-2 state for inline column creation (step 1 is inline, step 2 is a modal)
  const [showStep2, setShowStep2] = React.useState(false)
  const [step2Prompt, setStep2Prompt] = React.useState("")

  // Reset inline form when parent closes the popover
  React.useEffect(() => {
    if (!showAddColumnPopover) {
      setShowStep2(false)
      setStep2Prompt("")
    }
  }, [showAddColumnPopover])

  const handleInlineContinue = React.useCallback((prompt: string) => {
    if (onInlinePromptSubmit) {
      // Redirect to BulkColumnBuilder (Harvey-style)
      onCloseAddColumnPopover?.()
      onInlinePromptSubmit(prompt)
    } else {
      // Fallback: single-column step 2 modal
      setStep2Prompt(prompt)
      setShowStep2(true)
    }
  }, [onInlinePromptSubmit, onCloseAddColumnPopover])

  const handleInlineCancel = React.useCallback(() => {
    onCloseAddColumnPopover?.()
  }, [onCloseAddColumnPopover])
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
  
  const cellDetailsCache = React.useRef<Map<string, CellDetails>>(new Map())

  // Popover state for Harvey-style cell detail popup
  const [cellPopoverAnchor, setCellPopoverAnchor] = React.useState<HTMLElement | null>(null)
  const [cellPopoverData, setCellPopoverData] = React.useState<{
    cellValue: string
    reasoning?: string | null
    sourceDocName?: string
    sourcePage?: number | null
    sourceReferences?: Array<{ page?: number | null; section?: string | null; text: string }>
    onViewSource: () => void
  } | null>(null)

  // Debounced глобальный фильтр (оставлен для внутренней логики фильтрации)

  // Apply advanced filters to rows
  const applyAdvancedFilters = React.useCallback((rows: typeof tableData.rows, filters: AdvancedFilters, columns: TabularColumn[]) => {
    // Normalize cell value for comparison (empty -> same key as in FilterPopover)
    const EMPTY_VALUE_KEY = ""
    const normalizeCellValue = (val: string | null | undefined): string =>
      val == null || val === "" ? EMPTY_VALUE_KEY : String(val).trim()

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

    return rows.filter((row) => {
      const conditions: boolean[] = []

      // Column value filters (each condition: cell value in selectedValues; all conditions AND)
      const activeValueFilters = filters.columnValueFilters?.filter((c) => c.selectedValues.length > 0) ?? []
      if (activeValueFilters.length > 0) {
        const valueMatch = activeValueFilters.every((cond) => {
          const cellVal = normalizeCellValue(row.cells[cond.columnId]?.cell_value ?? null)
          return cond.selectedValues.includes(cellVal)
        })
        conditions.push(valueMatch)
      }

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
        <Typography component="span" sx={{ fontSize: '0.75rem', color: '#9CA3AF', userSelect: 'none' }}>
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
            <Typography sx={{ fontWeight: 600, fontSize: '0.75rem', letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--text-secondary, #6B7280)' }}>
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
          spacing={0.75}
          alignItems="center"
          sx={{
            cursor: 'pointer',
            overflow: 'hidden',
            '&:hover .file-name-text': { color: '#2563EB' },
          }}
          onClick={async () => {
            if (onCellClick) {
              const fileId = row.original.file_id
              const columnId = tableData.columns.length > 0 ? tableData.columns[0].id : ""
              onCellClick(fileId, columnId, { highlightMode: 'none' })
            }
          }}
        >
          <FileTextIcon sx={{ fontSize: 15, color: '#9CA3AF', flexShrink: 0 }} />
          <Typography
            className="file-name-text"
            variant="body2"
            sx={{
              fontSize: '0.8125rem',
              color: '#374151',
              flex: 1,
              minWidth: 0,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              transition: 'color 0.15s',
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
      header: () => (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, width: '100%' }}>
          <Box
            component="span"
            onClick={(e) => {
              e.stopPropagation()
              onColumnEdit?.(col.id, e.currentTarget as HTMLElement)
            }}
            sx={{
              flex: 1,
              cursor: onColumnEdit ? 'pointer' : 'default',
              '&:hover': onColumnEdit ? { opacity: 0.8 } : {},
            }}
          >
            <Typography sx={{ fontWeight: 600, fontSize: '0.75rem', letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--text-secondary, #6B7280)' }}>
              {col.column_label}
            </Typography>
          </Box>
          {onRunColumn && col.column_type !== 'manual_input' && (
            <Tooltip title="Запустить ИИ для заполнения колонки">
              <IconButton
                size="small"
                onClick={(e) => {
                  e.stopPropagation()
                  if (runningColumnIds?.has(col.id)) return
                  onRunColumn(col.id)
                }}
                disabled={runningColumnIds?.has(col.id)}
                aria-label="Запустить ИИ для заполнения колонки"
                sx={{ p: 0.25 }}
              >
                {runningColumnIds?.has(col.id) ? (
                  <CircularProgress size={18} color="inherit" />
                ) : (
                  <PlayArrowIcon sx={{ fontSize: 18 }} />
                )}
              </IconButton>
            </Tooltip>
          )}
        </Box>
      ),
      cell: ({ row }) => {
        // Show skeleton while AI is filling this column
        if (runningColumnIds?.has(col.id)) {
          const widths = [55, 70, 45, 80, 60, 50, 75, 40, 65, 85]
          const w = widths[row.index % widths.length]
          return (
            <Box sx={{ px: 1, py: 1 }}>
              <Box sx={{
                height: 13,
                borderRadius: '4px',
                bgcolor: '#E5E7EB',
                width: `${w}%`,
                '@keyframes shimmer': {
                  '0%, 100%': { opacity: 1 },
                  '50%': { opacity: 0.35 },
                },
                animation: 'shimmer 1.4s ease-in-out infinite',
              }} />
            </Box>
          )
        }

        const cell: TabularCell = row.getValue(col.id)
        let cellValue = cell?.cell_value || "-"

        // Parse JSON if cell_value is a JSON string (backend may return structured extraction result)
        if (cellValue !== "-" && typeof cellValue === "string" && cellValue.trim().startsWith("{")) {
          try {
            // Remove trailing commas before closing braces/brackets (LLM may produce non-standard JSON)
            const cleanJson = cellValue.replace(/,\s*([}\]])/g, '$1')
            const parsed = JSON.parse(cleanJson)
            if (parsed && typeof parsed === "object" && "cell_value" in parsed) {
              const inner = parsed.cell_value
              cellValue = (inner !== null && inner !== undefined && inner !== "") ? String(inner) : "-"
            }
          } catch (e) {
            // JSON.parse failed — try regex fallback to extract cell_value
            const match = cellValue.match(/"cell_value"\s*:\s*"([^"]*)"/)
            if (match && match[1] !== undefined) {
              cellValue = match[1] || "-"
            } else {
              // Cannot extract — treat as not found
              cellValue = "-"
            }
          }
        }

        // Normalize empty/placeholder values to "-" (not found)
        if (typeof cellValue === "string") {
          const v = cellValue.trim()
          if (
            !v ||
            v.toUpperCase() === "N/A" ||
            v === "—" || v === "-" || v === "–" ||
            /^[_\s\-.]+$/.test(v) ||       // pure underscores/dashes
            /_{2,}/.test(v)                // contains unfilled template blanks like «___» ____20__г.
          ) {
            cellValue = "-"
          }
        }

        const cellStatus = cell?.status || "pending"
        const isTagType = col.column_type === "tag"

        return (
          <Box
            sx={{
              cursor: cellValue !== "-" ? 'pointer' : 'default',
              py: 0,
              px: 0,
              minHeight: 20,
              display: 'flex',
              alignItems: 'center',
              overflow: 'hidden',
              width: '100%',
              transition: (theme) => theme.transitions.create(['background-color'], {
                duration: theme.transitions.duration.shorter,
              }),
              '&:hover': cellValue !== "-" ? {
                opacity: 0.85,
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
                // Don't trigger on double-click (editing)
                if (e.detail === 2) return

              const anchor = e.currentTarget as HTMLElement
              const cacheKey = `${row.original.file_id}_${col.id}`

              const openPopover = (details: CellDetails) => {
                let highlightMode: 'verbatim' | 'page' | 'none' = 'none'
                if (details.verbatim_extract) {
                  highlightMode = 'verbatim'
                } else if (details.source_page || details.source_section) {
                  highlightMode = 'page'
                }
                const viewSourcePayload = {
                  verbatimExtract: details.verbatim_extract,
                  sourcePage: details.source_page,
                  sourceSection: details.source_section,
                  columnType: details.column_type,
                  highlightMode,
                  sourceReferences: details.source_references,
                  docId: details.primary_source_doc_id || row.original.file_id,
                  charStart: details.primary_source_char_start || undefined,
                  charEnd: details.primary_source_char_end || undefined,
                }
                setCellPopoverAnchor(anchor)
                setCellPopoverData({
                  cellValue,
                  reasoning: details.reasoning,
                  sourceDocName: row.original.file_name,
                  sourcePage: details.source_page,
                  sourceReferences: details.source_references,
                  onViewSource: () => {
                    setCellPopoverAnchor(null)
                    setCellPopoverData(null)
                    if (onCellClick) {
                      onCellClick(row.original.file_id, col.id, viewSourcePayload)
                    }
                  },
                })
              }

              // Use cache if available
              if (cellDetailsCache.current.has(cacheKey)) {
                openPopover(cellDetailsCache.current.get(cacheKey)!)
                return
              }

              // Load from API
              setLoadingCell(true)
              try {
                const details = await tabularReviewApi.getCellDetails(
                  reviewId,
                  row.original.file_id,
                  col.id
                )
                cellDetailsCache.current.set(cacheKey, details)
                openPopover(details)
              } catch (error) {
                console.error("Error loading cell details:", error)
              } finally {
                setLoadingCell(false)
              }
            }}
          >
            {/* Status indicator (per-cell processing) */}
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
                    color: cellValue === "-" ? '#9CA3AF' : '#1F2937',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    minWidth: 0,
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
      size: showAddColumnPopover ? ADD_COLUMN_OVERLAY_WIDTH : 140,
      minSize: showAddColumnPopover ? ADD_COLUMN_OVERLAY_WIDTH : 120,
      maxSize: showAddColumnPopover ? ADD_COLUMN_OVERLAY_WIDTH : 160,
      enableResizing: false,
      enableSorting: false,
      enableHiding: false,
      header: () => onAddColumnClick ? (
        <Box
          component="button"
          type="button"
          ref={(el) => { addColumnButtonRef.current = el as HTMLElement | null }}
          onClick={(e) => {
            e.stopPropagation()
            // Расширяем колонку под ширину модального окна и открываем форму
            setColumnSizing((prev) => ({
              ...prev,
              add_column: ADD_COLUMN_OVERLAY_WIDTH,
            }))
            onAddColumnClick?.()
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
  }, [tableData.columns, reviewId, onCellClick, onRemoveDocument, onColumnEdit, onColumnDelete, onAddColumnClick, onRunColumn, runningColumnIds, handleInlineContinue, handleInlineCancel, showAddColumnPopover])

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
      <TableContainer 
        component={Paper} 
        variant="outlined"
        ref={tableContainerRef}
        sx={{
          bgcolor: 'var(--bg-primary)',
          boxShadow: 'none',
          border: '1px solid var(--border, #E5E7EB)',
          borderRadius: '8px',
          overflowX: 'auto',
          overflowY: 'auto',
          width: '100%',
          flex: 1,
          minHeight: 0,
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
        <Table sx={{ borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed' }} style={{ width: table.getTotalSize() }}>
          <TableHead>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow
                key={headerGroup.id}
                sx={{
                  '& th': {
                    position: 'sticky',
                    top: 0,
                    zIndex: 10,
                    bgcolor: 'var(--bg-secondary, #F9FAFB)',
                    borderTop: 'none',
                    borderBottom: '1px solid var(--border, #D1D5DB)',
                    borderRight: '1px solid var(--border, #E5E7EB)',
                    borderLeft: 'none',
                    fontWeight: 600,
                    fontSize: '0.75rem',
                    letterSpacing: '0.04em',
                    textTransform: 'uppercase',
                    color: 'var(--text-secondary, #6B7280)',
                    py: '7px',
                    px: '14px',
                  },
                }}
              >
                {headerGroup.headers.map((header) => (
                  <TableCell
                    key={header.id}
                    sx={{
                      bgcolor: 'var(--bg-secondary, #F9FAFB)',
                      width: header.getSize(),
                      verticalAlign: 'middle',
                    }}
                    style={{
                      // Use inline style for sticky positioning to override any cascade issues
                      left: header.column.getIsPinned() === 'left' ? `${header.getStart('left')}px` : undefined,
                      right: header.column.getIsPinned() === 'right' ? `${header.getStart('right')}px` : undefined,
                      zIndex: header.column.getIsPinned() ? 20 : 10,
                      boxShadow: header.column.getIsPinned() === 'left' ? '2px 0 6px -2px rgba(0,0,0,0.1)' : undefined,
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
                          bgcolor: 'var(--bg-primary)',
                          '&:hover': { bgcolor: 'var(--bg-hover, rgba(0,0,0,0.02))' },
                          '& td': {
                            borderBottom: '1px solid var(--border, #E5E7EB)',
                            borderRight: '1px solid var(--border, #E5E7EB)',
                            borderLeft: 'none',
                            py: '6px',
                            px: '14px',
                            fontSize: '0.875rem',
                            color: 'var(--text-primary, #1F2937)',
                          },
                        }}
                      >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell
                        key={cell.id}
                        sx={{
                          width: cell.column.getSize(),
                          maxWidth: cell.column.getSize(),
                          overflow: 'hidden',
                          bgcolor: cell.column.getIsPinned() === 'left' ? 'var(--bg-primary)' : 'transparent',
                        }}
                        style={{
                          position: cell.column.getIsPinned() ? 'sticky' : undefined,
                          left: cell.column.getIsPinned() === 'left' ? `${cell.column.getStart('left')}px` : undefined,
                          right: cell.column.getIsPinned() === 'right' ? `${cell.column.getStart('right')}px` : undefined,
                          zIndex: cell.column.getIsPinned() ? 10 : undefined,
                          backgroundColor: cell.column.getIsPinned() === 'left' ? 'var(--bg-primary, #ffffff)' : undefined,
                          boxShadow: cell.column.getIsPinned() === 'left' ? '2px 0 6px -2px rgba(0,0,0,0.1)' : undefined,
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
                      bgcolor: 'var(--bg-primary)',
                      '&:hover': { bgcolor: 'var(--bg-hover, rgba(0,0,0,0.02))' },
                      '& td': {
                        borderBottom: '1px solid var(--border, #E5E7EB)',
                        borderRight: '1px solid var(--border, #E5E7EB)',
                        borderLeft: 'none',
                        py: '6px',
                        px: '14px',
                        fontSize: '0.875rem',
                        color: 'var(--text-primary, #1F2937)',
                      },
                    }}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell
                        key={cell.id}
                        sx={{
                          width: cell.column.getSize(),
                          maxWidth: cell.column.getSize(),
                          overflow: 'hidden',
                          bgcolor: cell.column.getIsPinned() === 'left' ? 'var(--bg-primary)' : 'transparent',
                        }}
                        style={{
                          position: cell.column.getIsPinned() ? 'sticky' : undefined,
                          left: cell.column.getIsPinned() === 'left' ? `${cell.column.getStart('left')}px` : undefined,
                          right: cell.column.getIsPinned() === 'right' ? `${cell.column.getStart('right')}px` : undefined,
                          zIndex: cell.column.getIsPinned() ? 10 : undefined,
                          backgroundColor: cell.column.getIsPinned() === 'left' ? 'var(--bg-primary, #ffffff)' : undefined,
                          boxShadow: cell.column.getIsPinned() === 'left' ? '2px 0 6px -2px rgba(0,0,0,0.1)' : undefined,
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

      {/* Step 2 modal: shown after user enters prompt in the inline form (fallback when onInlinePromptSubmit is not set) */}
      {showStep2 && onSaveNewColumn && (
        <ColumnBuilder
          isOpen={true}
          onClose={() => {
            setShowStep2(false)
            setStep2Prompt("")
            onCloseAddColumnPopover?.()
          }}
          onSave={async (column) => {
            await onSaveNewColumn(column)
            setShowStep2(false)
            setStep2Prompt("")
          }}
          startAtStep={2}
          initialPrompt={step2Prompt}
        />
      )}

      {filterPopoverOpen && filterAnchorEl && onCloseFilterPopover && (
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

      {/* Add column popover — модальное окно строго в рамках колонки, перекрывающее ~7 строк */}
      {onAddColumnClick && (
        <Popover
          open={Boolean(showAddColumnPopover && addColumnButtonRef.current)}
          anchorEl={addColumnButtonRef.current}
          onClose={() => {
            onCloseAddColumnPopover?.()
          }}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
          transformOrigin={{ vertical: 'top', horizontal: 'left' }}
          slotProps={{
            paper: {
              sx: {
                width: ADD_COLUMN_OVERLAY_WIDTH,
                maxWidth: ADD_COLUMN_OVERLAY_WIDTH,
                borderRadius: '10px',
                boxShadow: '0 8px 32px rgba(0,0,0,0.15)',
                p: 2.5,
                height: ROW_HEIGHT_ESTIMATE * ADD_COLUMN_OVERLAY_ROWS,
                display: 'flex',
                flexDirection: 'column',
                overflowY: 'auto',
              },
            },
          }}
        >
          <InlineColumnForm
            onContinue={(prompt) => {
              handleInlineContinue(prompt)
            }}
            onCancel={() => {
              handleInlineCancel()
            }}
          />
        </Popover>
      )}

      {/* Cell detail popover — Harvey-style */}
      <Popover
        open={Boolean(cellPopoverAnchor)}
        anchorEl={cellPopoverAnchor}
        onClose={() => { setCellPopoverAnchor(null); setCellPopoverData(null) }}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        slotProps={{ paper: { sx: { width: 340, borderRadius: '12px', boxShadow: '0 8px 32px rgba(0,0,0,0.15)', p: 2.5, display: 'flex', flexDirection: 'column', gap: 2 } } }}
      >
        {cellPopoverData && (
          <>
            {/* Summary */}
            <Box>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                <Typography sx={{ fontSize: '0.6875rem', fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
                  Summary
                </Typography>
                <IconButton
                  size="small"
                  onClick={() => navigator.clipboard.writeText(cellPopoverData.cellValue)}
                  sx={{ p: 0.5 }}
                  title="Копировать"
                >
                  <ContentCopyIcon sx={{ fontSize: 13, color: '#9CA3AF' }} />
                </IconButton>
              </Box>
              <Chip
                label={cellPopoverData.cellValue}
                size="small"
                sx={{ bgcolor: '#F3F4F6', color: '#1F2937', fontWeight: 500, fontSize: '0.8125rem', height: 26, borderRadius: '6px' }}
              />
            </Box>

            {/* Additional Context */}
            {cellPopoverData.reasoning && (
              <Box>
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.75 }}>
                  <Typography sx={{ fontSize: '0.6875rem', fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
                    Additional Context
                  </Typography>
                  <IconButton
                    size="small"
                    onClick={() => navigator.clipboard.writeText(cellPopoverData.reasoning!)}
                    sx={{ p: 0.5 }}
                    title="Копировать"
                  >
                    <ContentCopyIcon sx={{ fontSize: 13, color: '#9CA3AF' }} />
                  </IconButton>
                </Box>
                <Typography sx={{ fontSize: '0.8125rem', color: '#374151', lineHeight: 1.55 }}>
                  {cellPopoverData.reasoning}
                </Typography>
              </Box>
            )}

            {/* Source */}
            {(cellPopoverData.sourceDocName || cellPopoverData.sourcePage) && (
              <Box>
                <Typography sx={{ fontSize: '0.6875rem', fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.07em', mb: 0.75 }}>
                  Source
                </Typography>
                {cellPopoverData.sourceDocName && (
                  <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.75 }}>
                    <FileTextIcon sx={{ fontSize: 14, color: '#6B7280', mt: '2px', flexShrink: 0 }} />
                    <Typography sx={{ fontSize: '0.8125rem', color: '#374151', lineHeight: 1.4 }}>
                      {cellPopoverData.sourceDocName}
                    </Typography>
                  </Box>
                )}
                {cellPopoverData.sourcePage && (
                  <Typography sx={{ fontSize: '0.8125rem', color: '#6B7280', mt: 0.5, pl: 2.75 }}>
                    Стр. {cellPopoverData.sourcePage}
                  </Typography>
                )}
              </Box>
            )}

            {/* View Source button */}
            {onCellClick && (
              <>
                <Divider />
                <Box
                  component="button"
                  type="button"
                  onClick={cellPopoverData.onViewSource}
                  sx={{
                    width: '100%',
                    py: 1,
                    border: '1px solid #E5E7EB',
                    borderRadius: '8px',
                    background: 'white',
                    fontSize: '0.875rem',
                    color: '#374151',
                    fontWeight: 500,
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                    '&:hover': { bgcolor: '#F9FAFB' },
                  }}
                >
                  View Source
                </Box>
              </>
            )}
          </>
        )}
      </Popover>
    </Box>
  )
})

TabularReviewTable.displayName = 'TabularReviewTable'
