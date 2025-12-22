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
  // Process content with inline citations [1][2][3]
  const processContent = (text: string) => {
    // Check if text contains citations
    const citationRegex = /\[(\d+)\]/g
    const hasCitations = citationRegex.test(text)
    
    if (!hasCitations || sources.length === 0) {
      // No citations, render normally
      return (
        <ReactMarkdown>{text}</ReactMarkdown>
      )
    }
    
    // Process text with citations - replace [1][2][3] with components
    const parts: (string | React.ReactElement)[] = []
    let lastIndex = 0
    let keyCounter = 0
    
    // Reset regex
    citationRegex.lastIndex = 0
    let match
    
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
    
    // Render with markdown for non-citation parts - inline to preserve citations
    return (
      <div>
        {parts.map((part, idx) => {
          if (React.isValidElement(part)) {
            return part
          }
          // Render markdown for text parts - inline to preserve citations
          return (
            <ReactMarkdown key={`text-${idx}`} components={{
              p: ({ children }) => <span style={{ display: 'inline' }}>{children}</span>,
              h1: ({ children }) => <h1 style={{ fontSize: '28px', fontWeight: 600, color: 'var(--color-primary)', margin: '0 0 16px 0', display: 'block' }}>{children}</h1>,
              h2: ({ children }) => <h2 style={{ fontSize: '24px', fontWeight: 600, color: 'var(--color-text)', margin: '24px 0 12px 0', display: 'block' }}>{children}</h2>,
              h3: ({ children }) => <h3 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--color-text)', margin: '20px 0 10px 0', display: 'block' }}>{children}</h3>,
              ul: ({ children }) => <ul style={{ margin: '16px 0', paddingLeft: '24px', display: 'block' }}>{children}</ul>,
              ol: ({ children }) => <ol style={{ margin: '16px 0', paddingLeft: '24px', display: 'block' }}>{children}</ol>,
              li: ({ children }) => <li style={{ margin: '8px 0', display: 'list-item' }}>{children}</li>,
              code: ({ children }) => <code style={{ backgroundColor: 'rgba(0, 212, 255, 0.15)', padding: '2px 6px', borderRadius: '4px', fontSize: '14px', fontFamily: "'Fira Code', 'Courier New', monospace", color: 'var(--color-primary)', display: 'inline' }}>{children}</code>,
              strong: ({ children }) => <strong style={{ fontWeight: 600, display: 'inline' }}>{children}</strong>,
              em: ({ children }) => <em style={{ display: 'inline' }}>{children}</em>,
              a: ({ children, href }) => <a href={href} style={{ color: 'var(--color-primary)', textDecoration: 'underline', textDecorationColor: 'rgba(0, 212, 255, 0.4)', display: 'inline' }}>{children}</a>,
              blockquote: ({ children }) => <blockquote style={{ borderLeft: '4px solid var(--color-primary)', paddingLeft: '16px', margin: '16px 0', color: 'var(--color-text-secondary)', fontStyle: 'italic', display: 'block' }}>{children}</blockquote>,
            }}>
              {part as string}
            </ReactMarkdown>
          )
        })}
      </div>
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
