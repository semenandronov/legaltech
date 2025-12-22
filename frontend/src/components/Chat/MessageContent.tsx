import React from 'react'
import ReactMarkdown from 'react-markdown'
import { SourceInfo } from '../../services/api'
import InlineCitation from './InlineCitation'

interface MessageContentProps {
  content: string
  sources: SourceInfo[]
  onCitationClick?: (source: SourceInfo) => void
  isStreaming?: boolean
}

const MessageContent: React.FC<MessageContentProps> = ({
  content,
  sources,
  onCitationClick,
  isStreaming = false
}) => {
  // Parse citations [1][2][3] and replace with components
  const parseContent = (text: string): (string | React.ReactElement)[] => {
    const parts: (string | React.ReactElement)[] = []
    const citationRegex = /\[(\d+)\]/g
    let lastIndex = 0
    let match
    let keyCounter = 0

    while ((match = citationRegex.exec(text)) !== null) {
      // Add text before citation
      if (match.index > lastIndex) {
        const textBefore = text.substring(lastIndex, match.index)
        if (textBefore) {
          parts.push(textBefore)
        }
      }

      // Add citation component
      const citationIndex = parseInt(match[1], 10)
      parts.push(
        <InlineCitation
          key={`citation-${keyCounter++}`}
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

  // Process content with inline citations
  // We need to replace citations before ReactMarkdown processes the text
  const processContent = (text: string) => {
    // Replace [1][2][3] patterns with placeholders, then restore after markdown
    const citationPlaceholders: { [key: string]: number } = {}
    let processedText = text
    let placeholderCounter = 0
    
    // Replace citations with placeholders
    processedText = processedText.replace(/\[(\d+)\]/g, (match, index) => {
      const placeholder = `__CITATION_${placeholderCounter}__`
      citationPlaceholders[placeholder] = parseInt(index, 10)
      placeholderCounter++
      return placeholder
    })
    
    // Render markdown, then replace placeholders with citation components
    return (
      <ReactMarkdown
        components={{
          p: ({ children }) => {
            if (typeof children === 'string') {
              const parts: (string | React.ReactElement)[] = []
              let lastIndex = 0
              
              for (const placeholder in citationPlaceholders) {
                const index = processedText.indexOf(placeholder, lastIndex)
                if (index !== -1) {
                  // Add text before citation
                  if (index > lastIndex) {
                    parts.push(processedText.substring(lastIndex, index))
                  }
                  
                  // Add citation component
                  const citationIndex = citationPlaceholders[placeholder]
                  parts.push(
                    <InlineCitation
                      key={`citation-${placeholder}`}
                      index={citationIndex}
                      sources={sources}
                      onClick={onCitationClick}
                    />
                  )
                  
                  lastIndex = index + placeholder.length
                }
              }
              
              // Add remaining text
              if (lastIndex < processedText.length) {
                parts.push(processedText.substring(lastIndex))
              }
              
              return <p>{parts}</p>
            }
            return <p>{children}</p>
          },
        }}
      >
        {processedText}
      </ReactMarkdown>
    )
  }

  return (
    <>
      {processContent(content)}
      {isStreaming && <span className="streaming-cursor" aria-hidden="true" />}
    </>
  )
}

export default MessageContent

