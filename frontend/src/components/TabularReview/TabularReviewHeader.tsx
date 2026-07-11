"use client"

import { useRef } from 'react'
import { Filter } from 'lucide-react'
import { buildMikeTabularHeaderProps, type TabularHeaderControllerInput } from './mike/buildMikeTabularHeader'
import { MikePageHeader } from './mike/MikePageHeader'

export type TabularReviewHeaderProps = Omit<TabularHeaderControllerInput, 'filterAction'> & {
  onOpenFilter: (anchorEl: HTMLElement) => void
  activeFilterCount?: number
}

/**
 * Tabular review header: Mike UI + наш контроллер (rename, run, export, filter, chat).
 */
export function TabularReviewHeader({
  onOpenFilter,
  activeFilterCount = 0,
  ...props
}: TabularReviewHeaderProps) {
  const filterBtnRef = useRef<HTMLButtonElement>(null)

  const filterAction = (
    <button
      ref={filterBtnRef}
      type="button"
      title="Фильтры"
      aria-label="Фильтры"
      aria-pressed={activeFilterCount > 0}
      disabled={props.processing}
      onClick={() => {
        if (filterBtnRef.current) onOpenFilter(filterBtnRef.current)
      }}
      className="flex h-7 w-7 items-center justify-center gap-1.5 rounded-full px-0 text-sm text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 active:bg-gray-100 disabled:cursor-default disabled:text-gray-300 disabled:hover:bg-transparent sm:w-auto sm:px-3"
    >
      <Filter className="h-4 w-4" />
      <span className="hidden sm:inline">Фильтры</span>
      {activeFilterCount > 0 ? (
        <span className="inline-flex min-w-[1.1rem] items-center justify-center rounded-full bg-gray-900 px-1.5 text-[10px] font-medium leading-4 text-white">
          {activeFilterCount}
        </span>
      ) : null}
    </button>
  )

  const headerProps = buildMikeTabularHeaderProps({
    ...props,
    filterAction,
  })

  return <MikePageHeader {...headerProps} />
}
