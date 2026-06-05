import { useState } from 'react'
import type { Editor } from '@tiptap/react'
import { ChevronDown } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '../UI/dropdown-menu'
import { capturePmRange, type PmTextRange } from './editorSelection'

interface ToolbarTypographyMenuProps {
  editor: Editor
  label: string
  value: string
  options: { value: string; label: string }[]
  getSavedSelection: () => PmTextRange | null
  onApply: (value: string, saved: PmTextRange | null) => boolean
  onValueChange: (value: string) => void
  minWidth?: number
}

export function ToolbarTypographyMenu({
  editor,
  label,
  value,
  options,
  getSavedSelection,
  onApply,
  onValueChange,
  minWidth = 120,
}: ToolbarTypographyMenuProps) {
  const [open, setOpen] = useState(false)
  const display =
    options.find((o) => o.value === value)?.label ??
    options.find((o) => o.value === value)?.value ??
    label

  const pick = (next: string, saved: PmTextRange | null) => {
    onValueChange(next)
    onApply(next, saved)
    setOpen(false)
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={label}
          onMouseDown={(e) => {
            // Keep ProseMirror selection; native &lt;select&gt; used preventDefault and broke clicks.
            e.preventDefault()
          }}
          className="h-9 inline-flex items-center justify-between gap-1 px-2 text-sm border rounded-md bg-white hover:bg-gray-50 text-gray-800"
          style={{ borderColor: 'var(--color-border)', minWidth }}
        >
          <span className="truncate">{display}</span>
          <ChevronDown className="w-3.5 h-3.5 shrink-0 opacity-60" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="z-[10060]">
        <DropdownMenuRadioGroup
          value={value}
          onValueChange={(next) => {
            const saved = getSavedSelection() ?? capturePmRange(editor)
            pick(next, saved)
          }}
        >
          {options.map((opt) => (
            <DropdownMenuRadioItem key={opt.value} value={opt.value}>
              {opt.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
