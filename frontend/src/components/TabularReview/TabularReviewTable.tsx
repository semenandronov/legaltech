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
import { ArrowUpDown, ChevronDown, FileText, Expand } from "lucide-react"

import { Button } from "@/components/UI/Button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/UI/dropdown-menu"
import Input from "@/components/UI/Input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/UI/table"
import { Badge } from "@/components/UI/Badge"
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

export function TabularReviewTable({ reviewId, tableData, onCellClick }: TabularReviewTableProps) {
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
              variant="ghost"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
            >
              Document
              <ArrowUpDown className="ml-2 h-4 w-4" />
            </Button>
          )
        },
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-muted-foreground" />
            <span className="font-medium">{row.getValue("file_name")}</span>
          </div>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => {
          const status = row.getValue("status") as string
          const statusMap: Record<string, { variant: 'pending' | 'completed' | 'flagged', label: string }> = {
            'reviewed': { variant: 'completed', label: 'Reviewed' },
            'flagged': { variant: 'flagged', label: 'Flagged' },
            'pending_clarification': { variant: 'flagged', label: 'Pending' },
            'not_reviewed': { variant: 'pending', label: 'Not Reviewed' },
          }
          const statusInfo = statusMap[status] || { variant: 'pending' as const, label: status }
          return <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
        },
      },
    ]

    // Add dynamic columns from tableData.columns
    const dynamicColumns: ColumnDef<any>[] = tableData.columns.map((col) => ({
      accessorKey: col.id,
      header: ({ column }) => {
        return (
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
            >
              {col.column_label}
              <ArrowUpDown className="ml-2 h-4 w-4" />
            </Button>
          </div>
        )
      },
      cell: ({ row }) => {
        const cell: TabularCell = row.getValue(col.id)
        const cellValue = cell?.cell_value || "-"
        
        return (
          <div
            className="cursor-pointer hover:bg-muted/70 p-3 rounded transition-colors min-h-[44px] flex items-center"
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
            <div className="flex items-center gap-2 min-h-[24px]">
              <span className="text-sm flex-1">{cellValue === "-" ? <span className="text-muted-foreground italic">—</span> : cellValue}</span>
              {cell?.verbatim_extract && (
                <Expand className="w-3 h-3 text-muted-foreground flex-shrink-0" />
              )}
            </div>
            {cell?.confidence_score && (
              <div className="text-xs text-muted-foreground mt-1">
                Уверенность: {Math.round(cell.confidence_score * 100)}%
              </div>
            )}
          </div>
        )
      },
    }))

    return [...baseColumns, ...dynamicColumns]
  }, [tableData.columns, reviewId])

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

  return (
    <div className="w-full">
      <div className="flex items-center py-4">
        <Input
          placeholder="Поиск по документам..."
          value={(table.getColumn("file_name")?.getFilterValue() as string) ?? ""}
          onChange={(event: React.ChangeEvent<HTMLInputElement>) =>
            table.getColumn("file_name")?.setFilterValue(event.target.value)
          }
          className="max-w-sm"
        />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" className="ml-auto">
              Колонки <ChevronDown className="ml-2 h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {table
              .getAllColumns()
              .filter((column) => column.getCanHide())
              .map((column) => {
                return (
                  <DropdownMenuCheckboxItem
                    key={column.id}
                    className="capitalize"
                    checked={column.getIsVisible()}
                    onCheckedChange={(value) =>
                      column.toggleVisibility(!!value)
                    }
                  >
                    {column.id}
                  </DropdownMenuCheckboxItem>
                )
              })}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className="rounded-md border overflow-hidden bg-background">
        <Table className="tabular-review-table">
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="border-b-2">
                {headerGroup.headers.map((header) => {
                  return (
                    <TableHead key={header.id} className="border-r last:border-r-0 bg-muted/50 font-semibold">
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext()
                          )}
                    </TableHead>
                  )
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows?.length ? (
              table.getRowModel().rows.map((row, rowIndex) => (
                <TableRow
                  key={row.id}
                  data-state={row.getIsSelected() && "selected"}
                  className={`border-b ${rowIndex % 2 === 0 ? 'bg-background' : 'bg-muted/20'}`}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell 
                      key={cell.id}
                      className="border-r last:border-r-0 p-0"
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
                  className="h-24 text-center"
                >
                  Нет результатов.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <div className="flex items-center justify-end space-x-2 py-4">
        <div className="flex-1 text-sm text-muted-foreground">
          {table.getFilteredRowModel().rows.length} строк показано
        </div>
        <div className="space-x-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
          >
            Назад
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
          >
            Вперед
          </Button>
        </div>
      </div>
      
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
    </div>
  )
}

