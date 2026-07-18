export type BankruptcyPeriodId = '1m' | '6m' | '1y' | '3y'

export type OperationsViewMode = 'operations' | 'counterparties'

export interface BankruptcySuspicionWindow {
  periodId: BankruptcyPeriodId
  label: string
  dateFrom: string
  dateTo: string
}

export const BANKRUPTCY_PERIOD_OPTIONS: ReadonlyArray<{
  id: BankruptcyPeriodId
  label: string
  months: number
}> = [
  { id: '1m', label: '1 месяц', months: 1 },
  { id: '6m', label: '6 месяцев', months: 6 },
  { id: '1y', label: '1 год', months: 12 },
  { id: '3y', label: '3 года', months: 36 },
]

function pad2(value: number): string {
  return String(value).padStart(2, '0')
}

export function formatIsoDate(value: Date): string {
  return `${value.getFullYear()}-${pad2(value.getMonth() + 1)}-${pad2(value.getDate())}`
}

export function parseIsoDate(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim())
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const date = new Date(year, month - 1, day)
  if (
    date.getFullYear() !== year
    || date.getMonth() !== month - 1
    || date.getDate() !== day
  ) {
    return null
  }
  return date
}

function subtractMonths(date: Date, months: number): Date {
  const year = date.getFullYear()
  const monthIndex = date.getMonth() - months
  const day = date.getDate()
  const result = new Date(year, monthIndex, day)
  if (result.getDate() !== day) {
    return new Date(result.getFullYear(), result.getMonth() + 1, 0)
  }
  return result
}

export function bankruptcyPeriodWindow(
  petitionDate: Date,
  periodId: BankruptcyPeriodId,
): BankruptcySuspicionWindow {
  const option = BANKRUPTCY_PERIOD_OPTIONS.find((item) => item.id === periodId)
  if (!option) {
    throw new Error(`Unknown bankruptcy period: ${periodId}`)
  }
  const dateFrom = subtractMonths(petitionDate, option.months)
  return {
    periodId,
    label: option.label,
    dateFrom: formatIsoDate(dateFrom),
    dateTo: formatIsoDate(petitionDate),
  }
}

export function resolveActivePeriodRange(
  petitionDate: string | null | undefined,
  activePeriod: BankruptcyPeriodId | null | undefined,
): { dateFrom?: string; dateTo?: string } {
  if (!petitionDate || !activePeriod) return {}
  const parsed = parseIsoDate(petitionDate)
  if (!parsed) return {}
  const window = bankruptcyPeriodWindow(parsed, activePeriod)
  return { dateFrom: window.dateFrom, dateTo: window.dateTo }
}

export function parseBankruptcyPeriodId(value: string | null | undefined): BankruptcyPeriodId | null {
  const normalized = (value || '').trim().toLowerCase()
  if (normalized === '1m' || normalized === '6m' || normalized === '1y' || normalized === '3y') {
    return normalized
  }
  return null
}
