/**
 * DD document taxonomy v1 — mirrors backend/app/services/dd_document_taxonomy.py
 * Prefer labels from GET /api/cases/dd-doc-taxonomy when available.
 */

export const DD_DOC_TYPES = [
  'lease_commercial',
  'supply',
  'services',
  'works',
  'contract_other',
  'addendum',
  'appendix_spec',
  'payment_order',
  'bank_statement',
  'litigation',
  'correspondence',
  'other',
  'unknown',
] as const

export type DdDocType = (typeof DD_DOC_TYPES)[number]

export const DD_DOC_TYPE_SHORT_LABELS: Record<DdDocType, string> = {
  lease_commercial: 'Аренда',
  supply: 'Поставка',
  services: 'Услуги',
  works: 'Подряд',
  contract_other: 'Договор',
  addendum: 'ДС',
  appendix_spec: 'Приложение',
  payment_order: 'Платёжка',
  bank_statement: 'Выписка',
  litigation: 'Суд',
  correspondence: 'Переписка',
  other: 'Прочее',
  unknown: 'Не определено',
}

export const DD_DOC_TYPE_LABELS: Record<DdDocType, string> = {
  lease_commercial: 'Договор / документ по коммерческой аренде',
  supply: 'Договор поставки / документ по поставке',
  services: 'Договор оказания услуг',
  works: 'Договор подряда / выполнения работ',
  contract_other: 'Договор (прочее / тема не уточнена)',
  addendum: 'Дополнительное соглашение',
  appendix_spec: 'Приложение / спецификация',
  payment_order: 'Платёжное поручение',
  bank_statement: 'Банковская выписка / реестр операций',
  litigation: 'Судебный / процессуальный документ',
  correspondence: 'Письмо / претензия / уведомление',
  other: 'Прочее',
  unknown: 'Не определено',
}

export const DD_NEEDS_REVIEW_CONFIDENCE = 0.55

export type DdTaxonomyType = {
  id: string
  label: string
  short_label: string
}

export type DdTaxonomyResponse = {
  version: string
  needs_review_confidence: number
  types: DdTaxonomyType[]
}

export function isDdDocType(value: string | null | undefined): value is DdDocType {
  return Boolean(value && (DD_DOC_TYPES as readonly string[]).includes(value))
}

export function ddDocTypeShortLabel(
  docType?: string | null,
  taxonomy?: DdTaxonomyType[] | null,
): string {
  const key = (docType || 'unknown').trim() || 'unknown'
  const fromApi = taxonomy?.find((t) => t.id === key)?.short_label
  if (fromApi) return fromApi
  if (isDdDocType(key)) return DD_DOC_TYPE_SHORT_LABELS[key]
  return DD_DOC_TYPE_SHORT_LABELS.unknown
}

export function ddDocTypeLabel(
  docType?: string | null,
  taxonomy?: DdTaxonomyType[] | null,
): string {
  const key = (docType || 'unknown').trim() || 'unknown'
  const fromApi = taxonomy?.find((t) => t.id === key)?.label
  if (fromApi) return fromApi
  if (isDdDocType(key)) return DD_DOC_TYPE_LABELS[key]
  return DD_DOC_TYPE_LABELS.unknown
}

export function ddNeedsReview(params: {
  docType?: string | null
  confidence?: number | null
  source?: string | null
  needsReviewFlag?: boolean | null
}): boolean {
  if (typeof params.needsReviewFlag === 'boolean') return params.needsReviewFlag
  if ((params.source || '').toLowerCase() === 'user') return false
  const t = (params.docType || 'unknown').trim() || 'unknown'
  if (t === 'unknown' || t === 'other') return true
  if (params.confidence == null) return true
  return params.confidence < DD_NEEDS_REVIEW_CONFIDENCE
}
