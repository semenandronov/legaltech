"use client"

import { Check, X } from 'lucide-react'

interface MikeBreadcrumbRenameProps {
  value: string
  onChange: (value: string) => void
  onSave: () => void
  onCancel: () => void
}

export function MikeBreadcrumbRename({
  value,
  onChange,
  onSave,
  onCancel,
}: MikeBreadcrumbRenameProps) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1">
      <input
        autoFocus
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            onSave()
          }
          if (e.key === 'Escape') onCancel()
        }}
        className="min-w-0 max-w-[12rem] sm:max-w-[20rem] rounded border border-gray-200 bg-white px-2 py-0.5 text-base font-medium text-gray-900 outline-none focus:border-gray-400"
      />
      <button
        type="button"
        onMouseDown={(e) => {
          e.preventDefault()
          onSave()
        }}
        className="inline-flex h-6 w-6 items-center justify-center rounded text-gray-500 hover:bg-gray-100 hover:text-gray-900"
        title="Сохранить"
        aria-label="Сохранить"
      >
        <Check className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        onMouseDown={(e) => {
          e.preventDefault()
          onCancel()
        }}
        className="inline-flex h-6 w-6 items-center justify-center rounded text-gray-500 hover:bg-gray-100 hover:text-gray-900"
        title="Отмена"
        aria-label="Отмена"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </span>
  )
}
