import React from 'react'
import ReactMarkdown from 'react-markdown'
import { SourceInfo } from '../../services/api'
import { InlineCitationAdapter } from './InlineCitationAdapter'

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
      
      // Add citation component (Perplexity style)
      const citationIndex = parseInt(match[1], 10)
      parts.push(
        <InlineCitationAdapter
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
              p: ({ children }) => <p style={{ margin: '0 0 12px 0', lineHeight: 1.7, display: 'block' }}>{children}</p>,
              h1: ({ children }) => <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'inherit', margin: '24px 0 16px 0', display: 'block', lineHeight: 1.3 }}>{children}</h1>,
              h2: ({ children }) => <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'inherit', margin: '20px 0 12px 0', display: 'block', lineHeight: 1.4 }}>{children}</h2>,
              h3: ({ children }) => <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'inherit', margin: '16px 0 10px 0', display: 'block', lineHeight: 1.4 }}>{children}</h3>,
              ul: ({ children }) => <ul style={{ margin: '12px 0', paddingLeft: '24px', display: 'block', lineHeight: 1.7 }}>{children}</ul>,
              ol: ({ children }) => <ol style={{ margin: '12px 0', paddingLeft: '24px', display: 'block', lineHeight: 1.7 }}>{children}</ol>,
              li: ({ children }) => <li style={{ margin: '6px 0', display: 'list-item', lineHeight: 1.7 }}>{children}</li>,
              code: ({ children, className }) => {
                const isInline = !className
                return isInline ? (
                  <code style={{ backgroundColor: 'rgba(0, 0, 0, 0.06)', padding: '2px 6px', borderRadius: '4px', fontSize: '0.9em', fontFamily: "'Fira Code', 'Courier New', monospace", color: 'inherit', display: 'inline' }}>{children}</code>
                ) : (
                  <code style={{ backgroundColor: 'rgba(0, 0, 0, 0.06)', padding: '12px', borderRadius: '6px', fontSize: '0.9em', fontFamily: "'Fira Code', 'Courier New', monospace", color: 'inherit', display: 'block', overflowX: 'auto', margin: '12px 0' }}>{children}</code>
                )
              },
              pre: ({ children }) => <pre style={{ backgroundColor: 'rgba(0, 0, 0, 0.04)', padding: '12px', borderRadius: '6px', fontSize: '0.9em', fontFamily: "'Fira Code', 'Courier New', monospace", overflowX: 'auto', margin: '12px 0', display: 'block' }}>{children}</pre>,
              strong: ({ children }) => <strong style={{ fontWeight: 600, display: 'inline' }}>{children}</strong>,
              em: ({ children }) => <em style={{ fontStyle: 'italic', display: 'inline' }}>{children}</em>,
              a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'underline', textDecorationColor: 'rgba(0, 0, 0, 0.3)', display: 'inline' }}>{children}</a>,
              blockquote: ({ children }) => <blockquote style={{ borderLeft: '3px solid rgba(0, 0, 0, 0.2)', paddingLeft: '16px', margin: '12px 0', color: 'inherit', fontStyle: 'normal', display: 'block', opacity: 0.8 }}>{children}</blockquote>,
              table: ({ children }) => <table style={{ borderCollapse: 'collapse', width: '100%', margin: '12px 0', display: 'block', overflowX: 'auto' }}>{children}</table>,
              th: ({ children }) => <th style={{ border: '1px solid rgba(0, 0, 0, 0.1)', padding: '8px 12px', textAlign: 'left', fontWeight: 600, backgroundColor: 'rgba(0, 0, 0, 0.04)' }}>{children}</th>,
              td: ({ children }) => <td style={{ border: '1px solid rgba(0, 0, 0, 0.1)', padding: '8px 12px' }}>{children}</td>,
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
