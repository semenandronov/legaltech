"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { AlertCircle } from 'lucide-react'
import type { CellDetails, TabularColumn } from '@/services/tabularReviewApi'
import { tabularReviewApi } from '@/services/tabularReviewApi'
import { preprocessTabularCellMarkdown } from '@/utils/tabularCitationUtils'
import { shouldRenderAsPill } from '@/utils/tabularPillUtils'
import type { MikeTableCellVM } from './types'
import { getMikePillClass } from './mikePillUtils'
import { SkeletonLine } from './mikeTablePrimitives'
import { buildCellCitationList } from './buildCellCitationList'
import { MikeCellDetailPopover } from './MikeCellDetailPopover'

export type MikeCellColumnMeta = Pick<TabularColumn, 'column_type' | 'column_config'>

interface MikeTabularCellProps {
  cell: MikeTableCellVM
  columnMeta: MikeCellColumnMeta
  reviewId: string
  fileId: string
  columnId: string
  columnLabel: string
  isPopoverOpen: boolean
  isEditing: boolean
  onPopoverOpen: () => void
  onPopoverClose: () => void
  onViewInDocument: (citationIndex: number) => void
  onStartEdit: () => void
  onCancelEdit: () => void
  onSave: (value: string) => Promise<void>
}

const FLAG_STYLES = {
  reviewed: 'bg-green-500',
  green: 'bg-green-500',
  grey: 'bg-gray-400',
  yellow: 'bg-amber-400',
  red: 'bg-red-500',
} as const

const CLICK_DELAY_MS = 280

function normalizeYesNoEditValue(raw: string): string {
  const value = (raw || '').trim()
  if (!value) return ''
  if (value === 'Yes' || value.toLowerCase() === 'yes') return 'Да'
  if (value === 'No' || value.toLowerCase() === 'no') return 'Нет'
  if (value === 'Unknown' || value.toUpperCase() === 'N/A' || value === 'Н/Д') return 'N/A'
  return value
}

function getInitialEditValue(cell: MikeTableCellVM, columnMeta: MikeCellColumnMeta): string {
  const raw = (cell.rawValue ?? '').trim()
  if (!raw || raw === '-' || raw === '—') return ''

  const column = columnMeta as TabularColumn
  if (column.column_type === 'yes_no') {
    return normalizeYesNoEditValue(raw)
  }

  return cell.rawValue ?? ''
}

function TabularCellSkeleton() {
  return (
    <div className="flex h-full min-h-10 items-center px-2 py-2">
      <SkeletonLine className="h-3.5 w-full" />
    </div>
  )
}

function CellMarkdown({
  text,
  columnMeta,
  onCitationBadgeClick,
}: {
  text: string
  columnMeta: MikeCellColumnMeta
  onCitationBadgeClick?: (index: number) => void
}) {
  const column = columnMeta as TabularColumn
  const { processed, citations, pills } = useMemo(
    () => preprocessTabularCellMarkdown(text),
    [text],
  )

  if (shouldRenderAsPill(column, text)) {
    return (
      <span
        className={`inline-block rounded-full px-1.5 py-0.5 text-[10px] font-medium leading-none ${getMikePillClass(text, columnMeta)}`}
      >
        {text}
      </span>
    )
  }

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ ...props }) => <p className="mb-1 last:mb-0 leading-relaxed" {...props} />,
        ul: ({ ...props }) => <ul className="list-disc pl-4 space-y-0.5" {...props} />,
        ol: ({ ...props }) => <ol className="list-decimal pl-4 space-y-0.5" {...props} />,
        li: ({ ...props }) => <li {...props} />,
        strong: ({ ...props }) => <strong className="font-semibold" {...props} />,
        em: ({ ...props }) => <em className="italic" {...props} />,
        a: ({ href, children, ...props }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:text-blue-700 underline"
            {...props}
          >
            {children}
          </a>
        ),
        code: ({ children, ...props }) => {
          const token = String(children)
          const citMatch = token.match(/^§c(\d+)§$/)
          if (citMatch) {
            const idx = parseInt(citMatch[1], 10)
            const citation = citations[idx]
            if (citation) {
              return (
                <button
                  type="button"
                  title={`Стр. ${citation.page}: "${citation.quote}"`}
                  onClick={(event) => {
                    event.stopPropagation()
                    onCitationBadgeClick?.(idx)
                  }}
                  className="mx-0.5 inline-flex items-center justify-center rounded-full bg-gray-200 w-3.5 h-3.5 text-[9px] font-medium text-gray-700 align-super cursor-pointer hover:bg-gray-300 transition-colors border-0 p-0"
                  data-citation-badge
                >
                  {idx + 1}
                </button>
              )
            }
          }
          const pillMatch = token.match(/^§p(\d+)§$/)
          if (pillMatch) {
            const content = pills[parseInt(pillMatch[1], 10)]
            if (content !== undefined) {
              return (
                <span
                  className={`inline-block rounded-full px-1.5 py-0.5 text-[10px] font-medium leading-none ${getMikePillClass(content, columnMeta)}`}
                >
                  {content}
                </span>
              )
            }
          }
          return (
            <code className="bg-gray-100 px-1 py-0.5 rounded text-[11px] font-mono" {...props}>
              {children}
            </code>
          )
        },
      }}
    >
      {processed}
    </ReactMarkdown>
  )
}

function MikeInlineCellEditor({
  columnMeta,
  value,
  onChange,
  onKeyDown,
  onBlur,
  inputRef,
  minHeight,
}: {
  columnMeta: MikeCellColumnMeta
  value: string
  onChange: (value: string) => void
  onKeyDown: (event: React.KeyboardEvent) => void
  onBlur: () => void
  inputRef: React.RefObject<HTMLTextAreaElement | HTMLSelectElement | null>
  minHeight: number
}) {
  const column = columnMeta as TabularColumn

  if (column.column_type === 'yes_no') {
    return (
      <select
        ref={inputRef as React.RefObject<HTMLSelectElement>}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        onBlur={onBlur}
        className="ws-mike-cell-inline-select"
      >
        <option value="">—</option>
        <option value="Да">Да</option>
        <option value="Нет">Нет</option>
        <option value="N/A">N/A</option>
      </select>
    )
  }

  if (column.column_type === 'tag') {
    const options = column.column_config?.options ?? []
    return (
      <select
        ref={inputRef as React.RefObject<HTMLSelectElement>}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        onBlur={onBlur}
        className="ws-mike-cell-inline-select"
      >
        <option value="">—</option>
        {options.map((option) => (
          <option key={option.label} value={option.label}>
            {option.label}
          </option>
        ))}
      </select>
    )
  }

  return (
    <textarea
      ref={inputRef as React.RefObject<HTMLTextAreaElement>}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={onKeyDown}
      onBlur={onBlur}
      rows={Math.max(1, value.split('\n').length)}
      className="ws-mike-cell-inline-textarea"
      style={{ minHeight }}
    />
  )
}

export function MikeTabularCell({
  cell,
  columnMeta,
  reviewId,
  fileId,
  columnId,
  columnLabel,
  isPopoverOpen,
  isEditing,
  onPopoverOpen,
  onPopoverClose,
  onViewInDocument,
  onStartEdit,
  onCancelEdit,
  onSave,
}: MikeTabularCellProps) {
  const cellRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement | HTMLSelectElement | null>(null)
  const clickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const savingRef = useRef(false)
  const skipBlurCommitRef = useRef(false)
  const [details, setDetails] = useState<CellDetails | null>(null)
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [selectedCitationIndex, setSelectedCitationIndex] = useState(0)
  const [draft, setDraft] = useState('')
  const [editMinHeight, setEditMinHeight] = useState(40)

  const markdownSource = (cell.rawValue || cell.displayValue || '').trim()
  const displayValue = cell.displayValue === '-' ? '—' : cell.displayValue
  const isEmpty =
    !isEditing &&
    (!cell.displayValue || cell.displayValue === '-' || cell.displayValue === '—')

  const citations = useMemo(
    () => buildCellCitationList(cell.rawValue || markdownSource, details),
    [cell.rawValue, markdownSource, details],
  )

  const loadDetails = useCallback(async () => {
    setDetailsLoading(true)
    try {
      const loaded = await tabularReviewApi.getCellDetails(reviewId, fileId, columnId)
      setDetails(loaded)
    } catch (error) {
      console.error('Error loading cell details:', error)
      setDetails(null)
    } finally {
      setDetailsLoading(false)
    }
  }, [reviewId, fileId, columnId])

  const openPopover = useCallback(
    (citationIndex = 0) => {
      setSelectedCitationIndex(citationIndex)
      onPopoverOpen()
      void loadDetails()
    },
    [loadDetails, onPopoverOpen],
  )

  useEffect(() => {
    if (!isEditing) return
    setDraft(getInitialEditValue(cell, columnMeta))
    requestAnimationFrame(() => {
      const el = inputRef.current
      if (!el) return
      el.focus()
      if (el instanceof HTMLTextAreaElement) {
        el.setSelectionRange(el.value.length, el.value.length)
        el.style.height = 'auto'
        el.style.height = `${el.scrollHeight}px`
      }
    })
  }, [isEditing, cell, columnMeta])

  useEffect(() => {
    const el = inputRef.current
    if (!isEditing || !(el instanceof HTMLTextAreaElement)) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [draft, isEditing])

  const clearClickTimer = () => {
    if (clickTimerRef.current) {
      clearTimeout(clickTimerRef.current)
      clickTimerRef.current = null
    }
  }

  const commitEdit = useCallback(async () => {
    if (savingRef.current) return
    const initial = getInitialEditValue(cell, columnMeta)
    if (draft === initial) {
      onCancelEdit()
      return
    }
    savingRef.current = true
    try {
      await onSave(draft)
      onCancelEdit()
    } catch {
      // Остаёмся в режиме редактирования при ошибке
    } finally {
      savingRef.current = false
    }
  }, [cell, columnMeta, draft, onCancelEdit, onSave])

  const handleClick = (event: React.MouseEvent) => {
    if (isEditing) return
    const target = event.target as HTMLElement
    if (target.closest('a, button, [data-citation-badge]')) return

    clearClickTimer()
    clickTimerRef.current = setTimeout(() => {
      if (isPopoverOpen) {
        onPopoverClose()
      } else {
        openPopover(0)
      }
      clickTimerRef.current = null
    }, CLICK_DELAY_MS)
  }

  const handleDoubleClick = (event: React.MouseEvent) => {
    event.stopPropagation()
    clearClickTimer()
    onPopoverClose()
    const currentHeight = cellRef.current?.offsetHeight ?? 40
    setEditMinHeight(Math.max(40, currentHeight))
    onStartEdit()
  }

  const handleEditorKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      skipBlurCommitRef.current = true
      onCancelEdit()
      return
    }
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault()
      void commitEdit()
    }
  }

  const handleEditorBlur = () => {
    if (skipBlurCommitRef.current) {
      skipBlurCommitRef.current = false
      return
    }
    void commitEdit()
  }

  if (cell.isProcessing || cell.status === 'processing' || cell.status === 'generating') {
    return <TabularCellSkeleton />
  }

  if (cell.status === 'error') {
    return (
      <div className="flex h-full min-h-10 items-center justify-center px-2 py-2 text-gray-300">
        <AlertCircle className="h-4 w-4 text-red-300" aria-hidden />
      </div>
    )
  }

  const flagKey = cell.flag ?? (cell.status === 'reviewed' ? 'reviewed' : undefined)
  const flagStyle = flagKey ? FLAG_STYLES[flagKey] : undefined

  return (
    <>
      <div
        ref={cellRef}
        className={`relative flex h-full min-h-10 w-full flex-1 px-2 py-2 text-xs text-gray-800 leading-relaxed ${
          isEditing ? 'ws-mike-cell--editing' : 'cursor-pointer'
        }`}
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
      >
        {flagStyle && !isEditing && (
          <span
            className={`absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full ${flagStyle}`}
            title="Проверено"
          />
        )}

        {isEditing ? (
          <MikeInlineCellEditor
            columnMeta={columnMeta}
            value={draft}
            onChange={setDraft}
            onKeyDown={handleEditorKeyDown}
            onBlur={handleEditorBlur}
            inputRef={inputRef}
            minHeight={editMinHeight}
          />
        ) : isEmpty ? null : (
          <div className="w-full min-w-0 break-words pr-3">
            <CellMarkdown
              text={markdownSource === '-' || markdownSource === '—' ? displayValue : markdownSource}
              columnMeta={columnMeta}
              onCitationBadgeClick={(index) => {
                clearClickTimer()
                setSelectedCitationIndex(index)
                if (isPopoverOpen) {
                  onViewInDocument(index)
                } else {
                  openPopover(index)
                }
              }}
            />
          </div>
        )}
      </div>

      <MikeCellDetailPopover
        open={isPopoverOpen && !isEditing}
        anchorEl={cellRef.current}
        onClose={onPopoverClose}
        loading={detailsLoading}
        details={details}
        citations={citations}
        selectedCitationIndex={selectedCitationIndex}
        onSelectCitation={setSelectedCitationIndex}
        onViewInDocument={() => onViewInDocument(selectedCitationIndex)}
        columnLabel={columnLabel}
      />
    </>
  )
}
