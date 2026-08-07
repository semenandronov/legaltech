"use client"

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Loader2, X } from 'lucide-react'
import type { CellDetails, UserFlagColor } from '@/services/tabularReviewApi'
import {
  isExplicitTabularNaValue,
  TABULAR_EMPTY_DISPLAY,
  TABULAR_LOW_CONFIDENCE_THRESHOLD,
  TABULAR_NA_DISPLAY,
  type TabularCellAttention,
} from '@/utils/tabularCellDisplay'
import type { CellCitationItem } from './buildCellCitationList'
import { MikeCellCommentsSection } from './MikeCellCommentsSection'
import type { CellComment } from '@/services/tabularReviewApi'

const FLAG_OPTIONS: Array<{ value: UserFlagColor; label: string; className: string }> = [
  { value: 'red', label: 'Красный', className: 'bg-red-500' },
  { value: 'orange', label: 'Оранжевый', className: 'bg-orange-500' },
  { value: 'yellow', label: 'Жёлтый', className: 'bg-amber-400' },
  { value: 'green', label: 'Зелёный', className: 'bg-green-500' },
]

interface MikeCellDetailPopoverProps {
  open: boolean
  anchorEl: HTMLElement | null
  onClose: () => void
  loading: boolean
  details: CellDetails | null
  citations: CellCitationItem[]
  selectedCitationIndex: number
  onSelectCitation: (index: number) => void
  onViewInDocument: () => void
  columnLabel: string
  fallbackAnswer?: string
  isExplicitNa?: boolean
  attention?: TabularCellAttention
  userFlag?: UserFlagColor | null
  flagSaving?: boolean
  onUserFlagChange?: (flag: UserFlagColor | null) => Promise<void> | void
  isSkipped?: boolean
  comments?: CellComment[]
  commentsLoading?: boolean
  commentSubmitting?: boolean
  currentUserId?: string | null
  onCommentSubmit?: (text: string) => Promise<void> | void
  onCommentResolve?: (commentId: string) => Promise<void> | void
  onCommentUnresolve?: (commentId: string) => Promise<void> | void
  onCommentDelete?: (commentId: string) => Promise<void> | void
  commentsReadOnly?: boolean
}

function resolveAnswerText(
  details: CellDetails | null,
  fallbackAnswer: string | undefined,
  isExplicitNa: boolean,
): string {
  const fromDetails = details?.cell_value?.trim()
  if (fromDetails) {
    if (isExplicitTabularNaValue(fromDetails)) return TABULAR_NA_DISPLAY
    return fromDetails
  }
  if (isExplicitNa) return TABULAR_NA_DISPLAY
  const fallback = (fallbackAnswer || '').trim()
  if (!fallback || fallback === TABULAR_EMPTY_DISPLAY || fallback === '-' || fallback === '—') {
    return '—'
  }
  if (isExplicitTabularNaValue(fallback) || fallback === TABULAR_NA_DISPLAY) {
    return TABULAR_NA_DISPLAY
  }
  return fallback
}

export function MikeCellDetailPopover({
  open,
  anchorEl,
  onClose,
  loading,
  details,
  citations,
  selectedCitationIndex,
  onSelectCitation,
  onViewInDocument,
  columnLabel,
  fallbackAnswer,
  isExplicitNa = false,
  attention = 'none',
  userFlag = null,
  flagSaving = false,
  onUserFlagChange,
  isSkipped = false,
  comments = [],
  commentsLoading = false,
  commentSubmitting = false,
  currentUserId = null,
  onCommentSubmit,
  onCommentResolve,
  onCommentUnresolve,
  onCommentDelete,
  commentsReadOnly = false,
}: MikeCellDetailPopoverProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<{ top: number; left: number; width: number } | null>(
    null,
  )
  const activeFlag = (details?.user_flag ?? userFlag) || null

  useLayoutEffect(() => {
    if (!open || !anchorEl) {
      setPosition(null)
      return
    }

    const updatePosition = () => {
      const rect = anchorEl.getBoundingClientRect()
      const width = Math.min(Math.max(rect.width, 288), 400)
      let left = rect.left
      if (left + width > window.innerWidth - 12) {
        left = window.innerWidth - width - 12
      }
      setPosition({
        top: rect.bottom + 4,
        left: Math.max(12, left),
        width,
      })
    }

    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [open, anchorEl])

  useEffect(() => {
    if (!open) return
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node
      if (panelRef.current?.contains(target)) return
      if (anchorEl?.contains(target)) return
      onClose()
    }
    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [open, anchorEl, onClose])

  if (!open || !position || typeof document === 'undefined') return null

  const answerText = resolveAnswerText(details, fallbackAnswer, isExplicitNa)
  const answerIsNa =
    isExplicitNa ||
    answerText === TABULAR_NA_DISPLAY ||
    isExplicitTabularNaValue(details?.cell_value) ||
    isExplicitTabularNaValue(fallbackAnswer)
  const answerIsEmpty = !answerIsNa && (answerText === '—' || answerText === TABULAR_EMPTY_DISPLAY)
  const selectedCitation = citations[selectedCitationIndex]
  const hasSourceMaterial = Boolean(
    details?.verbatim_extract ||
      details?.source_page ||
      (details?.source_references && details.source_references.length > 0),
  )
  const canOpenDocument = citations.length > 0 || hasSourceMaterial
  const showMissingCitations =
    !loading &&
    !isSkipped &&
    citations.length === 0 &&
    !details?.verbatim_extract &&
    !answerIsEmpty
  const confidence = details?.confidence_score
  const confidenceLow =
    typeof confidence === 'number' && confidence < TABULAR_LOW_CONFIDENCE_THRESHOLD
  const statusHint = isSkipped
    ? 'Пропущено: условие колонки не выполнено'
    : attention === 'conflict'
      ? 'Конфликт значений — стоит перепроверить'
      : attention === 'low_confidence' || confidenceLow
        ? 'Низкая уверенность — стоит перепроверить'
        : null

  return createPortal(
    <div
      ref={panelRef}
      className="ws-mike-cell-detail-popover"
      style={{
        position: 'fixed',
        top: position.top,
        left: position.left,
        width: position.width,
        zIndex: 2000,
      }}
      onClick={(event) => event.stopPropagation()}
    >
      <div className="ws-mike-cell-detail-popover-header">
        <p className="ws-mike-cell-detail-popover-title">{columnLabel}</p>
        <button
          type="button"
          className="ws-mike-cell-detail-popover-close"
          onClick={onClose}
          aria-label="Закрыть"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {loading ? (
        <div className="ws-mike-cell-detail-popover-loading">
          <Loader2 className="h-4 w-4 animate-spin text-gray-400" aria-hidden />
          <span>Загрузка…</span>
        </div>
      ) : (
        <div className="ws-mike-cell-detail-popover-body">
          <section>
            <p className="ws-mike-cell-detail-popover-label">Ответ</p>
            <p
              className={`ws-mike-cell-detail-popover-text${
                answerIsNa || answerIsEmpty || isSkipped
                  ? ' ws-mike-cell-detail-popover-text--muted'
                  : ''
              }`}
            >
              {isSkipped
                ? 'Пропущено по условию'
                : answerIsEmpty
                  ? 'Ячейка ещё не заполнена'
                  : answerText}
            </p>
            {statusHint && (
              <p className="ws-mike-cell-detail-popover-hint ws-mike-cell-detail-popover-hint--warn">
                {statusHint}
              </p>
            )}
          </section>

          {onUserFlagChange && (
            <section>
              <p className="ws-mike-cell-detail-popover-label">Флаг</p>
              <div className="ws-mike-cell-detail-flag-row">
                {FLAG_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    title={option.label}
                    aria-label={option.label}
                    disabled={flagSaving}
                    className={`ws-mike-flag-swatch ${option.className} ${
                      activeFlag === option.value ? 'ws-mike-flag-swatch--active' : ''
                    }`}
                    onClick={() => {
                      void onUserFlagChange(activeFlag === option.value ? null : option.value)
                    }}
                  />
                ))}
                <button
                  type="button"
                  className="ws-mike-cell-detail-flag-clear"
                  disabled={flagSaving || !activeFlag}
                  onClick={() => void onUserFlagChange(null)}
                >
                  Сбросить
                </button>
              </div>
            </section>
          )}

          {(commentsReadOnly || (onCommentSubmit && onCommentResolve && onCommentUnresolve && onCommentDelete)) && (
            <MikeCellCommentsSection
              comments={comments}
              loading={commentsLoading}
              submitting={commentSubmitting}
              currentUserId={currentUserId}
              readOnly={commentsReadOnly}
              onSubmit={onCommentSubmit ?? (async () => undefined)}
              onResolve={onCommentResolve ?? (async () => undefined)}
              onUnresolve={onCommentUnresolve ?? (async () => undefined)}
              onDelete={onCommentDelete ?? (async () => undefined)}
            />
          )}

          {(details?.reasoning || answerIsNa) && (
            <section>
              <p className="ws-mike-cell-detail-popover-label">Объяснение</p>
              <p className="ws-mike-cell-detail-popover-text ws-mike-cell-detail-popover-text--muted">
                {details?.reasoning ||
                  'Чёткий ответ не сформирован: в доступных фрагментах документа не найден нужный участок текста, который подтверждал бы ответ на вопрос столбца.'}
              </p>
            </section>
          )}

          {details?.verbatim_extract && (
            <section>
              <p className="ws-mike-cell-detail-popover-label">Цитата из документа</p>
              <p className="ws-mike-cell-detail-popover-text ws-mike-cell-detail-popover-text--quote">
                {details.verbatim_extract}
              </p>
            </section>
          )}

          {citations.length > 0 && (
            <section>
              <p className="ws-mike-cell-detail-popover-label">
                Источники ({citations.length})
              </p>
              <div className="ws-mike-cell-detail-popover-citations">
                {citations.map((citation) => (
                  <button
                    key={citation.index}
                    type="button"
                    className={`ws-mike-cell-detail-citation-btn ${
                      citation.index === selectedCitationIndex
                        ? 'ws-mike-cell-detail-citation-btn--active'
                        : ''
                    }`}
                    onClick={() => onSelectCitation(citation.index)}
                    title={citation.quote}
                  >
                    [{citation.index + 1}]
                    {citation.page != null ? ` · стр. ${citation.page}` : ''}
                  </button>
                ))}
              </div>
              {selectedCitation?.quote && (
                <p className="ws-mike-cell-detail-popover-citation-preview">
                  «{selectedCitation.quote}»
                </p>
              )}
            </section>
          )}

          {showMissingCitations && (
            <section>
              <p className="ws-mike-cell-detail-popover-label">Источники</p>
              <p className="ws-mike-cell-detail-popover-text ws-mike-cell-detail-popover-text--muted">
                Подтверждающая цитата не найдена
              </p>
            </section>
          )}

          {confidence != null && !isSkipped && (
            <section>
              <p className="ws-mike-cell-detail-popover-label">Уверенность</p>
              <p
                className={`ws-mike-cell-detail-popover-text${
                  confidenceLow ? ' ws-mike-cell-detail-popover-confidence--low' : ''
                }`}
              >
                {Math.round(confidence * 100)}%
              </p>
            </section>
          )}
        </div>
      )}

      <div className="ws-mike-cell-detail-popover-footer">
        <button
          type="button"
          className="ws-mike-cell-detail-popover-doc-btn"
          disabled={loading || !canOpenDocument}
          onClick={() => {
            onViewInDocument()
          }}
        >
          {canOpenDocument ? 'Посмотреть в документе' : 'Нет ссылки на документ'}
        </button>
      </div>
    </div>,
    document.body,
  )
}
