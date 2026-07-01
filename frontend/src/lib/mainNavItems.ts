import { Clock, FolderOpen, MessageSquare } from 'lucide-react'
import { isProductFeatureEnabled } from '@/lib/productFeatures'

export type MainNavItem = {
  id: string
  label: string
  icon: typeof FolderOpen
  path: string
}

/** Главное меню сайдбара: без глобального ассистента по умолчанию — только Дела и История. */
export function buildMainNavItems(): MainNavItem[] {
  const items: MainNavItem[] = [
    { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
  ]
  if (isProductFeatureEnabled('globalAssistant')) {
    items.push({ id: 'assistant', label: 'Ассистент', icon: MessageSquare, path: '/assistant' })
  }
  items.push({ id: 'history', label: 'История', icon: Clock, path: '/history' })
  return items
}
