import { useState } from 'react'
import { Users } from 'lucide-react'
import { MikePageHeader } from '@/components/TabularReview/mike/MikePageHeader'
import { CaseParticipantsModal } from '@/components/CaseOverview/CaseParticipantsModal'

interface CaseOverviewPageHeaderProps {
  loading: boolean
  caseId?: string
  caseTitle?: string | null
  documentCountLabel: string
  onNavigateCases: () => void
  showParticipants?: boolean
}

export function CaseOverviewPageHeader({
  loading,
  caseId,
  caseTitle,
  documentCountLabel,
  onNavigateCases,
  showParticipants = true,
}: CaseOverviewPageHeaderProps) {
  const [participantsOpen, setParticipantsOpen] = useState(false)

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
        actions={
          showParticipants && caseId
            ? [
                {
                  label: 'Участники',
                  icon: <Users className="h-3.5 w-3.5" />,
                  onClick: () => setParticipantsOpen(true),
                },
              ]
            : undefined
        }
      />
      {!loading && (
        <p className="px-4 pb-1 text-xs text-gray-500 md:px-10">{documentCountLabel}</p>
      )}
      {caseId ? (
        <CaseParticipantsModal
          open={participantsOpen}
          caseId={caseId}
          onClose={() => setParticipantsOpen(false)}
        />
      ) : null}
    </div>
  )
}
