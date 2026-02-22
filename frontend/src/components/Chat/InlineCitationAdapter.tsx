import React, { useState } from 'react'
import ReactDOM from 'react-dom'
import { SourceInfo } from '@/services/api'

interface InlineCitationAdapterProps {
  index: number
  sources: SourceInfo[]
  onClick?: (source: SourceInfo) => void
}

/**
 * Inline citation rendered as a compact superscript badge [N].
 * Hover shows document name + quote preview tooltip (fixed positioning).
 * Click opens document preview.
 */
export const InlineCitationAdapter: React.FC<InlineCitationAdapterProps> = ({
  index,
  sources,
  onClick,
}) => {
  const source = sources[index - 1] // Citations are 1-indexed
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null)

  if (!source) {
    return (
      <sup style={{ color: '#9ca3af', fontSize: '0.7em', marginLeft: '1px' }}>[{index}]</sup>
    )
  }

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (onClick) {
      onClick(source)
    }
  }

  const handleMouseEnter = (e: React.MouseEvent<HTMLElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const tooltipWidth = 300
    // Center tooltip on badge, clamped to viewport
    let x = rect.left + rect.width / 2 - tooltipWidth / 2
    x = Math.max(8, Math.min(x, window.innerWidth - tooltipWidth - 8))
    const y = rect.top - 8 // above the badge
    setTooltipPos({ x, y })
  }

  const handleMouseLeave = () => {
    setTooltipPos(null)
  }

  const quoteText = source.quote || source.text_preview || ''

  return (
    <span
      style={{ position: 'relative', display: 'inline' }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {/* Compact superscript badge */}
      <sup
        onClick={handleClick}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter') handleClick(e as any) }}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          minWidth: '16px',
          height: '16px',
          padding: '0 4px',
          marginLeft: '2px',
          background: 'rgba(37, 99, 235, 0.12)',
          color: '#2563eb',
          border: '1px solid rgba(37, 99, 235, 0.25)',
          borderRadius: '4px',
          fontSize: '10px',
          fontWeight: 600,
          lineHeight: 1,
          cursor: 'pointer',
          verticalAlign: 'super',
          transition: 'all 0.15s ease',
          userSelect: 'none',
        }}
        onMouseOver={(e) => {
          e.currentTarget.style.background = 'rgba(37, 99, 235, 0.2)'
          e.currentTarget.style.borderColor = '#2563eb'
        }}
        onMouseOut={(e) => {
          e.currentTarget.style.background = 'rgba(37, 99, 235, 0.12)'
          e.currentTarget.style.borderColor = 'rgba(37, 99, 235, 0.25)'
        }}
      >
        {index}
      </sup>

      {/* Tooltip rendered in portal to avoid overflow clipping */}
      {tooltipPos && ReactDOM.createPortal(
        <div style={{
          position: 'fixed',
          left: `${tooltipPos.x}px`,
          top: `${tooltipPos.y}px`,
          transform: 'translateY(-100%)',
          width: '300px',
          padding: '12px 14px',
          background: '#1e293b',
          color: '#e2e8f0',
          border: '1px solid #334155',
          borderRadius: '10px',
          boxShadow: '0 8px 24px rgba(0, 0, 0, 0.3)',
          zIndex: 9999,
          fontSize: '12px',
          lineHeight: 1.5,
          pointerEvents: 'none',
        }}>
          {/* Header */}
          <span style={{
            display: 'block',
            fontWeight: 600,
            fontSize: '12px',
            color: '#94a3b8',
            marginBottom: '6px',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>
            {source.file || 'Документ'}
            {source.page ? ` · стр. ${source.page}` : ''}
          </span>

          {/* Quote */}
          {quoteText && (
            <span style={{
              display: 'block',
              padding: '8px 10px',
              background: 'rgba(0, 0, 0, 0.2)',
              borderRadius: '6px',
              fontStyle: 'italic',
              color: '#cbd5e1',
              maxHeight: '80px',
              overflow: 'hidden',
            }}>
              &laquo;{quoteText.length > 180 ? quoteText.substring(0, 180) + '...' : quoteText}&raquo;
            </span>
          )}

          {/* CTA */}
          <span style={{
            display: 'block',
            textAlign: 'center',
            marginTop: '8px',
            fontSize: '11px',
            color: '#60a5fa',
          }}>
            Нажмите, чтобы открыть документ
          </span>
        </div>,
        document.body
      )}
    </span>
  )
}
