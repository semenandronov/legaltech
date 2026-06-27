import { Plus } from 'lucide-react'
import { MikePageHeader } from '@/components/TabularReview/mike/MikePageHeader'

interface GlobalAssistantPageHeaderProps {
  onNewChat: () => void
}

export function GlobalAssistantPageHeader({ onNewChat }: GlobalAssistantPageHeaderProps) {
  return (
    <MikePageHeader
      breadcrumbs={[{ label: 'Ассистент' }]}
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
