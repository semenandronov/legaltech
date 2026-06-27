import type { ReactNode } from 'react'

interface MikeTableToolbarItem<T extends string = string> {
  id: T
  label: string
}

interface MikeTableToolbarProps<T extends string = string> {
  leading?: ReactNode
  items?: MikeTableToolbarItem<T>[]
  active?: T
  onChange?: (id: T) => void
  actions?: ReactNode
}

/** Mike TableToolbar — чистый UI. */
export function MikeTableToolbar<T extends string = string>({
  leading,
  items = [],
  active,
  onChange,
  actions,
}: MikeTableToolbarProps<T>) {
  const hasItems = items.length > 0

  return (
    <div className="flex h-10 items-center border-b border-gray-200 px-4 md:px-10">
      {leading}
      {hasItems && (
        <div className="flex items-center gap-4">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onChange?.(item.id)}
              className={`text-xs transition-colors ${
                active === item.id
                  ? 'font-medium text-gray-700'
                  : 'font-normal text-gray-500 hover:text-gray-700'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
      {actions && <div className="ml-auto flex items-center gap-5">{actions}</div>}
    </div>
  )
}
