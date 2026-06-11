/** Парсинг дат из ячеек таблицы (ISO, DD.MM.YYYY и др.) → timestamp ms или null */
export function parseTabularDateMs(raw: string | null | undefined): number | null {
  const str = (raw ?? "").trim()
  if (!str || str === "-" || str === "—" || str.toUpperCase() === "N/A") {
    return null
  }

  const dotMatch = str.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/)
  if (dotMatch) {
    return new Date(
      parseInt(dotMatch[3], 10),
      parseInt(dotMatch[2], 10) - 1,
      parseInt(dotMatch[1], 10),
    ).getTime()
  }

  const isoMatch = str.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (isoMatch) {
    return new Date(
      parseInt(isoMatch[1], 10),
      parseInt(isoMatch[2], 10) - 1,
      parseInt(isoMatch[3], 10),
    ).getTime()
  }

  const anyMatch = str.match(/(\d{1,2})[\.\/\-](\d{1,2})[\.\/\-](\d{2,4})/)
  if (anyMatch) {
    const year =
      anyMatch[3].length === 2
        ? 2000 + parseInt(anyMatch[3], 10)
        : parseInt(anyMatch[3], 10)
    return new Date(
      year,
      parseInt(anyMatch[2], 10) - 1,
      parseInt(anyMatch[1], 10),
    ).getTime()
  }

  const parsed = Date.parse(str)
  return Number.isNaN(parsed) ? null : parsed
}

export function isDateColumn(columnType: string, columnLabel: string): boolean {
  if (columnType === "date") return true
  const label = columnLabel.toLowerCase()
  return label.includes("дат") || label.includes("date") || label.includes("срок")
}

export function isEmptySortValue(value: string | null | undefined): boolean {
  const str = (value ?? "").trim()
  if (!str) return true
  const upper = str.toUpperCase()
  return str === "-" || str === "—" || upper === "N/A"
}

/** Сравнение значений ячеек для сортировки (−1 / 0 / 1), без учёта направления */
export function compareTabularCellValues(
  valueA: string,
  valueB: string,
  columnType: string,
  columnLabel: string,
): number {
  if (isDateColumn(columnType, columnLabel)) {
    const dateA = parseTabularDateMs(valueA)
    const dateB = parseTabularDateMs(valueB)
    if (dateA !== null && dateB !== null) return dateA - dateB
    if (dateA !== null) return -1
    if (dateB !== null) return 1
  }

  if (columnType === "number" || columnType === "currency") {
    const numA = parseFloat(valueA.replace(/[^\d.,-]/g, "").replace(",", "."))
    const numB = parseFloat(valueB.replace(/[^\d.,-]/g, "").replace(",", "."))
    if (!Number.isNaN(numA) && !Number.isNaN(numB)) return numA - numB
  }

  return valueA.localeCompare(valueB, "ru")
}

/**
 * Сравнение с учётом направления сортировки TanStack Table.
 * Пустые ячейки всегда внизу (и при asc, и при desc).
 */
export function compareTabularCellValuesForSort(
  valueA: string,
  valueB: string,
  columnType: string,
  columnLabel: string,
  sortDesc: boolean,
): number {
  const emptyA = isEmptySortValue(valueA)
  const emptyB = isEmptySortValue(valueB)
  if (emptyA && emptyB) return 0
  if (emptyA) return sortDesc ? -1 : 1
  if (emptyB) return sortDesc ? 1 : -1

  return compareTabularCellValues(valueA, valueB, columnType, columnLabel)
}
