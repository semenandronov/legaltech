import type { TabularColumn } from '@/services/tabularReviewApi'

export type PillSegment =
  | { type: 'text'; content: string }
  | { type: 'pill'; content: string }

export const TAG_PILL_CLASSES = [
  'ws-tabular-pill--blue',
  'ws-tabular-pill--violet',
  'ws-tabular-pill--pink',
  'ws-tabular-pill--orange',
  'ws-tabular-pill--teal',
  'ws-tabular-pill--amber',
  'ws-tabular-pill--indigo',
  'ws-tabular-pill--rose',
] as const

const CURRENCY_PILL_CLASSES: Record<string, string> = {
  USD: 'ws-tabular-pill--green',
  EUR: 'ws-tabular-pill--blue',
  GBP: 'ws-tabular-pill--violet',
  JPY: 'ws-tabular-pill--red',
  CHF: 'ws-tabular-pill--orange',
  AUD: 'ws-tabular-pill--cyan',
  CAD: 'ws-tabular-pill--teal',
  RUB: 'ws-tabular-pill--pink',
}

export function getTabularPillClass(content: string, column?: TabularColumn): string {
  const columnType = column?.column_type

  if (columnType === 'yes_no') {
    // No green/red semantics — triage color is set by the user via cell flags.
    return 'ws-tabular-pill--neutral'
  }

  if (columnType === 'currency') {
    return CURRENCY_PILL_CLASSES[content.toUpperCase()] ?? 'ws-tabular-pill--neutral'
  }

  if (columnType === 'tag') {
    const options = column?.column_config?.options ?? []
    const idx = options.findIndex(
      (opt) => opt.label.toLowerCase() === content.toLowerCase(),
    )
    if (idx >= 0) return TAG_PILL_CLASSES[idx % TAG_PILL_CLASSES.length]!
  }

  return 'ws-tabular-pill--neutral'
}

/** Split text on [[...]] pill markers, preserving surrounding text. */
export function parseTabularPills(text: string): PillSegment[] {
  const segments: PillSegment[] = []
  const regex = /\[\[([^\]]+)\]\]/g
  let lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: 'text', content: text.slice(lastIndex, match.index) })
    }
    segments.push({ type: 'pill', content: match[1] })
    lastIndex = regex.lastIndex
  }
  if (lastIndex < text.length) {
    segments.push({ type: 'text', content: text.slice(lastIndex) })
  }
  return segments
}

export function shouldRenderAsPill(column?: TabularColumn, value?: string): boolean {
  if (!value || value === '-' || value === '—') return false
  const type = column?.column_type
  // yes_no is plain text — color comes only from user cell flags
  return type === 'tag' || type === 'currency'
}
