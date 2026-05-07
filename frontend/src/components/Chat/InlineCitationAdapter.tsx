import React, { useState } from 'react'
import ReactDOM from 'react-dom'
import { SourceInfo } from '@/services/api'

export interface InlineCitationAdapterProps {
  /** 1-based номер для отображения в суперскрипте */
  displayNumber: number
  sources: SourceInfo[]
  onClick?: (source: SourceInfo) => void
  /** Стабильный id цитаты из каталога; если нет — используется legacyIndex */
  citationId?: string
  /** Legacy: индекс в массиве sources (0-based), когда маркер без citation_id */
  legacySourceIndex?: number
}

/** Экспорт для юнит-тестов и отладки. */
export function resolveInlineCitationSource(
  sources: SourceInfo[],
  citationId: string | undefined,
  legacySourceIndex: number | undefined,
): SourceInfo | undefined {
  if (citationId) {
    return sources.find((s) => s.citation_id === citationId)
  }
  if (legacySourceIndex !== undefined && legacySourceIndex >= 0 && legacySourceIndex < sources.length) {
    return sources[legacySourceIndex]
  }
  return undefined
}

/**
 * Кликабельный бейдж цитаты: по citation_id или по legacy-индексу в sources.
 */
export const InlineCitationAdapter: React.FC<InlineCitationAdapterProps> = ({
  displayNumber,
  sources,
  onClick,
  citationId,
  legacySourceIndex,
}) => {
  const source = resolveInlineCitationSource(sources, citationId, legacySourceIndex)
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null)

  if (!source) {
    return (
      <sup
        style={{
          color: 'var(--color-text-muted, #9ca3af)',
          fontSize: '0.72em',
          marginLeft: '2px',
          fontWeight: 600,
        }}
      >
        [{displayNumber}]
      </sup>
    )
  }

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    onClick?.(source)
  }

  const handleMouseEnter = (e: React.MouseEvent<HTMLElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const tooltipWidth = 300
    let x = rect.left + rect.width / 2 - tooltipWidth / 2
    x = Math.max(8, Math.min(x, window.innerWidth - tooltipWidth - 8))
    const y = rect.top - 8
    setTooltipPos({ x, y })
  }

  const handleMouseLeave = () => {
    setTooltipPos(null)
  }

  const quoteText = source.quote || source.quote_anchor || source.text_preview || ''

  return (
    <span
      style={{ position: 'relative', display: 'inline' }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <sup
        onClick={handleClick}
        role="button"
        tabIndex={0}
        aria-label={`Источник ${displayNumber}, открыть документ`}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            handleClick(e as unknown as React.MouseEvent)
          }
        }}
        className="inline-citation-badge"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          minWidth: '1.125rem',
          height: '1.125rem',
          padding: '0 5px',
          marginLeft: '3px',
          background: 'color-mix(in srgb, var(--color-accent, #2563eb) 14%, var(--color-bg-elevated, #fff))',
          color: 'var(--color-accent, #2563eb)',
          border: '1px solid color-mix(in srgb, var(--color-accent, #2563eb) 32%, var(--color-border, #e5e7eb))',
          borderRadius: '999px',
          fontSize: '0.65rem',
          fontWeight: 700,
          lineHeight: 1,
          letterSpacing: '-0.02em',
          cursor: 'pointer',
          verticalAlign: 'super',
          transition: 'background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease',
          userSelect: 'none',
          boxShadow: '0 1px 2px color-mix(in srgb, var(--color-text-primary, #000) 6%, transparent)',
        }}
        onMouseOver={(e) => {
          e.currentTarget.style.background = 'color-mix(in srgb, var(--color-accent, #2563eb) 22%, var(--color-bg-elevated, #fff))'
          e.currentTarget.style.borderColor = 'var(--color-accent, #2563eb)'
        }}
        onMouseOut={(e) => {
          e.currentTarget.style.background =
            'color-mix(in srgb, var(--color-accent, #2563eb) 14%, var(--color-bg-elevated, #fff))'
          e.currentTarget.style.borderColor =
            'color-mix(in srgb, var(--color-accent, #2563eb) 32%, var(--color-border, #e5e7eb))'
        }}
      >
        {displayNumber}
      </sup>

      {tooltipPos &&
        ReactDOM.createPortal(
          <div
            style={{
              position: 'fixed',
              left: `${tooltipPos.x}px`,
              top: `${tooltipPos.y}px`,
              transform: 'translateY(-100%)',
              width: 'min(320px, calc(100vw - 16px))',
              padding: '12px 14px',
              background: 'var(--color-bg-elevated, #1e293b)',
              color: 'var(--color-text-primary, #e2e8f0)',
              border: '1px solid var(--color-border, #334155)',
              borderRadius: '12px',
              boxShadow: '0 12px 32px color-mix(in srgb, var(--color-text-primary, #000) 22%, transparent)',
              zIndex: 9999,
              fontSize: '12px',
              lineHeight: 1.5,
              pointerEvents: 'none',
            }}
          >
            <span
              style={{
                display: 'block',
                fontWeight: 650,
                fontSize: '11px',
                color: 'var(--color-text-secondary, #94a3b8)',
                marginBottom: '6px',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {source.file || 'Документ'}
              {source.page ? ` · стр. ${source.page}` : ''}
            </span>

            {quoteText && (
              <span
                style={{
                  display: 'block',
                  padding: '8px 10px',
                  background: 'var(--color-bg-secondary, rgba(0, 0, 0, 0.2))',
                  borderRadius: '8px',
                  fontStyle: 'italic',
                  color: 'var(--color-text-secondary, #cbd5e1)',
                  maxHeight: '88px',
                  overflow: 'hidden',
                }}
              >
                &laquo;{quoteText.length > 180 ? quoteText.substring(0, 180) + '...' : quoteText}&raquo;
              </span>
            )}

            <span
              style={{
                display: 'block',
                textAlign: 'center',
                marginTop: '8px',
                fontSize: '11px',
                color: 'var(--color-accent, #60a5fa)',
                fontWeight: 500,
              }}
            >
              Нажмите, чтобы открыть документ
            </span>
          </div>,
          document.body,
        )}
    </span>
  )
}
