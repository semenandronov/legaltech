import React from 'react'
import type { StructuredEdit } from '@/services/documentEditorApi'

interface EditSuggestionCardProps {
  edit: StructuredEdit
  onApply: (edit: StructuredEdit) => void
  onSkip: (edit: StructuredEdit) => void
  onNavigate: (text: string) => void
  isApplied?: boolean
  isSkipped?: boolean
}

/**
 * Word-level diff: returns segments marked as 'equal', 'removed', or 'added'.
 * Uses a simple LCS-based approach on word arrays.
 */
type DiffSegment = { type: 'equal' | 'removed' | 'added'; text: string }

function computeWordDiff(oldText: string, newText: string): DiffSegment[] {
  const oldWords = oldText.split(/(\s+)/)
  const newWords = newText.split(/(\s+)/)

  // Build LCS table
  const m = oldWords.length
  const n = newWords.length
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (oldWords[i - 1] === newWords[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1])
      }
    }
  }

  // Backtrack to build diff
  const segments: DiffSegment[] = []
  let i = m, j = n
  const raw: { type: 'equal' | 'removed' | 'added'; word: string }[] = []

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldWords[i - 1] === newWords[j - 1]) {
      raw.push({ type: 'equal', word: oldWords[i - 1] })
      i--; j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      raw.push({ type: 'added', word: newWords[j - 1] })
      j--
    } else {
      raw.push({ type: 'removed', word: oldWords[i - 1] })
      i--
    }
  }
  raw.reverse()

  // Merge consecutive segments of the same type
  for (const item of raw) {
    if (segments.length > 0 && segments[segments.length - 1].type === item.type) {
      segments[segments.length - 1].text += item.word
    } else {
      segments.push({ type: item.type, text: item.word })
    }
  }

  return segments
}

/** Generate a brief description from the edit */
function generateEditTitle(edit: StructuredEdit): string {
  if ((edit as any).description) return (edit as any).description

  const origLen = edit.original_text.length
  const newLen = edit.new_text.length

  if (origLen === 0 && newLen > 0) {
    const preview = edit.new_text.slice(0, 60)
    return `Добавить: "${preview}${edit.new_text.length > 60 ? '...' : ''}"`
  }
  if (newLen === 0 && origLen > 0) {
    const preview = edit.original_text.slice(0, 60)
    return `Удалить: "${preview}${edit.original_text.length > 60 ? '...' : ''}"`
  }

  // For replacements, show a short summary
  const origPreview = edit.original_text.slice(0, 40)
  return `Заменить: "${origPreview}${origLen > 40 ? '...' : ''}"`
}

export const EditSuggestionCard: React.FC<EditSuggestionCardProps> = ({
  edit,
  onApply,
  onSkip,
  onNavigate,
  isApplied = false,
  isSkipped = false,
}) => {
  const isProcessed = isApplied || isSkipped
  const title = generateEditTitle(edit)
  const diffSegments = computeWordDiff(edit.original_text, edit.new_text)

  return (
    <div
      className={`rounded-xl border overflow-hidden transition-all duration-200 ${
        isApplied
          ? 'border-green-200 bg-green-50/30 opacity-70'
          : isSkipped
            ? 'border-gray-200 bg-gray-50/30 opacity-50'
            : 'border-gray-200 bg-white shadow-sm'
      }`}
    >
      {/* Title */}
      <div
        className="px-4 pt-3 pb-2 cursor-pointer"
        onClick={() => edit.found_in_document && !isProcessed && onNavigate(edit.original_text)}
      >
        <h4 className="text-sm font-semibold text-gray-900 leading-snug">
          {title}
        </h4>
        {isApplied && (
          <span className="inline-block mt-1 text-xs font-medium text-green-600">Применено</span>
        )}
        {isSkipped && (
          <span className="inline-block mt-1 text-xs font-medium text-gray-400">Пропущено</span>
        )}
      </div>

      {/* Inline redline diff */}
      <div className="px-4 pb-3">
        <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2.5 text-sm leading-relaxed text-gray-700">
          {/* Context before */}
          {edit.context_before && (
            <span className="text-gray-400">...{edit.context_before.slice(-80)} </span>
          )}

          {/* Diff segments */}
          {diffSegments.map((seg, idx) => {
            if (seg.type === 'removed') {
              return (
                <span
                  key={idx}
                  className="line-through decoration-2 text-red-500"
                  style={{ textDecorationColor: 'rgb(239 68 68)' }}
                >
                  {seg.text}
                </span>
              )
            }
            if (seg.type === 'added') {
              return (
                <span key={idx} className="text-green-600 font-medium">
                  {seg.text}
                </span>
              )
            }
            return <span key={idx}>{seg.text}</span>
          })}

          {/* Context after */}
          {edit.context_after && (
            <span className="text-gray-400"> {edit.context_after.slice(0, 80)}...</span>
          )}
        </div>

        {/* Warning if text not found */}
        {!edit.found_in_document && !isProcessed && (
          <div className="mt-2 text-xs text-amber-600">
            Текст не найден в документе
          </div>
        )}
      </div>

      {/* Action buttons - Harvey style */}
      {!isProcessed && (
        <div className="flex items-center border-t border-gray-100">
          <button
            onClick={() => onSkip(edit)}
            className="flex-1 px-4 py-2.5 text-sm font-medium text-gray-500 hover:text-gray-700 hover:bg-gray-50 transition-colors"
          >
            Dismiss
          </button>
          <div className="w-px h-8 bg-gray-100" />
          <button
            onClick={() => onApply(edit)}
            disabled={!edit.found_in_document}
            className="flex-1 px-4 py-2.5 text-sm font-semibold text-gray-900 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Apply
          </button>
        </div>
      )}
    </div>
  )
}

interface EditSuggestionsListProps {
  edits: StructuredEdit[]
  onApply: (edit: StructuredEdit) => void
  onSkip: (edit: StructuredEdit) => void
  onNavigate: (text: string) => void
  onApplyAll: () => void
  onSkipAll: () => void
  appliedIds: Set<string>
  skippedIds: Set<string>
}

export const EditSuggestionsList: React.FC<EditSuggestionsListProps> = ({
  edits,
  onApply,
  onSkip,
  onNavigate,
  onApplyAll,
  onSkipAll,
  appliedIds,
  skippedIds,
}) => {
  const pendingEdits = edits.filter(e => !appliedIds.has(e.id) && !skippedIds.has(e.id))
  const hasFoundEdits = pendingEdits.some(e => e.found_in_document)

  if (edits.length === 0) return null

  return (
    <div className="mt-4 space-y-3">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="text-sm font-semibold text-gray-900 mr-auto">
          {edits.length} suggestions
        </div>
        {pendingEdits.length > 1 && (
          <div className="flex items-center gap-1.5">
            <button
              onClick={onApplyAll}
              disabled={!hasFoundEdits}
              className="text-xs px-2.5 py-1 rounded-md bg-gray-900 text-white hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Apply all
            </button>
            <button
              onClick={onSkipAll}
              className="text-xs px-2.5 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors"
            >
              Dismiss all
            </button>
          </div>
        )}
      </div>

      {/* Cards */}
      <div className="space-y-3">
        {edits.map((edit) => (
          <EditSuggestionCard
            key={edit.id}
            edit={edit}
            onApply={onApply}
            onSkip={onSkip}
            onNavigate={onNavigate}
            isApplied={appliedIds.has(edit.id)}
            isSkipped={skippedIds.has(edit.id)}
          />
        ))}
      </div>
    </div>
  )
}

export default EditSuggestionCard
