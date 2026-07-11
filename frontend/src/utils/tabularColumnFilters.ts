import type { TabularColumn, TabularRow } from "@/services/tabularReviewApi"
import { isDateColumn, parseTabularDateMs } from "./tabularDateUtils"
import { isNumericColumn, parseFilterNumber, parseNumericCellValue } from "./tabularNumericUtils"

export const EMPTY_VALUE_KEY = ""
export const EMPTY_VALUE_LABEL = "—"

export type ColumnFilterOperator =
  | "equals"
  | "not_equals"
  | "contains"
  | "not_empty"
  | "date_after"
  | "date_before"
  | "date_between"
  | "number_greater_than"
  | "number_less_than"
  | "number_between"

export interface ColumnValueFilterCondition {
  columnId: string
  operator: ColumnFilterOperator
  selectedValues: string[]
  textQuery: string
  dateFrom: string | null
  dateTo: string | null
  /** Порог для number_greater_than / number_less_than */
  numberFrom: string | null
  /** Верхняя граница для number_between */
  numberTo: string | null
}

export interface FilterOperatorOption {
  value: ColumnFilterOperator
  label: string
}

const TEXT_OPERATORS: FilterOperatorOption[] = [
  { value: "equals", label: "Равно" },
  { value: "not_equals", label: "Не равно" },
  { value: "contains", label: "Содержит" },
  { value: "not_empty", label: "Не пусто" },
]

const DATE_OPERATORS: FilterOperatorOption[] = [
  { value: "equals", label: "Равно" },
  { value: "not_equals", label: "Не равно" },
  { value: "not_empty", label: "Не пусто" },
  { value: "date_after", label: "Позже" },
  { value: "date_before", label: "Раньше" },
  { value: "date_between", label: "От — до" },
]

const NUMBER_OPERATORS: FilterOperatorOption[] = [
  { value: "equals", label: "Равно" },
  { value: "not_equals", label: "Не равно" },
  { value: "not_empty", label: "Не пусто" },
  { value: "number_greater_than", label: "Больше" },
  { value: "number_less_than", label: "Меньше" },
  { value: "number_between", label: "От — до" },
]

export function emptyFilterCondition(): ColumnValueFilterCondition {
  return {
    columnId: "",
    operator: "equals",
    selectedValues: [],
    textQuery: "",
    dateFrom: null,
    dateTo: null,
    numberFrom: null,
    numberTo: null,
  }
}

export function normalizeCellValue(val: string | null | undefined): string {
  return val == null || val === "" ? EMPTY_VALUE_KEY : String(val).trim()
}

export function isEmptyCellValue(val: string | null | undefined): boolean {
  const normalized = normalizeCellValue(val)
  if (normalized === EMPTY_VALUE_KEY) return true
  const upper = normalized.toUpperCase()
  return upper === "-" || upper === "—" || upper === "N/A"
}

export function getOperatorsForColumn(column: TabularColumn | undefined): FilterOperatorOption[] {
  if (column && isDateColumn(column.column_type, column.column_label)) {
    return DATE_OPERATORS
  }
  if (column && isNumericColumn(column.column_type, column.column_label)) {
    return NUMBER_OPERATORS
  }
  return TEXT_OPERATORS
}

export function defaultOperatorForColumn(column: TabularColumn | undefined): ColumnFilterOperator {
  return getOperatorsForColumn(column)[0]?.value ?? "equals"
}

export function isDateOperator(operator: ColumnFilterOperator): boolean {
  return operator === "date_after" || operator === "date_before" || operator === "date_between"
}

export function isNumberOperator(operator: ColumnFilterOperator): boolean {
  return (
    operator === "number_greater_than" ||
    operator === "number_less_than" ||
    operator === "number_between"
  )
}

export function isFilterConditionComplete(
  cond: ColumnValueFilterCondition,
  column?: TabularColumn,
): boolean {
  if (!cond.columnId) return false

  switch (cond.operator) {
    case "not_empty":
      return true
    case "contains":
      return cond.textQuery.trim().length > 0
    case "equals":
    case "not_equals":
      if (column && isDateColumn(column.column_type, column.column_label)) {
        return Boolean(cond.dateFrom)
      }
      if (column && isNumericColumn(column.column_type, column.column_label)) {
        return parseFilterNumber(cond.numberFrom) != null
      }
      return cond.selectedValues.length > 0
    case "number_greater_than":
    case "number_less_than":
      return parseFilterNumber(cond.numberFrom) != null
    case "number_between":
      return (
        parseFilterNumber(cond.numberFrom) != null && parseFilterNumber(cond.numberTo) != null
      )
    case "date_after":
    case "date_before":
      return Boolean(cond.dateFrom)
    case "date_between":
      return Boolean(cond.dateFrom && cond.dateTo)
    default: {
      const _exhaustive: never = cond.operator
      return _exhaustive
    }
  }
}

function cellDateMs(cellValue: string | null | undefined): number | null {
  return parseTabularDateMs(cellValue ?? "")
}

function filterDateMs(iso: string | null): number | null {
  if (!iso) return null
  return parseTabularDateMs(iso)
}

export function evaluateColumnValueFilter(
  cellValue: string | null | undefined,
  cond: ColumnValueFilterCondition,
  column?: TabularColumn,
): boolean {
  const normalized = normalizeCellValue(cellValue)
  const empty = isEmptyCellValue(cellValue)

  switch (cond.operator) {
    case "not_empty":
      return !empty

    case "contains": {
      if (empty) return false
      const query = cond.textQuery.trim().toLowerCase()
      if (!query) return true
      return normalized.toLowerCase().includes(query)
    }

    case "equals":
      if (column && isDateColumn(column.column_type, column.column_label)) {
        const cellMs = cellDateMs(cellValue)
        const filterMs = filterDateMs(cond.dateFrom)
        if (cellMs === null || filterMs === null) return false
        return cellMs === filterMs
      }
      if (column && isNumericColumn(column.column_type, column.column_label)) {
        const cellNum = parseNumericCellValue(cellValue)
        const filterNum = parseFilterNumber(cond.numberFrom)
        if (cellNum === null || filterNum === null) return false
        return cellNum === filterNum
      }
      return cond.selectedValues.includes(normalized)

    case "not_equals":
      if (column && isDateColumn(column.column_type, column.column_label)) {
        const cellMs = cellDateMs(cellValue)
        const filterMs = filterDateMs(cond.dateFrom)
        if (filterMs === null) return true
        if (cellMs === null) return true
        return cellMs !== filterMs
      }
      if (column && isNumericColumn(column.column_type, column.column_label)) {
        const cellNum = parseNumericCellValue(cellValue)
        const filterNum = parseFilterNumber(cond.numberFrom)
        if (filterNum === null) return true
        if (cellNum === null) return true
        return cellNum !== filterNum
      }
      return !cond.selectedValues.includes(normalized)

    case "number_greater_than": {
      const cellNum = parseNumericCellValue(cellValue)
      const filterNum = parseFilterNumber(cond.numberFrom)
      if (cellNum === null || filterNum === null) return false
      return cellNum > filterNum
    }

    case "number_less_than": {
      const cellNum = parseNumericCellValue(cellValue)
      const filterNum = parseFilterNumber(cond.numberFrom)
      if (cellNum === null || filterNum === null) return false
      return cellNum < filterNum
    }

    case "number_between": {
      const cellNum = parseNumericCellValue(cellValue)
      const fromNum = parseFilterNumber(cond.numberFrom)
      const toNum = parseFilterNumber(cond.numberTo)
      if (cellNum === null || fromNum === null || toNum === null) return false
      const lo = Math.min(fromNum, toNum)
      const hi = Math.max(fromNum, toNum)
      return cellNum >= lo && cellNum <= hi
    }

    case "date_after": {
      const cellMs = cellDateMs(cellValue)
      const filterMs = filterDateMs(cond.dateFrom)
      if (cellMs === null || filterMs === null) return false
      return cellMs > filterMs
    }

    case "date_before": {
      const cellMs = cellDateMs(cellValue)
      const filterMs = filterDateMs(cond.dateFrom)
      if (cellMs === null || filterMs === null) return false
      return cellMs < filterMs
    }

    case "date_between": {
      const cellMs = cellDateMs(cellValue)
      const fromMs = filterDateMs(cond.dateFrom)
      const toMs = filterDateMs(cond.dateTo)
      if (cellMs === null || fromMs === null || toMs === null) return false
      const lo = Math.min(fromMs, toMs)
      const hi = Math.max(fromMs, toMs)
      return cellMs >= lo && cellMs <= hi
    }

    default: {
      const _exhaustive: never = cond.operator
      return _exhaustive
    }
  }
}

export function applyColumnValueFilters(
  rows: TabularRow[],
  filters: ColumnValueFilterCondition[],
  columns: TabularColumn[],
): TabularRow[] {
  const columnById = new Map(columns.map((c) => [c.id, c]))
  const active = filters.filter((f) => isFilterConditionComplete(f, columnById.get(f.columnId)))

  if (active.length === 0) return rows

  return rows.filter((row) =>
    active.every((cond) => {
      const cellVal = row.cells[cond.columnId]?.cell_value ?? null
      return evaluateColumnValueFilter(cellVal, cond, columnById.get(cond.columnId))
    }),
  )
}

export function displayFilterValue(value: string): string {
  return value === EMPTY_VALUE_KEY ? EMPTY_VALUE_LABEL : value
}

export function formatFilterConditionSummary(
  cond: ColumnValueFilterCondition,
  column?: TabularColumn,
): string {
  const colLabel = column?.column_label ?? "Колонка"
  const op = getOperatorsForColumn(column).find((o) => o.value === cond.operator)?.label ?? cond.operator

  switch (cond.operator) {
    case "not_empty":
      return `${colLabel}: ${op}`
    case "contains":
      return `${colLabel}: ${op} «${cond.textQuery.trim()}»`
    case "date_after":
    case "date_before":
      return `${colLabel}: ${op} ${cond.dateFrom ?? ""}`
    case "date_between":
      return `${colLabel}: ${op} ${cond.dateFrom ?? ""} — ${cond.dateTo ?? ""}`
    case "number_greater_than":
    case "number_less_than":
      return `${colLabel}: ${op} ${cond.numberFrom ?? ""}`
    case "number_between":
      return `${colLabel}: ${op} ${cond.numberFrom ?? ""} — ${cond.numberTo ?? ""}`
    case "equals":
    case "not_equals":
      if (column && isDateColumn(column.column_type, column.column_label)) {
        return `${colLabel}: ${op} ${cond.dateFrom ?? ""}`
      }
      if (column && isNumericColumn(column.column_type, column.column_label)) {
        return `${colLabel}: ${op} ${cond.numberFrom ?? ""}`
      }
      return `${colLabel}: ${op} ${cond.selectedValues.map(displayFilterValue).join(", ")}`
    default: {
      const _exhaustive: never = cond.operator
      return _exhaustive
    }
  }
}
