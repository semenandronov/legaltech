import { MikePageHeader } from '@/components/TabularReview/mike/MikePageHeader'

interface NewCasePageHeaderProps {
  onNavigateCases: () => void
}

export function NewCasePageHeader({ onNavigateCases }: NewCasePageHeaderProps) {
  return (
    <MikePageHeader
      shrink
      breadcrumbs={[
        { label: 'Дела', onClick: onNavigateCases },
        { label: 'Новое дело' },
      ]}
    />
  )
}
