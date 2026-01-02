# Использование TanStack Table в проекте

Проект использует [TanStack Table](https://tanstack.com/table) для всех таблиц. Это headless библиотека, которая предоставляет полный контроль над разметкой, стилями и поведением.

## Установка

TanStack Table уже установлен в проекте:
```json
"@tanstack/react-table": "^8.21.3"
"@tanstack/react-virtual": "^3.11.1"
```

## UI Библиотека

Проект использует **Material-UI (MUI)** для всех компонентов таблиц. Базовые компоненты находятся в `src/components/UI/MuiTableComponents.tsx`.

## Базовые компоненты

### MUI Компоненты (рекомендуется)

Базовые компоненты таблиц находятся в `src/components/UI/MuiTableComponents.tsx`:
- `MuiTableContainer` - обертка для контейнера таблицы
- `MuiTableHeader` - заголовок таблицы
- `MuiTableHeaderRow` - строка заголовка
- `MuiTableHeaderCell` - ячейка заголовка
- `MuiTableBodyRow` - строка тела таблицы
- `MuiTableBodyCell` - ячейка данных
- `SortIndicator` - индикатор сортировки
- `TableToolbar` - toolbar с действиями
- `EmptyTableRow` - пустая строка (нет данных)
- `LoadingTableRow` - строки загрузки

### Устаревшие компоненты

Старые компоненты из `src/components/UI/table.tsx` (shadcn/ui) помечены как deprecated. Используйте MUI компоненты.

## Пример использования

### Простая таблица с MUI

```tsx
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table"
import {
  MuiTableContainer,
  MuiTableHeader,
  MuiTableHeaderRow,
  MuiTableHeaderCell,
  MuiTableBodyRow,
  MuiTableBodyCell,
} from "@/components/UI/MuiTableComponents"
import { Table, TableBody } from '@mui/material'

const columns: ColumnDef<DataType>[] = [
  {
    accessorKey: "name",
    header: "Название",
  },
  {
    accessorKey: "status",
    header: "Статус",
  },
]

function MyTable({ data }: { data: DataType[] }) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <MuiTableContainer>
      <Table>
        <MuiTableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <MuiTableHeaderRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <MuiTableHeaderCell key={header.id}>
                  {header.isPlaceholder
                    ? null
                    : flexRender(
                        header.column.columnDef.header,
                        header.getContext()
                      )}
                </MuiTableHeaderCell>
              ))}
            </MuiTableHeaderRow>
          ))}
        </MuiTableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row, index) => (
            <MuiTableBodyRow key={row.id} index={index}>
              {row.getVisibleCells().map((cell) => (
                <MuiTableBodyCell key={cell.id}>
                  {flexRender(
                    cell.column.columnDef.cell,
                    cell.getContext()
                  )}
                </MuiTableBodyCell>
              ))}
            </MuiTableBodyRow>
          ))}
        </TableBody>
      </Table>
    </MuiTableContainer>
  )
}
```

### Таблица с сортировкой и фильтрацией

См. `src/components/Cases/CasesTable.tsx` для полного примера с:
- Сортировкой с визуальными индикаторами
- Глобальной фильтрацией с debounce
- Пагинацией с выбором размера страницы
- Управлением видимостью колонок
- Выбором строк (row selection)
- Изменением размера колонок
- Экспортом данных

### Таблица с динамическими колонками и виртуализацией

См. `src/components/TabularReview/TabularReviewTable.tsx` для примера с:
- Динамическими колонками
- Интерактивными ячейками
- Виртуализацией для больших таблиц (>100 строк)
- Закреплением колонок
- Кешированием данных ячеек
- Глобальным поиском

## Основные возможности

### Сортировка с индикаторами

```tsx
import { getSortedRowModel } from "@tanstack/react-table"
import { SortIndicator } from "@/components/UI/MuiTableComponents"

const columns: ColumnDef<DataType>[] = [
  {
    accessorKey: "name",
    header: ({ column }) => {
      const sortDirection = column.getIsSorted()
      return (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Button
            variant="text"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
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
  },
]

const table = useReactTable({
  // ...
  getSortedRowModel: getSortedRowModel(),
  onSortingChange: setSorting,
  state: { sorting },
})
```

### Фильтрация

#### Глобальный фильтр

```tsx
import { getFilteredRowModel } from "@tanstack/react-table"

const [globalFilter, setGlobalFilter] = useState("")
const [globalFilterInput, setGlobalFilterInput] = useState("")

// Debounced фильтр
useEffect(() => {
  const timer = setTimeout(() => {
    setGlobalFilter(globalFilterInput)
  }, 300)
  return () => clearTimeout(timer)
}, [globalFilterInput])

const table = useReactTable({
  // ...
  getFilteredRowModel: getFilteredRowModel(),
  onGlobalFilterChange: setGlobalFilter,
  globalFilterFn: "includesString",
  state: { globalFilter },
})
```

#### Фильтры по колонкам

```tsx
const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])

const table = useReactTable({
  // ...
  getFilteredRowModel: getFilteredRowModel(),
  onColumnFiltersChange: setColumnFilters,
  state: { columnFilters },
})

// В заголовке колонки
header: ({ column }) => {
  return (
    <TextField
      size="small"
      placeholder="Фильтр..."
      value={(column.getFilterValue() as string) ?? ""}
      onChange={(e) => column.setFilterValue(e.target.value)}
    />
  )
}
```

### Пагинация

```tsx
import { getPaginationRowModel } from "@tanstack/react-table"
import { Pagination, Select, MenuItem } from '@mui/material'

const table = useReactTable({
  // ...
  getPaginationRowModel: getPaginationRowModel(),
  initialState: {
    pagination: {
      pageSize: 25,
    },
  },
})

// В UI
<Stack direction="row" spacing={2} alignItems="center">
  <Select
    value={table.getState().pagination.pageSize}
    onChange={(e) => table.setPageSize(Number(e.target.value))}
  >
    {[10, 25, 50, 100].map((pageSize) => (
      <MenuItem key={pageSize} value={pageSize}>
        {pageSize}
      </MenuItem>
    ))}
  </Select>
  <Pagination
    count={table.getPageCount()}
    page={table.getState().pagination.pageIndex + 1}
    onChange={(_, page) => table.setPageIndex(page - 1)}
  />
</Stack>
```

### Выбор строк (Row Selection)

```tsx
import { RowSelectionState } from "@tanstack/react-table"

const [rowSelection, setRowSelection] = useState<RowSelectionState>({})

const table = useReactTable({
  // ...
  onRowSelectionChange: setRowSelection,
  enableRowSelection: true,
  state: { rowSelection },
})

// Колонка для выбора
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
    />
  ),
}

// Получение выбранных строк
const selectedRows = table.getFilteredSelectedRowModel().rows
```

### Изменение размера колонок

```tsx
import { ColumnSizingState } from "@tanstack/react-table"

const [columnSizing, setColumnSizing] = useState<ColumnSizingState>({})

const table = useReactTable({
  // ...
  onColumnSizingChange: setColumnSizing,
  enableColumnResizing: true,
  columnResizeMode: 'onChange',
  state: { columnSizing },
})

// В ячейке заголовка
<TableCell
  sx={{
    width: header.getSize(),
    position: 'relative',
    '&::after': {
      content: '""',
      position: 'absolute',
      right: 0,
      top: 0,
      bottom: 0,
      width: '4px',
      cursor: 'col-resize',
    },
  }}
>
  {/* содержимое */}
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
    }}
  />
</TableCell>
```

### Закрепление колонок

```tsx
import { ColumnPinningState } from "@tanstack/react-table"

const [columnPinning, setColumnPinning] = useState<ColumnPinningState>({
  left: ['file_name'],
  right: [],
})

const table = useReactTable({
  // ...
  onColumnPinningChange: setColumnPinning,
  enablePinning: true,
  state: { columnPinning },
})

// В ячейке
<TableCell
  sx={{
    position: cell.column.getIsPinned() ? 'sticky' : 'static',
    left: cell.column.getIsPinned() === 'left' 
      ? `${cell.column.getStart('left')}px` 
      : undefined,
    right: cell.column.getIsPinned() === 'right' 
      ? `${cell.column.getAfter('right')}px` 
      : undefined,
    zIndex: cell.column.getIsPinned() ? 10 : 1,
  }}
>
  {/* содержимое */}
</TableCell>
```

### Виртуализация для больших таблиц

```tsx
import { useVirtualizer } from "@tanstack/react-virtual"

const tableContainerRef = useRef<HTMLDivElement>(null)
const shouldVirtualize = table.getRowModel().rows.length > 100

const { rows: virtualRows, totalSize } = useVirtualizer({
  count: table.getRowModel().rows.length,
  getScrollElement: () => tableContainerRef.current,
  estimateSize: () => 50, // Высота строки
  overscan: 10,
})

// В TableContainer
<TableContainer
  ref={tableContainerRef}
  sx={{
    maxHeight: shouldVirtualize ? '600px' : 'none',
    overflow: shouldVirtualize ? 'auto' : 'hidden',
  }}
>
  <TableBody>
    {shouldVirtualize ? (
      <>
        <tr style={{ height: `${virtualRows[0]?.start ?? 0}px` }} />
        {virtualRows.map((virtualRow) => {
          const row = table.getRowModel().rows[virtualRow.index]
          return (
            <TableRow
              key={row.id}
              ref={virtualRow.measureElement}
            >
              {/* ячейки */}
            </TableRow>
          )
        })}
        <tr style={{ height: `${totalSize - (virtualRows[virtualRows.length - 1]?.end ?? 0)}px` }} />
      </>
    ) : (
      // обычный рендеринг
    )}
  </TableBody>
</TableContainer>
```

### Сохранение состояния таблицы

```tsx
import { useTableState } from "@/hooks/useTableState"

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
  tableId: 'my-table',
  autoSave: true,
  debounceMs: 300,
})

const table = useReactTable({
  // ...
  state: {
    sorting,
    columnFilters,
    columnVisibility,
    columnSizing,
  },
  // ...
})
```

### Экспорт данных

```tsx
import { exportToCSV, exportSelectedRows } from "@/utils/exportUtils"

// Экспорт всех данных
const handleExport = () => {
  const columns = [
    { id: 'name', header: 'Название' },
    { id: 'status', header: 'Статус' },
  ]
  exportToCSV(data, columns, 'export.csv')
}

// Экспорт выбранных строк
const handleExportSelected = () => {
  const selectedRows = table.getFilteredSelectedRowModel().rows
  exportSelectedRows(
    selectedRows.map(row => row.original),
    columns,
    'csv',
    'selected.csv'
  )
}
```

## Утилиты

### tableUtils.ts

- `getCellValue<T>(row: T, columnId: string)` - получение значения ячейки
- `formatCellContent(value: any, emptyValue?: string)` - форматирование содержимого
- `saveTableState(tableId: string, state: TableState)` - сохранение состояния
- `loadTableState<T>(tableId: string)` - загрузка состояния
- `clearTableState(tableId: string)` - очистка состояния
- `debounce<T>(func: T, wait: number)` - debounce функция

### exportUtils.ts

- `exportToCSV<T>(data: T[], columns, filename?)` - экспорт в CSV
- `exportToJSON<T>(data: T[], filename?)` - экспорт в JSON
- `exportSelectedRows<T>(selectedRows, columns, format, filename?)` - экспорт выбранных строк

## Best Practices

1. **Используйте MUI компоненты** - они обеспечивают единый стиль и лучшую производительность
2. **Виртуализация для больших таблиц** - включайте виртуализацию при >100 строк
3. **Debounce для фильтров** - используйте debounce для глобального поиска (300ms)
4. **Кеширование данных** - кешируйте результаты API запросов (например, cellDetails)
5. **Мемоизация колонок** - используйте `useMemo` для определения колонок
6. **Сохранение состояния** - используйте `useTableState` для сохранения настроек пользователя
7. **Оптимизация рендеринга** - используйте `React.memo` для компонентов ячеек
8. **Типизация** - всегда типизируйте колонки и данные

## Примеры в проекте

1. **CasesTable** (`src/components/Cases/CasesTable.tsx`)
   - Полный пример с MUI компонентами
   - Сортировка, фильтрация, пагинация
   - Выбор строк, изменение размера колонок
   - Экспорт данных
   - Сохранение состояния

2. **TabularReviewTable** (`src/components/TabularReview/TabularReviewTable.tsx`)
   - Динамические колонки
   - Виртуализация для больших таблиц
   - Закрепление колонок
   - Кеширование данных ячеек
   - Глобальный поиск

## Документация

- Полная документация TanStack Table: https://tanstack.com/table/latest
- Документация TanStack Virtual: https://tanstack.com/virtual/latest
- Material-UI Tables: https://mui.com/material-ui/react-table/
