interface CitationQuoteBannerProps {
  quote: string
  page?: number | null
  className?: string
}

export function CitationQuoteBanner({ quote, page, className = '' }: CitationQuoteBannerProps) {
  const trimmed = quote.trim()
  if (!trimmed) return null

  return (
    <div
      className={`shrink-0 border-b border-gray-200 bg-gray-50/90 px-4 py-3 ${className}`}
    >
      {page != null && !Number.isNaN(page) && (
        <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-gray-500">
          Стр. {page <= 0 ? 1 : page}
        </p>
      )}
      <p className="line-clamp-4 text-sm leading-relaxed text-gray-700">
        &ldquo;{trimmed}&rdquo;
      </p>
    </div>
  )
}
