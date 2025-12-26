import * as React from "react"
import {
  DataGrid,
  GridColDef,
  GridActionsCellItem,
  GridToolbar,
  GridFilterModel,
  GridSortModel,
} from "@mui/x-data-grid"
import {
  Box,
  TextField,
  Menu,
  MenuItem,
  IconButton,
  Chip,
  Typography,
  Stack,
} from "@mui/material"
import { MoreVert as MoreHorizontalIcon } from "@mui/icons-material"
import { CaseListItem } from "@/services/api"
import { useNavigate } from "react-router-dom"

interface CasesTableProps {
  data: CaseListItem[]
  loading?: boolean
}

export function CasesTable({ data, loading }: CasesTableProps) {
  const navigate = useNavigate()
  const [filterModel, setFilterModel] = React.useState<GridFilterModel>({ items: [] })
  const [sortModel, setSortModel] = React.useState<GridSortModel>([])
  const [quickFilter, setQuickFilter] = React.useState("")

  const statusMap: Record<string, { color: 'default' | 'primary' | 'success' | 'warning' | 'error', label: string }> = {
    'review': { color: 'warning', label: 'Review' },
    'investigation': { color: 'error', label: 'Investigation' },
    'litigation': { color: 'error', label: 'Litigation' },
    'completed': { color: 'success', label: 'Completed' },
  }

  const columns: GridColDef<CaseListItem>[] = [
    {
      field: "title",
      headerName: "Название",
      flex: 1,
      minWidth: 200,
      renderCell: (params) => (
        <Typography variant="body2" fontWeight={500}>
          {params.value || "Без названия"}
        </Typography>
      ),
    },
    {
      field: "case_type",
      headerName: "Тип дела",
      width: 150,
      renderCell: (params) => {
        const type = params.value as string
        return type ? (
          <Chip label={type} size="small" variant="outlined" />
        ) : (
          <Typography variant="body2" color="text.secondary">
            —
          </Typography>
        )
      },
    },
    {
      field: "status",
      headerName: "Статус",
      width: 150,
      renderCell: (params) => {
        const status = params.value as string
        const statusInfo = statusMap[status] || { color: 'default' as const, label: status }
        return <Chip label={statusInfo.label} size="small" color={statusInfo.color} />
      },
    },
    {
      field: "num_documents",
      headerName: "Документов",
      width: 120,
      align: "right",
      headerAlign: "right",
      renderCell: (params) => (
        <Typography variant="body2" fontWeight={500}>
          {params.value}
        </Typography>
      ),
    },
    {
      field: "updated_at",
      headerName: "Обновлено",
      width: 150,
      renderCell: (params) => {
        const date = new Date(params.value as string)
        return (
          <Typography variant="body2" color="text.secondary">
            {date.toLocaleDateString("ru-RU")}
          </Typography>
        )
      },
    },
    {
      field: "actions",
      type: "actions",
      headerName: "Действия",
      width: 80,
      getActions: (params) => [
        <GridActionsCellItem
          key="open"
          label="Открыть"
          onClick={() => navigate(`/cases/${params.row.id}/workspace`)}
          showInMenu
        />,
        <GridActionsCellItem
          key="chat"
          label="Чат"
          onClick={() => navigate(`/cases/${params.row.id}/chat`)}
          showInMenu
        />,
        <GridActionsCellItem
          key="export"
          label="Экспорт"
          onClick={() => {}}
          showInMenu
        />,
        <GridActionsCellItem
          key="archive"
          label="Архивировать"
          onClick={() => {}}
          showInMenu
        />,
      ],
    },
  ]

  const rows = data.map((item, index) => ({
    id: item.id || index.toString(),
    ...item,
  }))

  return (
    <Box sx={{ width: "100%", height: 600 }}>
      <Box sx={{ mb: 2 }}>
        <TextField
          placeholder="Поиск по названию..."
          value={quickFilter}
          onChange={(e) => setQuickFilter(e.target.value)}
          size="small"
          sx={{ maxWidth: 300 }}
        />
      </Box>
      <DataGrid
        rows={rows}
        columns={columns}
        loading={loading}
        filterModel={filterModel}
        onFilterModelChange={setFilterModel}
        sortModel={sortModel}
        onSortModelChange={setSortModel}
        quickFilterText={quickFilter}
        pageSizeOptions={[10, 25, 50, 100]}
        initialState={{
          pagination: {
            paginationModel: { pageSize: 25 },
          },
        }}
        slots={{
          toolbar: GridToolbar,
        }}
        slotProps={{
          toolbar: {
            showQuickFilter: true,
            quickFilterProps: { debounceMs: 500 },
          },
        }}
        sx={{
          '& .MuiDataGrid-row:hover': {
            backgroundColor: 'action.hover',
          },
        }}
      />
    </Box>
  )
}
