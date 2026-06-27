import { cn } from '@/lib/utils'

export const TABLE_CHECKBOX_CLASS =
  'h-2.5 w-2.5 shrink-0 rounded border-gray-200 cursor-pointer accent-black'

export const DOC_COL_W = 'w-[332px] shrink-0'
export const COL_W = 'w-[300px] shrink-0'
export const STICKY_CELL_BG = 'bg-[#fafbfc]'

export const DOC_COL_W_PX = 332
export const DATA_COL_W_PX = 300

/** Заголовок таблицы всегда выше sticky-ячееек документов в строках (z-60). */
export const TABLE_HEADER_ROW_Z = 'z-[70]'
export const TABLE_HEADER_CORNER_Z = 'z-[71]'
export const TABLE_BODY_STICKY_DOC_Z = 'z-[60]'

export function SkeletonLine({ className }: { className?: string }) {
  return <div className={cn('h-3 rounded bg-gray-100 animate-pulse', className)} />
}

export function SkeletonDot({ className }: { className?: string }) {
  return (
    <div className={cn('h-2.5 w-2.5 shrink-0 rounded bg-gray-100 animate-pulse', className)} />
  )
}
