import { BookOpen, FileEdit, MessageSquare, Scissors, type LucideIcon } from 'lucide-react'
import { productFeatures } from '@/lib/productFeatures'
import { canAccessInternalDevTools } from '@/utils/internalDevToolsAccess'

export interface CaseNavItem {
  id: string
  label: string
  icon: LucideIcon
  path: string
}

/** Боковое меню внутри дела (чат, редактор, playbooks, chunk-lab). */
export function buildCaseNavItems(caseId: string, userEmail?: string | null): CaseNavItem[] {
  const items: CaseNavItem[] = [
    {
      id: 'chat',
      label: 'Ассистент',
      icon: MessageSquare,
      path: `/cases/${caseId}/chat`,
    },
  ]

  if (productFeatures.chunkLab && canAccessInternalDevTools(userEmail)) {
    items.push({
      id: 'chunk-lab',
      label: 'Чанки',
      icon: Scissors,
      path: `/cases/${caseId}/chunk-lab`,
    })
  }

  if (productFeatures.editor) {
    items.push({
      id: 'editor',
      label: 'Редактор',
      icon: FileEdit,
      path: `/cases/${caseId}/editor`,
    })
  }

  if (productFeatures.playbooks) {
    items.push({
      id: 'playbooks',
      label: 'Playbooks',
      icon: BookOpen,
      path: `/cases/${caseId}/playbooks`,
    })
  }

  return items
}
