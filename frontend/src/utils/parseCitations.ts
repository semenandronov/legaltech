import React from 'react'
import InlineCitation from '../components/Chat/InlineCitation'
import { SourceInfo } from '../services/api'

/**
 * Parse text with citations [1][2][3] and replace with InlineCitation components
 */
export const parseCitations = (
  text: string,
  sources: SourceInfo[],
  onCitationClick?: (source: SourceInfo) => void
): (string | React.ReactElement)[] => {
  const parts: (string | React.ReactElement)[] = []
  const citationRegex = /\[(\d+)\]/g
  let lastIndex = 0
  let match

  while ((match = citationRegex.exec(text)) !== null) {
    // Add text before citation
    if (match.index > lastIndex) {
      parts.push(text.substring(lastIndex, match.index))
    }

    // Add citation component
    const citationIndex = parseInt(match[1], 10)
    parts.push(
      <InlineCitation
        key={`citation-${match.index}`}
        index={citationIndex}
        sources={sources}
        onClick={onCitationClick}
      />
    )

    lastIndex = match.index + match[0].length
  }

  // Add remaining text
  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex))
  }

  return parts.length > 0 ? parts : [text]
}

