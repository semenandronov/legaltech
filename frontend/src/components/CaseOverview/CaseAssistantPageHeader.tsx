import { Plus } from 'lucide-react'
import { MikePageHeader } from '@/components/TabularReview/mike/MikePageHeader'

interface CaseAssistantPageHeaderProps {
  loading?: boolean
  caseTitle?: string
  onNavigateCases: () => void
  onNavigateCase: () => void
  onNewChat: () => void
}

export function CaseAssistantPageHeader({
  loading = false,
  caseTitle,
  onNavigateCases,
  onNavigateCase,
  onNewChat,
}: CaseAssistantPageHeaderProps) {
  return (
    <MikePageHeader
      loading={loading}
      breadcrumbs={[
        { label: 'Дела', onClick: onNavigateCases },
        {
          label: caseTitle || 'Без названия',
          onClick: onNavigateCase,
          loading: loading && !caseTitle,
          skeletonClassName: 'w-32',
        },
        { label: 'Ассистент' },
      ]}
      actionGroups={[
        {
          actions: [
            {
              type: 'button',
              icon: <Plus className="h-4 w-4" />,
              label: <span className="hidden sm:inline">Новый чат</span>,
              onClick: onNewChat,
              title: 'Новый чат',
            },
          ],
        },
      ]}
    />
  )
}
