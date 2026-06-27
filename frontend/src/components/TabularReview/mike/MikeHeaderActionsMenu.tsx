"use client"

import { MoreHorizontal, type LucideIcon } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/UI/dropdown-menu'
import { cn } from '@/lib/utils'

export type MikeHeaderActionsMenuItem = {
  label: string
  icon?: LucideIcon
  onSelect: () => void
  disabled?: boolean
  variant?: 'default' | 'danger'
}

interface MikeHeaderActionsMenuProps {
  items: MikeHeaderActionsMenuItem[]
  title?: string
}

/** Mike HeaderActionsMenu — чистый UI. */
export function MikeHeaderActionsMenu({
  items,
  title = 'Действия',
}: MikeHeaderActionsMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            'inline-flex h-7 w-7 items-center justify-center rounded-full text-gray-600 transition-all',
            'hover:bg-gray-100 hover:text-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-300',
          )}
          aria-label={title}
          title={title}
        >
          <MoreHorizontal className="h-4 w-4" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="z-[160] w-48 bg-white">
        {items.map((item) => {
          const Icon = item.icon
          return (
            <DropdownMenuItem
              key={item.label}
              disabled={item.disabled}
              onSelect={item.onSelect}
              className={cn(
                'cursor-pointer text-xs gap-2',
                item.variant === 'danger' && 'text-red-600 focus:bg-red-50 focus:text-red-700',
              )}
            >
              {Icon && <Icon className="h-3.5 w-3.5" />}
              {item.label}
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
