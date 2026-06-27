import {
  useEffect,
  useState,
  type HTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from 'react'
import { cn } from '@/lib/utils'
import {
  CLOSE_ROW_ACTIONS_EVENT,
  closeRowActionMenus,
} from './MikeRowActions'
import {
  STICKY_CELL_BG,
  TABLE_CHECKBOX_CLASS,
} from './mikeTablePrimitives'

export const TABLE_PRIMARY_CELL_WIDTH_CLASS =
  'w-[248px] sm:w-[292px] md:w-[332px] shrink-0'

const GLASS_DROPDOWN =
  'rounded-xl border border-white/70 bg-white/90 shadow-[0_8px_24px_rgba(15,23,42,0.08)] backdrop-blur-2xl'

type DivProps = HTMLAttributes<HTMLDivElement>

export function MikeTableScrollArea({
  children,
  className,
  innerClassName,
}: DivProps & { innerClassName?: string }) {
  return (
    <div className={cn('w-full min-h-0 flex-1 overflow-auto', className)}>
      <div className={cn('flex min-h-full min-w-max flex-col', innerClassName)}>{children}</div>
    </div>
  )
}

export function MikeTableHeaderRow({ children, className, ...props }: DivProps) {
  return (
    <div
      className={cn(
        'flex h-8 items-center border-b border-gray-200 pr-3 text-xs font-medium text-gray-500 select-none md:pr-10',
        STICKY_CELL_BG,
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}

export function MikeTableRow({
  children,
  className,
  interactive = true,
  onContextMenu,
  rightClickDropdown,
  ...props
}: DivProps & {
  interactive?: boolean
  rightClickDropdown?: ReactNode | ((close: () => void) => ReactNode)
}) {
  const [menuCoords, setMenuCoords] = useState<{ top: number; left: number } | null>(null)

  useEffect(() => {
    if (!menuCoords) return
    function handleClick() {
      setMenuCoords(null)
    }
    function handleCloseRowActions() {
      setMenuCoords(null)
    }
    document.addEventListener('click', handleClick)
    document.addEventListener(CLOSE_ROW_ACTIONS_EVENT, handleCloseRowActions)
    return () => {
      document.removeEventListener('click', handleClick)
      document.removeEventListener(CLOSE_ROW_ACTIONS_EVENT, handleCloseRowActions)
    }
  }, [menuCoords])

  function closeRightClickDropdown() {
    setMenuCoords(null)
  }

  function handleContextMenu(event: MouseEvent<HTMLDivElement>) {
    onContextMenu?.(event)
    if (!rightClickDropdown || event.defaultPrevented) return
    event.preventDefault()
    event.stopPropagation()
    closeRowActionMenus()
    const menuWidth = 192
    setMenuCoords({
      top: event.clientY,
      left: Math.min(event.clientX, window.innerWidth - menuWidth - 8),
    })
  }

  return (
    <>
      <div
        className={cn(
          'group flex h-10 items-center border-b border-gray-50 pr-3 transition-colors md:pr-10',
          interactive && 'cursor-pointer hover:bg-gray-100',
          className,
        )}
        onContextMenu={handleContextMenu}
        {...props}
      >
        {children}
      </div>
      {menuCoords && rightClickDropdown && (
        <div
          style={{ position: 'fixed', top: menuCoords.top, left: menuCoords.left }}
          className={cn('z-[120] w-48 overflow-hidden', GLASS_DROPDOWN)}
          onClick={(event) => event.stopPropagation()}
          onContextMenu={(event) => event.preventDefault()}
        >
          {typeof rightClickDropdown === 'function'
            ? rightClickDropdown(closeRightClickDropdown)
            : rightClickDropdown}
        </div>
      )}
    </>
  )
}

export function MikeTableStickyCell({
  children,
  className,
  widthClassName = TABLE_PRIMARY_CELL_WIDTH_CLASS,
  bgClassName = STICKY_CELL_BG,
  header = false,
  hover = true,
}: DivProps & {
  widthClassName?: string
  bgClassName?: string
  header?: boolean
  hover?: boolean
}) {
  return (
    <div
      className={cn(
        'sticky left-0 z-[60] flex gap-4 pl-4 pr-2 text-left',
        widthClassName,
        bgClassName,
        header ? 'items-center self-stretch' : 'py-2 transition-colors',
        !header && hover && 'group-hover:bg-gray-100',
        className,
      )}
    >
      {children}
    </div>
  )
}

export function MikeTablePrimaryCell({
  children,
  className,
  widthClassName = TABLE_PRIMARY_CELL_WIDTH_CLASS,
  bgClassName,
  selected,
  onSelectionChange,
  checkboxTitle,
  label,
}: DivProps & {
  widthClassName?: string
  bgClassName?: string
  selected: boolean
  onSelectionChange: () => void
  checkboxTitle?: string
  label?: ReactNode
}) {
  const content =
    label !== undefined ? (
      <span className="min-w-0 flex-1 truncate text-sm text-gray-800">{label}</span>
    ) : (
      children
    )

  return (
    <MikeTableStickyCell widthClassName={widthClassName} bgClassName={bgClassName} className={className}>
      <div className="flex min-w-0 items-center gap-4">
        <input
          type="checkbox"
          checked={selected}
          onChange={onSelectionChange}
          onClick={(event) => event.stopPropagation()}
          className={TABLE_CHECKBOX_CLASS}
          title={checkboxTitle}
        />
        {content}
      </div>
    </MikeTableStickyCell>
  )
}

export function MikeTableHeaderCell({ children, className, ...props }: DivProps) {
  return (
    <div className={cn('shrink-0 text-left', className)} {...props}>
      {children}
    </div>
  )
}

export function MikeTableCell({ children, className, ...props }: DivProps) {
  return (
    <div className={cn('shrink-0 truncate text-sm text-gray-500', className)} {...props}>
      {children}
    </div>
  )
}

export function MikeTableBody({ children, className, ...props }: DivProps) {
  return (
    <div className={cn('flex-1', className)} {...props}>
      {children}
    </div>
  )
}

export function MikeTableEmptyState({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'mx-auto flex w-full max-w-xs flex-1 flex-col items-start justify-center py-24',
        className,
      )}
    >
      {children}
    </div>
  )
}
