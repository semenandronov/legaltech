"use client"

import { useRef } from 'react'
import { buildMikeTabularHeaderProps, type TabularHeaderControllerInput } from './mike/buildMikeTabularHeader'
import { MikePageHeader } from './mike/MikePageHeader'

export type TabularReviewHeaderProps = Omit<TabularHeaderControllerInput, 'onOpenFilter'> & {
  onOpenFilter: (anchorEl: HTMLElement) => void
}

/**
 * Tabular review header: Mike UI + наш контроллер (rename, run, export, filter, chat).
 */
export function TabularReviewHeader(props: TabularReviewHeaderProps) {
  const filterAnchorRef = useRef<HTMLButtonElement>(null)

  const headerProps = buildMikeTabularHeaderProps({
    ...props,
    onOpenFilter: () => {
      if (filterAnchorRef.current) {
        props.onOpenFilter(filterAnchorRef.current)
      }
    },
  })

  return (
    <div className="relative shrink-0">
      <button
        ref={filterAnchorRef}
        type="button"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
      />
      <MikePageHeader {...headerProps} />
    </div>
  )
}
