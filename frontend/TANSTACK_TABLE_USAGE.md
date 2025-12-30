# Использование TanStack Table в проекте

Проект использует [TanStack Table](https://tanstack.com/table) для всех таблиц. Это headless библиотека, которая предоставляет полный контроль над разметкой, стилями и поведением.

## Установка

TanStack Table уже установлен в проекте:
```json
"@tanstack/react-table": "^8.21.3"
```

## Базовые компоненты

Базовые компоненты таблиц находятся в `src/components/UI/table.tsx`:
- `Table` - обертка для таблицы
- `TableHeader` - заголовок таблицы
- `TableBody` - тело таблицы
- `TableRow` - строка таблицы
- `TableHead` - ячейка заголовка
- `TableCell` - ячейка данных
- `TableFooter` - футер таблицы
- `TableCaption` - подпись таблицы

## Пример использования

### Простая таблица

```tsx
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/UI/table"

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
    <Table>
      <TableHeader>
        {table.getHeaderGroups().map((headerGroup) => (
          <TableRow key={headerGroup.id}>
            {headerGroup.headers.map((header) => (
              <TableHead key={header.id}>
                {flexRender(
                  header.column.columnDef.header,
                  header.getContext()
                )}
              </TableHead>
            ))}
          </TableRow>
        ))}
      </TableHeader>
      <TableBody>
        {table.getRowModel().rows.map((row) => (
          <TableRow key={row.id}>
            {row.getVisibleCells().map((cell) => (
              <TableCell key={cell.id}>
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
```

### Таблица с сортировкой и фильтрацией

См. `src/components/Cases/CasesTable.tsx` для полного примера с:
- Сортировкой
- Глобальной фильтрацией
- Пагинацией
- Управлением видимостью колонок

### Таблица с динамическими колонками

См. `src/components/TabularReview/TabularReviewTable.tsx` для примера с:
- Динамическими колонками
- Интерактивными ячейками
- Расширенными возможностями

## Основные возможности

### Сортировка

```tsx
import { getSortedRowModel } from "@tanstack/react-table"

const table = useReactTable({
  // ...
  getSortedRowModel: getSortedRowModel(),
  onSortingChange: setSorting,
  state: { sorting },
})
```

### Фильтрация

```tsx
import { getFilteredRowModel } from "@tanstack/react-table"

const table = useReactTable({
  // ...
  getFilteredRowModel: getFilteredRowModel(),
  onColumnFiltersChange: setColumnFilters,
  onGlobalFilterChange: setGlobalFilter,
  globalFilterFn: "includesString",
  state: { columnFilters, globalFilter },
})
```

### Пагинация

```tsx
import { getPaginationRowModel } from "@tanstack/react-table"

const table = useReactTable({
  // ...
  getPaginationRowModel: getPaginationRowModel(),
  initialState: {
    pagination: {
      pageSize: 25,
    },
  },
})
```

### Управление видимостью колонок

```tsx
const table = useReactTable({
  // ...
  onColumnVisibilityChange: setColumnVisibility,
  state: { columnVisibility },
})
```

## Документация

Полная документация: https://tanstack.com/table/latest

## Примеры в проекте

1. **CasesTable** (`src/components/Cases/CasesTable.tsx`)
   - Таблица дел с сортировкой, фильтрацией и пагинацией
   - Использует базовые UI компоненты

2. **TabularReviewTable** (`src/components/TabularReview/TabularReviewTable.tsx`)
   - Таблица для tabular review с динамическими колонками
   - Интерактивные ячейки с модальными окнами

