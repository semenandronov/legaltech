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
    return <span className="inline-citation-perplexity">[{index}]</span>
  }

  // Format citation like Perplexity: short name + number
  // Example: "habr +1", "sap +2", "document +1"
  const formatCitationLabel = (source: SourceInfo): string => {
    // Extract short name from file (remove extension, take first part)
    let name = source.file.replace(/\.[^/.]+$/, '') // Remove extension
    name = name.split(/[_\-\s]/)[0] // Take first word/part
    name = name.substring(0, 8).toLowerCase() // Limit to 8 chars, lowercase
    
    // Count how many times this source appears (for +N notation)
    const sameSourceCount = sources.filter(s => 
      s.file.replace(/\.[^/.]+$/, '').split(/[_\-\s]/)[0].toLowerCase() === name
    ).length
    
    if (sameSourceCount > 1) {
      return `${name} +${sameSourceCount}`
    }
    return name
  }

  const formatCitationTooltip = (source: SourceInfo): string => {
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

    const label = formatCitationLabel(source)

  return (
    <span
      className="inline-citation-perplexity"
      onClick={handleClick}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      {label}
      {showTooltip && source && (
        <div className="inline-citation-tooltip-perplexity">
          <div style={{ fontWeight: 600, marginBottom: source.text_preview ? '3px' : '0' }}>
            {formatCitationTooltip(source)}
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
