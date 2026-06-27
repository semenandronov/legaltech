import type { TabularColumn } from '@/services/tabularReviewApi'

/** Mike TAG_COLORS — Tailwind как в willchen96/mike pillUtils. */
export const MIKE_TAG_COLORS = [
  'bg-blue-100 text-blue-700',
  'bg-violet-100 text-violet-700',
  'bg-pink-100 text-pink-700',
  'bg-orange-100 text-orange-700',
  'bg-teal-100 text-teal-700',
  'bg-amber-100 text-amber-700',
  'bg-indigo-100 text-indigo-700',
  'bg-rose-100 text-rose-700',
] as const

const MIKE_CURRENCY_COLORS: Record<string, string> = {
  USD: 'bg-green-100 text-green-700',
  EUR: 'bg-blue-100 text-blue-700',
  GBP: 'bg-purple-100 text-purple-700',
  JPY: 'bg-red-100 text-red-700',
  CHF: 'bg-orange-100 text-orange-700',
  AUD: 'bg-cyan-100 text-cyan-700',
  CAD: 'bg-teal-100 text-teal-700',
  SGD: 'bg-pink-100 text-pink-700',
  HKD: 'bg-rose-100 text-rose-700',
  NZD: 'bg-lime-100 text-lime-700',
  CNY: 'bg-amber-100 text-amber-700',
  RUB: 'bg-pink-100 text-pink-700',
}

/** Mike getPillClass — адаптирован под TabularColumn. */
export function getMikePillClass(content: string, column?: Pick<TabularColumn, 'column_type' | 'column_config'>): string {
  if (column?.column_type === 'yes_no') {
    const lower = content.toLowerCase()
    if (lower === 'yes' || lower === 'да') return 'bg-green-100 text-green-700'
    if (lower === 'no' || lower === 'нет') return 'bg-red-100 text-red-700'
    return 'bg-gray-100 text-gray-700'
  }
  if (column?.column_type === 'currency') {
    return MIKE_CURRENCY_COLORS[content.toUpperCase()] ?? 'bg-slate-100 text-slate-700'
  }
  if (column?.column_type === 'tag') {
    const tags = column.column_config?.options?.map((opt) => opt.label) ?? []
    if (tags.length) {
      const idx = tags.findIndex((t) => t.toLowerCase() === content.toLowerCase())
      if (idx >= 0) return MIKE_TAG_COLORS[idx % MIKE_TAG_COLORS.length]!
    }
  }
  return 'bg-gray-100 text-gray-700'
}
