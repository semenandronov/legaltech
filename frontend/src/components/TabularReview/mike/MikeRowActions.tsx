"use client"

import { useEffect, useRef, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'

export const CLOSE_ROW_ACTIONS_EVENT = 'mike:close-row-actions'

export function closeRowActionMenus() {
  document.dispatchEvent(new Event(CLOSE_ROW_ACTIONS_EVENT))
}

const GLASS_DROPDOWN =
  'rounded-xl border border-white/70 bg-white/90 shadow-[0_8px_24px_rgba(15,23,42,0.08)] backdrop-blur-2xl'

interface MikeRowActionMenuItemsProps {
  onDelete?: () => void
  deleting?: boolean
  deleteDisabled?: boolean
  deleteLabel?: string
  onClose: () => void
}

export function MikeRowActionMenuItems({
  onDelete,
  deleting,
  deleteDisabled = false,
  deleteLabel = 'Удалить',
  onClose,
}: MikeRowActionMenuItemsProps) {
  if (!onDelete) return null

  return (
    <button
      type="button"
      onClick={() => {
        if (deleteDisabled || deleting) return
        onClose()
        onDelete()
      }}
      disabled={deleting || deleteDisabled}
      className={cn(
        'flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-red-500 transition-colors disabled:opacity-40',
        deleteDisabled ? 'cursor-not-allowed opacity-40 hover:bg-transparent' : 'hover:bg-red-500/10',
      )}
    >
      <Trash2 className="h-3.5 w-3.5" />
      {deleteLabel}
    </button>
  )
}

interface MikeRowActionsProps {
  onDelete?: () => void
  deleting?: boolean
  deleteDisabled?: boolean
  deleteLabel?: string
}

export function MikeRowActions(props: MikeRowActionsProps) {
  const [open, setOpen] = useState(false)
  const [coords, setCoords] = useState({ top: 0, right: 0 })
  const btnRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    function handleClick() {
      setOpen(false)
    }
    document.addEventListener('click', handleClick)
    return () => document.removeEventListener('click', handleClick)
  }, [open])

  useEffect(() => {
    function handleCloseRowActions() {
      setOpen(false)
    }
    document.addEventListener(CLOSE_ROW_ACTIONS_EVENT, handleCloseRowActions)
    return () => document.removeEventListener(CLOSE_ROW_ACTIONS_EVENT, handleCloseRowActions)
  }, [])

  function handleToggle(event: React.MouseEvent) {
    event.stopPropagation()
    if (open) {
      setOpen(false)
      return
    }
    closeRowActionMenus()
    if (btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect()
      setCoords({
        top: rect.bottom + 4,
        right: window.innerWidth - rect.right,
      })
    }
    setOpen(true)
  }

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={handleToggle}
        className="flex h-6 w-6 items-center justify-center rounded text-xs leading-none tracking-widest text-gray-700 transition-colors hover:bg-gray-100 hover:text-gray-900"
        aria-label="Действия"
      >
        ···
      </button>

      {open && (
        <div
          style={{ position: 'fixed', top: coords.top, right: coords.right }}
          className={cn('z-[120] w-48 overflow-hidden', GLASS_DROPDOWN)}
          onClick={(event) => event.stopPropagation()}
        >
          <MikeRowActionMenuItems {...props} onClose={() => setOpen(false)} />
        </div>
      )}
    </>
  )
}
