import React, { useState } from 'react'
import { SourceInfo } from '../../services/api'
import { FileText, ExternalLink } from 'lucide-react'
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
    return <span className="inline-citation-badge">[{index}]</span>
  }

  // Format short document name
  const formatShortName = (filename: string): string => {
    let name = filename.replace(/\.[^/.]+$/, '') // Remove extension
    // Take meaningful part - last segment if it contains date/type
    const parts = name.split(/[_\-]/)
    if (parts.length > 2) {
      // Try to get date and type (e.g., "20170619_Opredelenie")
      const dateMatch = parts.find(p => /^\d{8}$/.test(p))
      const typeMatch = parts.find(p => p.length > 5 && !/^\d+$/.test(p))
      if (dateMatch && typeMatch) {
        return `${typeMatch.substring(0, 12)}`
      }
    }
    return name.substring(0, 15)
  }

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (onClick) {
      onClick(source)
    }
  }

  const shortName = formatShortName(source.file)
  const pageInfo = source.page ? ` стр.${source.page}` : ''

  return (
    <span
      className="inline-citation-clickable"
      onClick={handleClick}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && handleClick(e as any)}
      aria-label={`Открыть документ: ${source.file}`}
    >
      <FileText className="inline-citation-icon" />
      <span className="inline-citation-text">{shortName}{pageInfo}</span>
      <ExternalLink className="inline-citation-link-icon" />
      
      {showTooltip && (
        <div className="inline-citation-tooltip-modern">
          <div className="tooltip-header">
            <FileText size={14} />
            <span className="tooltip-filename">{source.file}</span>
          </div>
          {source.page && (
            <div className="tooltip-page">Страница {source.page}</div>
          )}
          {source.relevance && (
            <div className="tooltip-relevance">
              Релевантность: {Math.round(source.relevance * 100)}%
            </div>
          )}
          {source.text_preview && (
            <div className="tooltip-preview">
              {source.text_preview.length > 200 
                ? source.text_preview.substring(0, 200) + '...' 
                : source.text_preview}
            </div>
          )}
          <div className="tooltip-action">
            Нажмите, чтобы открыть документ →
          </div>
        </div>
      )}
    </span>
  )
}

export default InlineCitation
