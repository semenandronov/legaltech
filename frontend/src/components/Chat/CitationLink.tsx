import React from 'react'
import { SourceInfo } from '../../services/api'
import './Chat.css'

interface CitationLinkProps {
  source: SourceInfo
  onClick?: (source: SourceInfo) => void
}

const CitationLink: React.FC<CitationLinkProps> = ({
  source,
  onClick
}) => {
  const formatCitation = (source: SourceInfo): string => {
    let citation = source.file
    if (source.page) {
      citation += `, стр. ${source.page}`
    }
    if (source.start_line) {
      citation += `, строки ${source.start_line}`
      if (source.end_line && source.end_line !== source.start_line) {
        citation += `-${source.end_line}`
      }
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
      className="chat-citation-link"
      onClick={handleClick}
      title={source.text_preview || formatCitation(source)}
    >
      📄 {formatCitation(source)}
    </span>
  )
}

export default CitationLink
