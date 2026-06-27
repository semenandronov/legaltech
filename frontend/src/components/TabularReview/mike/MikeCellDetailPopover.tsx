"use client"

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Loader2, X } from 'lucide-react'
import type { CellDetails } from '@/services/tabularReviewApi'
import type { CellCitationItem } from './buildCellCitationList'

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
}: MikeCellDetailPopoverProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<{ top: number; left: number; width: number } | null>(
    null,
  )

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

  const answerText = details?.cell_value?.trim() || '—'
  const selectedCitation = citations[selectedCitationIndex]
  const canOpenDocument =
    citations.length > 0 ||
    Boolean(
      details?.verbatim_extract ||
        details?.source_page ||
        (details?.source_references && details.source_references.length > 0),
    )

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
            <p className="ws-mike-cell-detail-popover-text">{answerText}</p>
          </section>

          {details?.reasoning && (
            <section>
              <p className="ws-mike-cell-detail-popover-label">Объяснение</p>
              <p className="ws-mike-cell-detail-popover-text ws-mike-cell-detail-popover-text--muted">
                {details.reasoning}
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

          {details?.confidence_score != null && (
            <section>
              <p className="ws-mike-cell-detail-popover-label">Уверенность</p>
              <p className="ws-mike-cell-detail-popover-text">
                {Math.round(details.confidence_score * 100)}%
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
          Посмотреть в документе
        </button>
      </div>
    </div>,
    document.body,
  )
}
