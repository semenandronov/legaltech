import { cn } from '@/lib/utils'
import type { DdTaxonomyType } from '@/lib/ddDocTypes'

export type DdDocTypeFilterBarProps = {
  types: DdTaxonomyType[]
  counts: Record<string, number>
  selected: string | null
  onSelect: (docType: string | null) => void
  needsReviewCount?: number
  showNeedsReview?: boolean
  needsReviewSelected?: boolean
  onToggleNeedsReview?: () => void
}

/**
 * Chip filters for the case document library (DD taxonomy).
 */
export function DdDocTypeFilterBar({
  types,
  counts,
  selected,
  onSelect,
  needsReviewCount = 0,
  showNeedsReview = true,
  needsReviewSelected = false,
  onToggleNeedsReview,
}: DdDocTypeFilterBarProps) {
  const visible = types.filter((t) => (counts[t.id] ?? 0) > 0)
  if (visible.length === 0 && needsReviewCount === 0) return null

  return (
    <div className="mb-3 flex flex-wrap items-center gap-1.5">
      <button
        type="button"
        onClick={() => onSelect(null)}
        className={cn(
          'rounded-full border px-2.5 py-1 text-xs transition-colors',
          selected == null && !needsReviewSelected
            ? 'border-gray-900 bg-gray-900 text-white'
            : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300',
        )}
      >
        Все
      </button>
      {showNeedsReview && needsReviewCount > 0 && onToggleNeedsReview && (
        <button
          type="button"
          onClick={onToggleNeedsReview}
          className={cn(
            'rounded-full border px-2.5 py-1 text-xs transition-colors',
            needsReviewSelected
              ? 'border-amber-600 bg-amber-600 text-white'
              : 'border-amber-200 bg-amber-50 text-amber-900 hover:border-amber-300',
          )}
        >
          Проверить ({needsReviewCount})
        </button>
      )}
      {visible.map((t) => {
        const count = counts[t.id] ?? 0
        const active = selected === t.id && !needsReviewSelected
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => onSelect(active ? null : t.id)}
            className={cn(
              'rounded-full border px-2.5 py-1 text-xs transition-colors',
              active
                ? 'border-gray-900 bg-gray-900 text-white'
                : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300',
            )}
          >
            {t.short_label} ({count})
          </button>
        )
      })}
    </div>
  )
}
