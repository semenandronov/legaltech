"use client"

import { useRef } from 'react'
import { Download, Filter, HelpCircle, MessageSquare, X } from 'lucide-react'
import { MikeHeaderActionsMenu } from '@/components/TabularReview/mike/MikeHeaderActionsMenu'
import { MikePageHeader } from '@/components/TabularReview/mike/MikePageHeader'
import type { MikePageHeaderActionGroup, MikePageHeaderBreadcrumb } from '@/components/TabularReview/mike/MikePageHeader'

export interface OperationsHeaderProps {
  caseName: string
  statementName: string
  operationCount: number
  showChat: boolean
  rowSearch: string
  activeFilterCount?: number
  onRowSearchChange: (value: string) => void
  onNavigateCases: () => void
  onNavigateCase: () => void
  onToggleChat: () => void
  onExport: () => void
  onOpenHelp: () => void
  onOpenFilter: (anchorEl: HTMLElement) => void
}

export function OperationsHeader({
  caseName,
  statementName,
  operationCount,
  showChat,
  rowSearch,
  activeFilterCount = 0,
  onRowSearchChange,
  onNavigateCases,
  onNavigateCase,
  onToggleChat,
  onExport,
  onOpenHelp,
  onOpenFilter,
}: OperationsHeaderProps) {
  const filterBtnRef = useRef<HTMLButtonElement>(null)

  const breadcrumbs: MikePageHeaderBreadcrumb[] = [
    { label: 'Дела', onClick: onNavigateCases, title: 'К списку дел' },
    { label: caseName || '...', onClick: onNavigateCase, title: 'К делу' },
    {
      label: statementName || 'Операции',
      title: `${operationCount} операций`,
    },
  ]

  const overflowItems = [
    { label: 'Экспорт', icon: Download, onSelect: onExport },
    { label: 'Справка', icon: HelpCircle, onSelect: onOpenHelp },
  ]

  const actionGroups: MikePageHeaderActionGroup[] = [
    [
      {
        type: 'search',
        value: rowSearch,
        onChange: onRowSearchChange,
        placeholder: 'Поиск операций…',
      },
      {
        type: 'custom',
        render: <MikeHeaderActionsMenu items={overflowItems} title="Дополнительные действия" />,
      },
    ],
    [
      {
        type: 'custom',
        render: (
          <button
            ref={filterBtnRef}
            type="button"
            title="Фильтры"
            aria-label="Фильтры"
            aria-pressed={activeFilterCount > 0}
            onClick={() => {
              if (filterBtnRef.current) onOpenFilter(filterBtnRef.current)
            }}
            className="flex h-7 items-center justify-center gap-1.5 rounded-full px-0 text-sm text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 active:bg-gray-100 sm:w-auto sm:px-3 w-7"
          >
            <Filter className="h-4 w-4" />
            <span className="hidden sm:inline">Фильтры</span>
            {activeFilterCount > 0 ? (
              <span className="inline-flex min-w-[1.1rem] items-center justify-center rounded-full bg-gray-900 px-1.5 text-[10px] font-medium leading-4 text-white">
                {activeFilterCount}
              </span>
            ) : null}
          </button>
        ),
      },
    ],
    [
      {
        onClick: onToggleChat,
        title: showChat ? 'Закрыть ассистента' : 'Открыть ассистента',
        icon: showChat ? <X className="h-4 w-4" /> : <MessageSquare className="h-4 w-4" />,
        label: <span className="hidden sm:inline">Ассистент</span>,
      },
    ],
  ]

  return <MikePageHeader breadcrumbs={breadcrumbs} actionGroups={actionGroups} />
}
