import { cn } from '@/lib/utils'
import { ddDocTypeShortLabel, ddNeedsReview } from '@/lib/ddDocTypes'

export type DdDocTypeBadgeProps = {
  docType?: string | null
  confidence?: number | null
  source?: string | null
  needsReview?: boolean | null
  shortLabel?: string | null
  className?: string
  /** Compact table cell */
  size?: 'sm' | 'md'
}

/**
 * Library badge for DD taxonomy. Yellow outline = lawyer should confirm.
 */
export function DdDocTypeBadge({
  docType,
  confidence,
  source,
  needsReview,
  shortLabel,
  className,
  size = 'sm',
}: DdDocTypeBadgeProps) {
  const label = shortLabel || ddDocTypeShortLabel(docType)
  const review = ddNeedsReview({
    docType,
    confidence,
    source,
    needsReviewFlag: needsReview,
  })

  return (
    <span
      title={
        review
          ? `${label} — проверьте тип`
          : source === 'user'
            ? `${label} (задан вручную)`
            : label
      }
      className={cn(
        'inline-flex max-w-full items-center truncate rounded-md border px-1.5 font-medium',
        size === 'sm' ? 'h-5 text-[11px] leading-none' : 'h-6 text-xs',
        review
          ? 'border-amber-300 bg-amber-50 text-amber-900'
          : 'border-gray-200 bg-gray-50 text-gray-700',
        className,
      )}
    >
      {label}
    </span>
  )
}
