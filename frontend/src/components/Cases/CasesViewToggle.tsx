import { LayoutGrid, List } from 'lucide-react'
import { cn } from '@/lib/utils'

export type CasesViewMode = 'list' | 'grid'

interface CasesViewToggleProps {
  value: CasesViewMode
  onChange: (mode: CasesViewMode) => void
}

export function CasesViewToggle({ value, onChange }: CasesViewToggleProps) {
  return (
    <div
      className="flex items-center gap-0.5 rounded-full border border-gray-200 bg-white p-0.5"
      role="group"
      aria-label="Вид отображения"
    >
      <button
        type="button"
        onClick={() => onChange('grid')}
        title="Сетка"
        aria-label="Сетка"
        aria-pressed={value === 'grid'}
        className={cn(
          'flex h-7 w-7 items-center justify-center rounded-full transition-colors',
          value === 'grid'
            ? 'bg-gray-100 text-gray-900'
            : 'text-gray-400 hover:text-gray-600',
        )}
      >
        <LayoutGrid className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        onClick={() => onChange('list')}
        title="Список"
        aria-label="Список"
        aria-pressed={value === 'list'}
        className={cn(
          'flex h-7 w-7 items-center justify-center rounded-full transition-colors',
          value === 'list'
            ? 'bg-gray-100 text-gray-900'
            : 'text-gray-400 hover:text-gray-600',
        )}
      >
        <List className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
