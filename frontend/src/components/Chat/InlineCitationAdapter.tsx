import React, { useState } from 'react'
import { SourceInfo } from '@/services/api'

interface InlineCitationAdapterProps {
  index: number
  sources: SourceInfo[]
  onClick?: (source: SourceInfo) => void
}

/**
 * Inline citation rendered as a compact clickable text link.
 * Shows abbreviated document name + page. Hover shows quote preview tooltip.
 */
export const InlineCitationAdapter: React.FC<InlineCitationAdapterProps> = ({
  index,
  sources,
  onClick,
}) => {
  const source = sources[index - 1] // Citations are 1-indexed
  const [showTooltip, setShowTooltip] = useState(false)

  if (!source) {
    return (
      <span style={{ color: '#9ca3af', fontSize: '0.85em' }}>[{index}]</span>
    )
  }

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (onClick) {
      onClick(source)
    }
  }

  // Format short file name for display
  const formatShortName = (filename: string): string => {
    let name = filename.replace(/\.[^/.]+$/, '') // Remove extension
    name = name.replace(/[_-]/g, ' ')
    if (name.length > 20) {
      name = name.substring(0, 20) + '\u2026'
    }
    return name
  }

  const shortName = source.file ? formatShortName(source.file) : '\u0414\u043E\u043A\u0443\u043C\u0435\u043D\u0442'
  const pageInfo = source.page ? `, \u0441.${source.page}` : ''
  const quoteText = source.quote || source.text_preview || ''

  return (
    <span
      style={{ position: 'relative', display: 'inline' }}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <span
        onClick={handleClick}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter') handleClick(e as any) }}
        style={{
          display: 'inline',
          color: '#2563eb',
          cursor: 'pointer',
          fontSize: '0.85em',
          fontWeight: 500,
          borderBottom: '1px dashed #93c5fd',
          paddingBottom: '1px',
          transition: 'all 0.15s ease',
          whiteSpace: 'nowrap',
        }}
        onMouseOver={(e) => {
          e.currentTarget.style.color = '#1d4ed8'
          e.currentTarget.style.borderBottomColor = '#2563eb'
          e.currentTarget.style.borderBottomStyle = 'solid'
        }}
        onMouseOut={(e) => {
          e.currentTarget.style.color = '#2563eb'
          e.currentTarget.style.borderBottomColor = '#93c5fd'
          e.currentTarget.style.borderBottomStyle = 'dashed'
        }}
        title={`${source.file || '\u0414\u043E\u043A\u0443\u043C\u0435\u043D\u0442'}${source.page ? `, \u0441\u0442\u0440. ${source.page}` : ''}`}
      >
        [{shortName}{pageInfo}]
      </span>

      {/* Tooltip with quote preview */}
      {showTooltip && quoteText && (
        <span
          style={{
            position: 'absolute',
            bottom: 'calc(100% + 8px)',
            left: '50%',
            transform: 'translateX(-50%)',
            minWidth: '250px',
            maxWidth: '360px',
            padding: '12px 14px',
            background: '#1e293b',
            color: '#e2e8f0',
            border: '1px solid #334155',
            borderRadius: '10px',
            boxShadow: '0 8px 24px rgba(0, 0, 0, 0.3)',
            zIndex: 1000,
            fontSize: '12px',
            lineHeight: 1.5,
            pointerEvents: 'none',
          }}
        >
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
            {source.file || '\u0414\u043E\u043A\u0443\u043C\u0435\u043D\u0442'}
            {source.page ? ` \u00B7 \u0441\u0442\u0440. ${source.page}` : ''}
          </span>

          {/* Quote */}
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

          {/* CTA */}
          <span style={{
            display: 'block',
            textAlign: 'center',
            marginTop: '8px',
            fontSize: '11px',
            color: '#60a5fa',
          }}>
            {'\u041D\u0430\u0436\u043C\u0438\u0442\u0435, \u0447\u0442\u043E\u0431\u044B \u043E\u0442\u043A\u0440\u044B\u0442\u044C \u0434\u043E\u043A\u0443\u043C\u0435\u043D\u0442'}
          </span>

          {/* Arrow */}
          <span style={{
            position: 'absolute',
            bottom: '-5px',
            left: '50%',
            transform: 'translateX(-50%) rotate(45deg)',
            width: '10px',
            height: '10px',
            background: '#1e293b',
            borderRight: '1px solid #334155',
            borderBottom: '1px solid #334155',
          }} />
        </span>
      )}
    </span>
  )
}
