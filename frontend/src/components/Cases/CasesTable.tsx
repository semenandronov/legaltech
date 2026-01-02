import * as React from "react"
import {
  ColumnDef,
  ColumnFiltersState,
  SortingState,
  VisibilityState,
  RowSelectionState,
  ColumnSizingState,
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
  Chip,
  Pagination,
  Select,
  FormControl,
  InputLabel,
  Tooltip,
  CircularProgress,
  Snackbar,
  Alert,
} from '@mui/material'
import {
  ChevronDown as ChevronDownIcon,
  SwapVert as ArrowUpDownIcon,
  MoreVert as MoreHorizontalIcon,
  Description as FileTextIcon,
  MessageSquare as MessageSquareIcon,
  Download as DownloadIcon,
  Archive as ArchiveIcon,
  ArrowUpward,
  ArrowDownward,
  UnfoldMore,
} from '@mui/icons-material'
import { CaseListItem } from "@/services/api"
import { useNavigate } from "react-router-dom"
import {
  MuiTableContainer,
  MuiTableHeader,
  MuiTableHeaderRow,
  MuiTableHeaderCell,
  MuiTableBodyRow,
  MuiTableBodyCell,
  SortIndicator,
  TableToolbar,
  EmptyTableRow,
  LoadingTableRow,
} from "@/components/UI/MuiTableComponents"
import { useTableState } from "@/hooks/useTableState"
import { exportToCSV, exportSelectedRows } from "@/utils/exportUtils"

interface CasesTableProps {
  data: CaseListItem[]
  loading?: boolean
}

export function CasesTable({ data, loading }: CasesTableProps) {
  const navigate = useNavigate()
  const [snackbar, setSnackbar] = React.useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false,
    message: '',
    severity: 'success',
  })

  // Используем хук для сохранения состояния
  const {
    sorting,
    columnFilters,
    columnVisibility,
    columnSizing,
    setSorting,
    setColumnFilters,
    setColumnVisibility,
    setColumnSizing,
  } = useTableState({
    tableId: 'cases-table',
    autoSave: true,
  })

  const [rowSelection, setRowSelection] = React.useState<RowSelectionState>({})
  const [globalFilter, setGlobalFilter] = React.useState("")
  const [globalFilterInput, setGlobalFilterInput] = React.useState("")
  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null)
  const [menuAnchorEl, setMenuAnchorEl] = React.useState<{ el: HTMLElement; rowId: string } | null>(null)

  // Debounced глобальный фильтр
  React.useEffect(() => {
    const timer = setTimeout(() => {
      setGlobalFilter(globalFilterInput)
    }, 300)
    return () => clearTimeout(timer)
  }, [globalFilterInput])

  const statusMap: Record<string, { color: 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning', label: string }> = {
    'review': { color: 'info', label: 'Review' },
    'investigation': { color: 'warning', label: 'Investigation' },
    'litigation': { color: 'error', label: 'Litigation' },
    'completed': { color: 'success', label: 'Completed' },
  }

  const columns: ColumnDef<CaseListItem>[] = React.useMemo(() => [
    {
      id: 'select',
      header: ({ table }) => (
        <Checkbox
          checked={table.getIsAllPageRowsSelected()}
          indeterminate={table.getIsSomePageRowsSelected()}
          onChange={table.getToggleAllPageRowsSelectedHandler()}
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onChange={row.getToggleSelectedHandler()}
          onClick={(e) => e.stopPropagation()}
        />
      ),
      enableSorting: false,
      enableHiding: false,
    },
    {
      accessorKey: "title",
      header: ({ column }) => {
        const sortDirection = column.getIsSorted()
        return (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Button
              variant="text"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
              sx={{ textTransform: 'none', fontWeight: 600, color: '#1F2937', minWidth: 'auto', p: 0 }}
            >
              Название
            </Button>
            <SortIndicator
              sortDirection={sortDirection === 'asc' ? 'asc' : sortDirection === 'desc' ? 'desc' : false}
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
            />
          </Box>
        )
      },
      cell: ({ row }) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <FileTextIcon fontSize="small" sx={{ color: '#6B7280' }} />
          <Typography variant="body2" sx={{ fontWeight: 500 }}>
            {row.getValue("title") || "Без названия"}
          </Typography>
        </Stack>
      ),
    },
    {
      accessorKey: "case_type",
      header: "Тип дела",
      cell: ({ row }) => {
        const type = row.getValue("case_type") as string
        return type ? (
          <Chip label={type} size="small" variant="outlined" />
        ) : (
          <Typography variant="body2" sx={{ color: '#6B7280' }}>—</Typography>
        )
      },
    },
    {
      accessorKey: "status",
      header: ({ column }) => {
        const sortDirection = column.getIsSorted()
        return (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Button
              variant="text"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
              sx={{ textTransform: 'none', fontWeight: 600, color: '#1F2937', minWidth: 'auto', p: 0 }}
            >
              Статус
            </Button>
            <SortIndicator
              sortDirection={sortDirection === 'asc' ? 'asc' : sortDirection === 'desc' ? 'desc' : false}
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
            />
          </Box>
        )
      },
      cell: ({ row }) => {
        const status = row.getValue("status") as string
        const statusInfo = statusMap[status] || { color: 'default' as const, label: status }
        return <Chip label={statusInfo.label} color={statusInfo.color} size="small" />
      },
    },
    {
      accessorKey: "num_documents",
      header: ({ column }) => {
        const sortDirection = column.getIsSorted()
        return (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, justifyContent: 'flex-end' }}>
            <Button
              variant="text"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
              sx={{ textTransform: 'none', fontWeight: 600, color: '#1F2937', minWidth: 'auto', p: 0 }}
            >
              Документов
            </Button>
            <SortIndicator
              sortDirection={sortDirection === 'asc' ? 'asc' : sortDirection === 'desc' ? 'desc' : false}
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
            />
          </Box>
        )
      },
      cell: ({ row }) => (
        <Typography variant="body2" sx={{ textAlign: 'right', fontWeight: 500 }}>
          {row.getValue("num_documents")}
        </Typography>
      ),
    },
    {
      accessorKey: "updated_at",
      header: ({ column }) => {
        const sortDirection = column.getIsSorted()
        return (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Button
              variant="text"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
              sx={{ textTransform: 'none', fontWeight: 600, color: '#1F2937', minWidth: 'auto', p: 0 }}
            >
              Обновлено
            </Button>
            <SortIndicator
              sortDirection={sortDirection === 'asc' ? 'asc' : sortDirection === 'desc' ? 'desc' : false}
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
            />
          </Box>
        )
      },
      cell: ({ row }) => {
        const date = new Date(row.getValue("updated_at") as string)
        return (
          <Typography variant="body2" sx={{ color: '#6B7280' }}>
            {date.toLocaleDateString("ru-RU")}
          </Typography>
        )
      },
    },
    {
      id: "actions",
      enableHiding: false,
      cell: ({ row }) => {
        const caseItem = row.original
        return (
          <IconButton
            size="small"
            onClick={(e) => {
              e.stopPropagation()
              setMenuAnchorEl({ el: e.currentTarget, rowId: row.id })
            }}
          >
            <MoreHorizontalIcon fontSize="small" />
          </IconButton>
        )
      },
    },
  ], [])

  const table = useReactTable({
    data,
    columns,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    onColumnVisibilityChange: setColumnVisibility,
    onColumnSizingChange: setColumnSizing,
    onGlobalFilterChange: setGlobalFilter,
    globalFilterFn: "includesString",
    onRowSelectionChange: setRowSelection,
    enableRowSelection: true,
    enableColumnResizing: true,
    columnResizeMode: 'onChange',
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      columnSizing,
      globalFilter,
      rowSelection,
    },
    initialState: {
      pagination: {
        pageSize: 25,
      },
    },
  })

  const selectedRows = table.getFilteredSelectedRowModel().rows
  const selectedCount = selectedRows.length

  const handleMenuOpen = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget)
  }

  const handleMenuClose = () => {
    setAnchorEl(null)
  }

  const handleExport = () => {
    try {
      const exportColumns = [
        { id: 'title', header: 'Название' },
        { id: 'case_type', header: 'Тип дела' },
        { id: 'status', header: 'Статус' },
        { id: 'num_documents', header: 'Документов' },
        { id: 'updated_at', header: 'Обновлено' },
      ]

      if (selectedCount > 0) {
        exportSelectedRows(
          selectedRows.map(row => row.original),
          exportColumns,
          'csv'
        )
        setSnackbar({ open: true, message: `Экспортировано ${selectedCount} строк`, severity: 'success' })
      } else {
        exportToCSV(data, exportColumns)
        setSnackbar({ open: true, message: 'Экспортировано все данные', severity: 'success' })
      }
    } catch (error) {
      setSnackbar({ open: true, message: 'Ошибка при экспорте', severity: 'error' })
    }
  }

  const handleArchive = () => {
    // TODO: Реализовать архивирование
    setSnackbar({ open: true, message: 'Функция архивирования в разработке', severity: 'info' })
  }

  return (
    <Box sx={{ width: '100%' }}>
      <Stack direction="row" spacing={2} alignItems="center" sx={{ py: 2 }}>
        <TextField
          placeholder="Поиск по всем полям..."
          value={globalFilterInput}
          onChange={(e) => setGlobalFilterInput(e.target.value)}
          size="small"
          sx={{ maxWidth: 300 }}
        />
        <Button
          variant="outlined"
          endIcon={<ChevronDownIcon />}
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
                <Typography sx={{ textTransform: 'capitalize', ml: 1 }}>
                  {column.id}
                </Typography>
              </MenuItem>
            ))}
        </Menu>
      </Stack>

      {selectedCount > 0 && (
        <TableToolbar
          selectedCount={selectedCount}
          onClearSelection={() => setRowSelection({})}
          actions={
            <Stack direction="row" spacing={1}>
              <Tooltip title="Экспорт выбранных">
                <IconButton size="small" onClick={handleExport}>
                  <DownloadIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              <Tooltip title="Архивировать">
                <IconButton size="small" onClick={handleArchive}>
                  <ArchiveIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Stack>
          }
        />
      )}

      <MuiTableContainer>
        <Table sx={{ borderCollapse: 'separate' }}>
          <MuiTableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <MuiTableHeaderRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <MuiTableHeaderCell
                    key={header.id}
                    align={header.id === 'num_documents' ? 'right' : 'left'}
                    width={header.getSize()}
                    sx={{
                      position: 'relative',
                      '&::after': {
                        content: '""',
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
                        zIndex: 1,
                      }}
                    />
                  </MuiTableHeaderCell>
                ))}
              </MuiTableHeaderRow>
            ))}
          </MuiTableHeader>
          <TableBody>
            {loading ? (
              <LoadingTableRow colSpan={columns.length} />
            ) : table.getRowModel().rows?.length ? (
              table.getRowModel().rows.map((row, index) => (
                <MuiTableBodyRow
                  key={row.id}
                  index={index}
                  selected={row.getIsSelected()}
                  onClick={() => navigate(`/cases/${row.original.id}/chat`)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <MuiTableBodyCell
                      key={cell.id}
                      align={cell.column.id === 'num_documents' ? 'right' : 'left'}
                      sx={{ width: cell.column.getSize() }}
                    >
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext()
                      )}
                    </MuiTableBodyCell>
                  ))}
                </MuiTableBodyRow>
              ))
            ) : (
              <EmptyTableRow colSpan={columns.length} />
            )}
          </TableBody>
        </Table>
      </MuiTableContainer>

      {/* Пагинация */}
      <Stack direction="row" spacing={2} alignItems="center" justifyContent="space-between" sx={{ py: 2 }}>
        <Typography variant="body2" sx={{ color: '#6B7280' }}>
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

      {/* Меню действий для строки */}
      <Menu
        anchorEl={menuAnchorEl?.el}
        open={Boolean(menuAnchorEl)}
        onClose={() => setMenuAnchorEl(null)}
      >
        <MenuItem
          onClick={() => {
            if (menuAnchorEl) {
              const row = table.getRowModel().rows.find(r => r.id === menuAnchorEl.rowId)
              if (row) {
                navigate(`/cases/${row.original.id}/chat`)
              }
            }
            setMenuAnchorEl(null)
          }}
        >
          <FileTextIcon sx={{ mr: 1, fontSize: 20 }} />
          Открыть
        </MenuItem>
        <MenuItem
          onClick={() => {
            if (menuAnchorEl) {
              const row = table.getRowModel().rows.find(r => r.id === menuAnchorEl.rowId)
              if (row) {
                navigate(`/cases/${row.original.id}/chat`)
              }
            }
            setMenuAnchorEl(null)
          }}
        >
          <MessageSquareIcon sx={{ mr: 1, fontSize: 20 }} />
          Чат
        </MenuItem>
        <MenuItem onClick={handleExport}>
          <DownloadIcon sx={{ mr: 1, fontSize: 20 }} />
          Экспорт
        </MenuItem>
        <MenuItem onClick={handleArchive}>
          <ArchiveIcon sx={{ mr: 1, fontSize: 20 }} />
          Архивировать
        </MenuItem>
      </Menu>

      {/* Snackbar для уведомлений */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
      >
        <Alert onClose={() => setSnackbar({ ...snackbar, open: false })} severity={snackbar.severity} sx={{ width: '100%' }}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  )
}
