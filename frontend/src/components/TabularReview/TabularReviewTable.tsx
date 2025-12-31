"use client"

import * as React from "react"
import {
  ColumnDef,
  ColumnFiltersState,
  SortingState,
  VisibilityState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table"
import {
  Box,
  TextField,
  Button,
  Chip,
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
} from '@mui/material'
import {
  SwapVert as ArrowUpDownIcon,
  ExpandMore as ExpandMoreIcon,
  Description as FileTextIcon,
  ExpandMore as ExpandIcon,
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
} from '@mui/icons-material'
import { TabularRow, TabularColumn, TabularCell, CellDetails } from "@/services/tabularReviewApi"
import { tabularReviewApi } from "@/services/tabularReviewApi"
import { CellExpansionModal } from "./CellExpansionModal"

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
  }) => void
}

export const TabularReviewTable = React.memo(({ reviewId, tableData, onCellClick }: TabularReviewTableProps) => {
  const [sorting, setSorting] = React.useState<SortingState>([])
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([])
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({})
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

  // Build columns dynamically
  const columns = React.useMemo<ColumnDef<any>[]>(() => {
    const baseColumns: ColumnDef<any>[] = [
      {
        accessorKey: "file_name",
        header: ({ column }) => {
          return (
            <Button
              variant="text"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
              endIcon={<ArrowUpDownIcon />}
              sx={{ textTransform: 'none', fontWeight: 600 }}
            >
              Document
            </Button>
          )
        },
        cell: ({ row }) => (
          <Stack direction="row" spacing={1} alignItems="center">
            <FileTextIcon fontSize="small" color="action" />
            <Typography variant="body2" fontWeight={500}>
              {row.getValue("file_name")}
            </Typography>
          </Stack>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => {
          const status = row.getValue("status") as string
          const statusMap: Record<string, { color: 'default' | 'success' | 'error' | 'warning', label: string }> = {
            'reviewed': { color: 'success', label: 'Reviewed' },
            'flagged': { color: 'error', label: 'Flagged' },
            'pending_clarification': { color: 'warning', label: 'Pending' },
            'not_reviewed': { color: 'default', label: 'Not Reviewed' },
          }
          const statusInfo = statusMap[status] || { color: 'default' as const, label: status }
          return <Chip label={statusInfo.label} color={statusInfo.color} size="small" />
        },
      },
    ]

    // Add dynamic columns from tableData.columns
    const dynamicColumns: ColumnDef<any>[] = tableData.columns.map((col) => ({
      accessorKey: col.id,
      header: ({ column }) => {
        return (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Button
              variant="text"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
              endIcon={<ArrowUpDownIcon />}
              sx={{ textTransform: 'none', fontWeight: 600 }}
            >
              {col.column_label}
            </Button>
          </Box>
        )
      },
      cell: ({ row }) => {
        const cell: TabularCell = row.getValue(col.id)
        const cellValue = cell?.cell_value || "-"
        
        return (
          <Box
            sx={{
              cursor: 'pointer',
              p: 1.5,
              borderRadius: 1,
              minHeight: 44,
              display: 'flex',
              alignItems: 'center',
              transition: (theme) => theme.transitions.create('background-color', {
                duration: theme.transitions.duration.shorter,
              }),
              '&:hover': {
                bgcolor: 'action.hover',
              },
            }}
            onClick={async () => {
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
            <Stack spacing={0.5} sx={{ flex: 1, minWidth: 0 }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ minHeight: 24 }}>
                <Typography
                  variant="body2"
                  sx={{
                    flex: 1,
                    fontStyle: cellValue === "-" ? 'italic' : 'normal',
                    color: cellValue === "-" ? 'text.secondary' : 'text.primary',
                  }}
                >
                  {cellValue === "-" ? "—" : cellValue}
                </Typography>
                {cell?.verbatim_extract && (
                  <ExpandIcon fontSize="small" color="action" />
                )}
              </Stack>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                {cell?.confidence_score !== null && cell?.confidence_score !== undefined && (
                  <Chip
                    label={`${Math.round(cell.confidence_score * 100)}%`}
                    size="small"
                    sx={{
                      height: 20,
                      fontSize: '0.7rem',
                      bgcolor: cell.confidence_score >= 0.9 
                        ? 'success.light' 
                        : cell.confidence_score >= 0.7 
                        ? 'warning.light' 
                        : 'error.light',
                      color: cell.confidence_score >= 0.9 
                        ? 'success.dark' 
                        : cell.confidence_score >= 0.7 
                        ? 'warning.dark' 
                        : 'error.dark',
                    }}
                  />
                )}
                {(cell?.source_page || cell?.source_section) && (
                  <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
                    {cell?.source_page && `Стр. ${cell.source_page}`}
                    {cell?.source_page && cell?.source_section && ', '}
                    {cell?.source_section && cell.source_section}
                  </Typography>
                )}
              </Stack>
            </Stack>
          </Box>
        )
      },
    }))

    return [...baseColumns, ...dynamicColumns]
  }, [tableData.columns, reviewId, onCellClick])

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
    state: {
      sorting,
      columnFilters,
      columnVisibility,
    },
  })

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
          placeholder="Поиск по документам..."
          value={(table.getColumn("file_name")?.getFilterValue() as string) ?? ""}
          onChange={(event: React.ChangeEvent<HTMLInputElement>) =>
            table.getColumn("file_name")?.setFilterValue(event.target.value)
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
      <TableContainer component={Paper} variant="outlined">
        <Table>
          <TableHead>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableCell
                    key={header.id}
                    sx={{
                      borderRight: 1,
                      borderColor: 'divider',
                      bgcolor: 'action.hover',
                      fontWeight: 600,
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
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableHead>
          <TableBody>
            {table.getRowModel().rows?.length ? (
              table.getRowModel().rows.map((row, rowIndex) => (
                <TableRow
                  key={row.id}
                  sx={{
                    bgcolor: rowIndex % 2 === 0 ? 'background.paper' : 'action.hover',
                  }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell
                      key={cell.id}
                      sx={{
                        borderRight: 1,
                        borderColor: 'divider',
                        p: 0,
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
            ) : (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  align="center"
                  sx={{ height: 96 }}
                >
                  <Typography color="text.secondary">
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
          {table.getFilteredRowModel().rows.length} строк показано
        </Typography>
        <Stack direction="row" spacing={1}>
          <Button
            variant="outlined"
            size="small"
            startIcon={<ChevronLeftIcon />}
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
          >
            Назад
          </Button>
          <Button
            variant="outlined"
            size="small"
            endIcon={<ChevronRightIcon />}
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
          >
            Вперед
          </Button>
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
