"use client"

import type { ReactNode } from 'react'
import {
  Download,
  Edit2,
  HelpCircle,
  MessageSquare,
  Users,
  X,
} from 'lucide-react'
import { MikeBreadcrumbRename } from './MikeBreadcrumbRename'
import { MikeHeaderActionsMenu } from './MikeHeaderActionsMenu'
import type { MikePageHeaderActionGroup, MikePageHeaderBreadcrumb, MikePageHeaderProps } from './MikePageHeader'

export interface TabularHeaderControllerInput {
  caseName: string
  reviewName: string
  processing: boolean
  showTableChat: boolean
  isEditingName: boolean
  editNameValue: string
  documentSearch: string
  onDocumentSearchChange: (value: string) => void
  onNavigateCases: () => void
  onNavigateCase: () => void
  onStartRename: () => void
  onSaveRename: () => void
  onCancelRename: () => void
  onEditNameChange: (value: string) => void
  onToggleChat: () => void
  onExport: () => void
  onOpenHelp: () => void
  onOpenParticipants?: () => void
  /** Visible Filters control (separate pill), built by TabularReviewHeader. */
  filterAction?: ReactNode
}

/** Адаптер: наша бизнес-логика → props Mike PageHeader. */
export function buildMikeTabularHeaderProps(
  input: TabularHeaderControllerInput,
): MikePageHeaderProps {
  const {
    caseName,
    reviewName,
    processing,
    showTableChat,
    isEditingName,
    editNameValue,
    documentSearch,
    onDocumentSearchChange,
    onNavigateCases,
    onNavigateCase,
    onStartRename,
    onSaveRename,
    onCancelRename,
    onEditNameChange,
    onToggleChat,
    onExport,
    onOpenHelp,
    onOpenParticipants,
    filterAction,
  } = input

  const breadcrumbs: MikePageHeaderBreadcrumb[] = [
    {
      label: 'Дела',
      onClick: onNavigateCases,
      title: 'К списку дел',
    },
    {
      label: caseName || '...',
      onClick: onNavigateCase,
      title: 'К делу',
    },
    isEditingName
      ? {
          label: (
            <MikeBreadcrumbRename
              value={editNameValue}
              onChange={onEditNameChange}
              onSave={onSaveRename}
              onCancel={onCancelRename}
            />
          ),
          cursor: 'text',
        }
      : {
          label: reviewName,
        },
  ]

  const overflowItems = [
    ...(onOpenParticipants
      ? [
          {
            label: 'Участники',
            icon: Users,
            onSelect: onOpenParticipants,
          },
        ]
      : []),
    {
      label: 'Переименовать',
      icon: Edit2,
      onSelect: onStartRename,
    },
    {
      label: 'Экспорт',
      icon: Download,
      onSelect: onExport,
    },
    {
      label: 'Справка',
      icon: HelpCircle,
      onSelect: onOpenHelp,
    },
  ]

  const actionGroups: MikePageHeaderActionGroup[] = [
    [
      {
        type: 'search',
        value: documentSearch,
        onChange: onDocumentSearchChange,
        placeholder: 'Поиск документов…',
      },
      {
        type: 'custom',
        render: <MikeHeaderActionsMenu items={overflowItems} title="Дополнительные действия" />,
      },
    ],
  ]

  if (filterAction) {
    actionGroups.push([
      {
        type: 'custom',
        render: filterAction,
      },
    ])
  }

  actionGroups.push([
    {
      onClick: onToggleChat,
      disabled: processing,
      title: showTableChat ? 'Закрыть ассистента' : 'Открыть ассистента',
      icon: showTableChat ? <X className="h-4 w-4" /> : <MessageSquare className="h-4 w-4" />,
      label: <span className="hidden sm:inline">Ассистент</span>,
    },
  ])

  return {
    shrink: true,
    className: 'gap-4',
    breadcrumbs,
    actionGroups,
    loading: processing,
  }
}
