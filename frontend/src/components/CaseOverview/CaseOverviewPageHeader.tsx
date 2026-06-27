import { MikePageHeader } from '@/components/TabularReview/mike/MikePageHeader'

interface CaseOverviewPageHeaderProps {
  loading: boolean
  caseTitle?: string | null
  documentCountLabel: string
  onNavigateCases: () => void
}

export function CaseOverviewPageHeader({
  loading,
  caseTitle,
  documentCountLabel,
  onNavigateCases,
}: CaseOverviewPageHeaderProps) {
  return (
    <div className="shrink-0">
      <MikePageHeader
        loading={loading}
        breadcrumbs={[
          { label: 'Дела', onClick: onNavigateCases },
          {
            label: caseTitle || 'Без названия',
            loading,
            skeletonClassName: 'w-48',
          },
        ]}
      />
      {!loading && (
        <p className="px-4 pb-1 text-xs text-gray-500 md:px-10">{documentCountLabel}</p>
      )}
    </div>
  )
}
