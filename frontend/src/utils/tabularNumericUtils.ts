import type { TabularColumn } from '@/services/tabularReviewApi'
import { isExplicitTabularNaValue } from './tabularCellDisplay'

const MONEY_HEADER_RE = /(сумм|amount|дебет|кредит|баланс)/i
const NUMBER_HEADER_RE = /(колич|count|qty|числ)/i

export function isNumericColumn(
  columnType: string | undefined,
  columnLabel: string | undefined,
): boolean {
  const type = (columnType || '').toLowerCase()
  if (type === 'currency' || type === 'number') return true
  const label = (columnLabel || '').trim()
  if (!label) return false
  return MONEY_HEADER_RE.test(label) || NUMBER_HEADER_RE.test(label)
}

/** Parses RU-formatted amounts like «1 234 567,89» into a number. */
export function parseNumericCellValue(value: string | null | undefined): number | null {
  const raw = (value ?? '').trim()
  if (!raw || raw === '—' || raw === '-' || isExplicitTabularNaValue(raw)) {
    return null
  }
  const match = raw.replace(/\u2212/g, '-').match(/[-+]?\s*[\d\s]+(?:[.,]\d+)?/)
  if (!match) return null
  const normalized = match[0].replace(/\s/g, '').replace(',', '.')
  const parsed = Number.parseFloat(normalized)
  return Number.isFinite(parsed) ? parsed : null
}

export function parseFilterNumber(value: string | null | undefined): number | null {
  return parseNumericCellValue(value)
}

export function columnTypeForOperationsHeader(header: string): TabularColumn['column_type'] {
  const label = header.trim()
  if (!label) return 'text'
  if (/(дата|date)/i.test(label)) return 'date'
  if (isNumericColumn(undefined, label)) return 'currency'
  return 'text'
}
