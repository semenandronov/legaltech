"use client"

import {
  Fragment,
  isValidElement,
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from 'react'
import { ChevronLeft, Loader2, Plus, Search, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface MikePageHeaderBreadcrumb {
  label?: ReactNode
  onClick?: () => void
  cursor?: 'text'
  loading?: boolean
  skeletonClassName?: string
  title?: string
}

type MikePageHeaderButtonAction = {
  type?: 'button'
  icon?: ReactNode
  label?: ReactNode
  onClick?: () => void
  disabled?: boolean
  title?: string
  variant?: 'default' | 'danger'
  iconOnly?: boolean
  tooltip?: ReactNode
}

type MikePageHeaderSearchAction = {
  type: 'search'
  value: string
  onChange: (value: string) => void
  placeholder?: string
}

type MikePageHeaderDeleteAction = {
  type: 'delete'
  onClick?: () => void
  disabled?: boolean
  loading?: boolean
  title?: string
}

type MikePageHeaderNewAction = {
  type: 'new'
  onClick?: () => void
  disabled?: boolean
  loading?: boolean
  title?: string
}

type MikePageHeaderCustomAction = {
  type: 'custom'
  render: ReactNode
}

export type MikePageHeaderAction =
  | MikePageHeaderButtonAction
  | MikePageHeaderSearchAction
  | MikePageHeaderDeleteAction
  | MikePageHeaderNewAction
  | MikePageHeaderCustomAction
  | ReactNode

export type MikePageHeaderActionGroup =
  | MikePageHeaderAction[]
  | {
      actions: MikePageHeaderAction[]
    }

export interface MikePageHeaderProps {
  children?: ReactNode
  actions?: MikePageHeaderAction[]
  actionGroups?: MikePageHeaderActionGroup[]
  shrink?: boolean
  className?: string
  breadcrumbs?: MikePageHeaderBreadcrumb[]
  loading?: boolean
}

/** Mike PageHeader — чистый UI (копия willchen96/mike). */
export function MikePageHeader({
  children,
  actions,
  actionGroups,
  shrink = false,
  className,
  breadcrumbs,
  loading = false,
}: MikePageHeaderProps) {
  const headerContent = breadcrumbs?.length ? (
    <MikePageHeaderBreadcrumbs items={breadcrumbs} />
  ) : (
    children
  )
  const actionsDisabled = loading || !!breadcrumbs?.some((item) => item.loading)
  const actionItems = actions?.filter(Boolean) ?? []
  const groupedActionItems =
    actionGroups
      ?.map(normalizeActionGroup)
      .filter((group) => group.actions.length > 0) ??
    (actionItems.length > 0 ? [{ actions: actionItems }] : [])
  const hasActions = groupedActionItems.length > 0

  return (
    <header
      className={cn(
        'flex items-center justify-between',
        'px-4 md:px-10 min-h-[76px] pb-4 pt-5.5',
        shrink && 'shrink-0',
        className,
      )}
    >
      {headerContent}
      {hasActions && (
        <div className="ml-4 flex shrink-0 items-center gap-3">
          <MikePageHeaderActionGroups
            groupedActionItems={groupedActionItems}
            actionsDisabled={actionsDisabled}
          />
        </div>
      )}
    </header>
  )
}

function MikePageHeaderActionGroups({
  groupedActionItems,
  actionsDisabled,
}: {
  groupedActionItems: { actions: MikePageHeaderAction[] }[]
  actionsDisabled: boolean
}) {
  return (
    <>
      {groupedActionItems.map((group, groupIndex) => (
        <div
          key={groupIndex}
          className={cn(
            'flex shrink-0 items-center gap-2',
            'rounded-full border border-white/70 bg-white px-1 py-1 shadow-[0_8px_24px_rgba(15,23,42,0.06)] backdrop-blur-2xl',
          )}
        >
          {group.actions.map((action, index) => (
            <Fragment key={index}>
              <MikePageHeaderActionRenderer action={action} disabled={actionsDisabled} />
            </Fragment>
          ))}
        </div>
      ))}
    </>
  )
}

function normalizeActionGroup(group: MikePageHeaderActionGroup) {
  if (Array.isArray(group)) {
    return { actions: group.filter(Boolean) }
  }
  return { actions: group.actions.filter(Boolean) }
}

function MikePageHeaderActionRenderer({
  action,
  disabled,
}: {
  action: MikePageHeaderAction
  disabled: boolean
}) {
  if (!isMikePageHeaderActionObject(action)) {
    return disabled ? (
      <span className="inline-flex h-7 items-center opacity-40 pointer-events-none">{action}</span>
    ) : (
      <>{action}</>
    )
  }

  switch (action.type) {
    case 'search':
      return <MikePageHeaderSearchActionControl action={action} disabled={disabled} />
    case 'delete':
      return <MikePageHeaderDeleteActionControl action={action} disabled={disabled} />
    case 'new':
      return <MikePageHeaderNewActionControl action={action} disabled={disabled} />
    case 'custom':
      return (
        <span className={cn('inline-flex h-7 items-center', disabled && 'pointer-events-none opacity-40')}>
          {action.render}
        </span>
      )
    case 'button':
    default:
      return <MikePageHeaderButtonActionControl action={action} disabled={disabled} />
  }
}

function isMikePageHeaderActionObject(
  action: MikePageHeaderAction,
): action is Exclude<MikePageHeaderAction, ReactNode> {
  return !!action && typeof action === 'object' && !isValidElement(action)
}

function MikePageHeaderButtonActionControl({
  action,
  disabled,
}: {
  action: MikePageHeaderButtonAction
  disabled: boolean
}) {
  const iconOnly = action.iconOnly ?? !action.label
  return (
    <div className={action.tooltip ? 'relative group' : undefined}>
      <MikePageHeaderActionButton
        onClick={action.onClick}
        disabled={disabled || action.disabled}
        title={action.title}
        aria-label={action.title}
        variant={action.variant}
        iconOnly={iconOnly}
      >
        {action.icon}
        {action.label}
      </MikePageHeaderActionButton>
      {action.tooltip && (
        <div className="pointer-events-none absolute right-0 top-full mt-1.5 z-10 hidden items-center whitespace-nowrap rounded-lg bg-gray-900 px-2.5 py-1.5 text-xs text-white shadow-lg group-hover:flex">
          {action.tooltip}
        </div>
      )}
    </div>
  )
}

function MikePageHeaderNewActionControl({
  action,
  disabled,
}: {
  action: MikePageHeaderNewAction
  disabled: boolean
}) {
  const title = action.title ?? 'New'
  return (
    <MikePageHeaderActionButton
      onClick={action.onClick}
      disabled={disabled || action.disabled || action.loading}
      title={title}
      aria-label={title}
      iconOnly
    >
      {action.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
    </MikePageHeaderActionButton>
  )
}

function MikePageHeaderDeleteActionControl({
  action,
  disabled,
}: {
  action: MikePageHeaderDeleteAction
  disabled: boolean
}) {
  const title = action.title ?? 'Delete'
  return (
    <MikePageHeaderActionButton
      onClick={action.onClick}
      disabled={disabled || action.disabled || action.loading}
      title={title}
      aria-label={title}
      iconOnly
      variant="danger"
    >
      {action.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
    </MikePageHeaderActionButton>
  )
}

function MikePageHeaderSearchActionControl({
  action,
  disabled,
}: {
  action: MikePageHeaderSearchAction
  disabled: boolean
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const placeholder = action.placeholder ?? 'Search…'

  useEffect(() => {
    function handleClick(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false)
        action.onChange('')
      }
    }
    if (open) document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open, action])

  return (
    <div ref={ref} className="relative flex items-center">
      {open ? (
        <div
          className={cn(
            pageHeaderActionControlClassName({
              className: 'cursor-text justify-start gap-2 px-3 text-gray-700 hover:text-gray-700',
            }),
            'w-56 bg-gray-100 sm:w-80',
          )}
        >
          <Search className="h-3.5 w-3.5 text-gray-400 shrink-0" />
          <input
            autoFocus
            disabled={disabled}
            type="text"
            placeholder={placeholder}
            value={action.value}
            onChange={(e) => action.onChange(e.target.value)}
            className="flex-1 text-sm text-gray-700 placeholder:text-gray-400 outline-none bg-transparent"
          />
        </div>
      ) : (
        <MikePageHeaderActionButton
          onClick={() => setOpen(true)}
          disabled={disabled}
          iconOnly
          title={placeholder}
          aria-label={placeholder}
        >
          <Search className="h-4 w-4" />
        </MikePageHeaderActionButton>
      )}
    </div>
  )
}

type MikePageHeaderActionButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> & {
  variant?: 'default' | 'danger'
  iconOnly?: boolean
}

function pageHeaderActionControlClassName({
  variant = 'default',
  iconOnly = false,
  disabled = false,
  className,
}: {
  variant?: 'default' | 'danger'
  iconOnly?: boolean
  disabled?: boolean
  className?: string
} = {}) {
  return cn(
    'flex h-7 items-center justify-center rounded-full text-sm transition-colors hover:bg-gray-100 active:bg-gray-100 disabled:cursor-default disabled:text-gray-300 disabled:hover:bg-transparent disabled:hover:text-gray-300',
    iconOnly ? 'w-7' : 'w-7 gap-1.5 px-0 sm:w-auto sm:px-3',
    disabled ? 'cursor-default' : 'cursor-pointer',
    variant === 'danger' ? 'text-gray-500 hover:text-red-600' : 'text-gray-500 hover:text-gray-900',
    className,
  )
}

function MikePageHeaderActionButton({
  children,
  variant = 'default',
  iconOnly = false,
  disabled,
  ...props
}: MikePageHeaderActionButtonProps) {
  return (
    <button
      disabled={disabled}
      className={pageHeaderActionControlClassName({ variant, iconOnly, disabled })}
      {...props}
    >
      {children}
    </button>
  )
}

function MikePageHeaderBreadcrumbs({ items }: { items: MikePageHeaderBreadcrumb[] }) {
  const parent = [...items]
    .slice(0, -1)
    .reverse()
    .find((item) => item.onClick)

  return (
    <div className="flex min-w-0 items-center gap-1.5 text-2xl font-medium font-serif">
      {parent?.onClick && (
        <button
          type="button"
          onClick={parent.onClick}
          className="shrink-0 text-gray-400 transition-colors hover:text-gray-600 sm:hidden"
          title={parent.title ?? 'Back'}
          aria-label={parent.title ?? 'Back'}
        >
          <ChevronLeft className="h-5 w-5" />
        </button>
      )}
      <div className="flex min-w-0 items-center gap-1.5">
        {items.map((item, index) => (
          <BreadcrumbItem key={index} item={item} current={index === items.length - 1} />
        ))}
      </div>
    </div>
  )
}

function BreadcrumbItem({
  item,
  current,
}: {
  item: MikePageHeaderBreadcrumb
  current: boolean
}) {
  const content = item.loading ? (
    <div className={cn('h-6 rounded bg-gray-100 animate-pulse', item.skeletonClassName ?? 'w-32')} />
  ) : (
    <span className={cn('truncate', item.cursor === 'text' && 'cursor-text')}>{item.label}</span>
  )

  const className = cn(
    'min-w-0 truncate transition-colors',
    item.cursor === 'text' && 'cursor-text',
    current ? 'text-gray-900' : item.onClick ? 'text-gray-500 hover:text-gray-700' : 'text-gray-500',
  )
  const wrapperClassName = cn('min-w-0 items-center gap-1.5', current ? 'flex' : 'hidden sm:flex')

  return (
    <span className={wrapperClassName}>
      {current ? (
        <span className={className}>{content}</span>
      ) : item.onClick ? (
        <button type="button" onClick={item.onClick} className={className}>
          {content}
        </button>
      ) : (
        <span className={className}>{content}</span>
      )}
      {!current && <span className="shrink-0 text-gray-300">›</span>}
    </span>
  )
}
