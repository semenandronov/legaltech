import React, { useState } from 'react'
import { SourceInfo } from '../../services/api'
import './Chat.css'

interface InlineCitationProps {
  index: number
  sources: SourceInfo[]
  onClick?: (source: SourceInfo) => void
}

const InlineCitation: React.FC<InlineCitationProps> = ({
  index,
  sources,
  onClick
}) => {
  const [showTooltip, setShowTooltip] = useState(false)
  const source = sources[index - 1] // Citations are 1-indexed

  if (!source) {
    return <span className="inline-citation">[{index}]</span>
  }

  const formatCitation = (source: SourceInfo): string => {
    let citation = source.file
    if (source.page) {
      citation += `, стр. ${source.page}`
    }
    return citation
  }

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (onClick) {
      onClick(source)
    }
  }

  return (
    <span
      className="inline-citation"
      onClick={handleClick}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      [{index}]
      {showTooltip && source && (
        <div className="inline-citation-tooltip">
          <div style={{ fontWeight: 600, marginBottom: source.text_preview ? '3px' : '0' }}>
            {formatCitation(source)}
          </div>
          {source.text_preview && (
            <div style={{ fontSize: '10px', color: 'var(--color-text-secondary)', lineHeight: '1.4' }}>
              {source.text_preview.length > 150 ? source.text_preview.substring(0, 150) + '...' : source.text_preview}
            </div>
          )}
        </div>
      )}
    </span>
  )
}

export default InlineCitation

