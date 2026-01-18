import React from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { SourceInfo } from '../../services/api'
import { InlineCitationAdapter } from './InlineCitationAdapter'

interface MessageContentProps {
  content: string
  sources: SourceInfo[]
  onCitationClick?: (source: SourceInfo) => void
  isStreaming?: boolean
}

// Общие компоненты для улучшенной типографики и таблиц
const markdownComponents: Components = {
  // Параграфы с улучшенными отступами
  p: ({ children }) => (
    <p style={{ 
      margin: '0 0 20px 0', 
      lineHeight: 1.8, 
      display: 'block',
      color: 'inherit'
    }}>
      {children}
    </p>
  ),
  
  // Заголовки с четкой иерархией и большими отступами
  h1: ({ children }) => (
    <h1 style={{ 
      fontSize: '28px', 
      fontWeight: 700, 
      color: 'inherit', 
      margin: '40px 0 24px 0', 
      display: 'block', 
      lineHeight: 1.2,
      letterSpacing: '-0.02em',
      paddingTop: '8px'
    }}>
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 style={{ 
      fontSize: '22px', 
      fontWeight: 600, 
      color: 'inherit', 
      margin: '36px 0 20px 0', 
      display: 'block', 
      lineHeight: 1.3,
      letterSpacing: '-0.01em',
      paddingTop: '8px'
    }}>
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 style={{ 
      fontSize: '18px', 
      fontWeight: 600, 
      color: 'inherit', 
      margin: '32px 0 16px 0', 
      display: 'block', 
      lineHeight: 1.4,
      paddingTop: '6px'
    }}>
      {children}
    </h3>
  ),
  h4: ({ children }) => (
    <h4 style={{ 
      fontSize: '16px', 
      fontWeight: 600, 
      color: 'inherit', 
      margin: '28px 0 14px 0', 
      display: 'block', 
      lineHeight: 1.4,
      paddingTop: '4px'
    }}>
      {children}
    </h4>
  ),
  
  // Списки с улучшенным форматированием
  ul: ({ children }) => (
    <ul style={{ 
      margin: '20px 0', 
      paddingLeft: '32px', 
      display: 'block', 
      lineHeight: 1.8,
      listStyleType: 'disc'
    }}>
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol style={{ 
      margin: '20px 0', 
      paddingLeft: '32px', 
      display: 'block', 
      lineHeight: 1.8,
      listStyleType: 'decimal'
    }}>
      {children}
    </ol>
  ),
  li: ({ children }) => (
    <li style={{ 
      margin: '10px 0', 
      display: 'list-item', 
      lineHeight: 1.8,
      paddingLeft: '6px'
    }}>
      {children}
    </li>
  ),
  
  // Код с улучшенным форматированием
  code: ({ children, className }) => {
    const isInline = !className
    return isInline ? (
      <code style={{ 
        backgroundColor: 'rgba(0, 0, 0, 0.08)', 
        padding: '3px 6px', 
        borderRadius: '4px', 
        fontSize: '0.9em', 
        fontFamily: "'Fira Code', 'Courier New', monospace", 
        color: 'inherit', 
        display: 'inline',
        fontWeight: 500
      }}>
        {children}
      </code>
    ) : (
      <code style={{ 
        backgroundColor: 'rgba(0, 0, 0, 0.06)', 
        padding: '14px 16px', 
        borderRadius: '8px', 
        fontSize: '0.9em', 
        fontFamily: "'Fira Code', 'Courier New', monospace", 
        color: 'inherit', 
        display: 'block', 
        overflowX: 'auto', 
        margin: '16px 0',
        lineHeight: 1.6
      }}>
        {children}
      </code>
    )
  },
  pre: ({ children }) => (
    <pre style={{ 
      backgroundColor: 'rgba(0, 0, 0, 0.04)', 
      padding: '16px', 
      borderRadius: '8px', 
      fontSize: '0.9em', 
      fontFamily: "'Fira Code', 'Courier New', monospace", 
      overflowX: 'auto', 
      margin: '16px 0', 
      display: 'block',
      lineHeight: 1.6
    }}>
      {children}
    </pre>
  ),
  
  // Выделение текста
  strong: ({ children }) => (
    <strong style={{ 
      fontWeight: 600, 
      display: 'inline',
      color: 'inherit'
    }}>
      {children}
    </strong>
  ),
  em: ({ children }) => (
    <em style={{ 
      fontStyle: 'italic', 
      display: 'inline',
      color: 'inherit'
    }}>
      {children}
    </em>
  ),
  
  // Ссылки
  a: ({ children, href }) => (
    <a 
      href={href} 
      target="_blank" 
      rel="noopener noreferrer" 
      style={{ 
        color: 'inherit', 
        textDecoration: 'underline', 
        textDecorationColor: 'rgba(0, 0, 0, 0.3)', 
        display: 'inline',
        textUnderlineOffset: '2px'
      }}
    >
      {children}
    </a>
  ),
  
  // Цитаты
  blockquote: ({ children }) => (
    <blockquote style={{ 
      borderLeft: '4px solid rgba(0, 0, 0, 0.2)', 
      paddingLeft: '24px', 
      margin: '24px 0', 
      color: 'inherit', 
      fontStyle: 'normal', 
      display: 'block', 
      opacity: 0.85,
      paddingTop: '8px',
      paddingBottom: '8px',
      paddingRight: '16px',
      backgroundColor: 'rgba(0, 0, 0, 0.02)',
      borderRadius: '0 4px 4px 0'
    }}>
      {children}
    </blockquote>
  ),
  
  // Улучшенные таблицы с правильным рендерингом и стилями
  table: ({ children }) => (
    <div style={{
      margin: '24px 0',
      overflowX: 'auto',
      borderRadius: '8px',
      border: '1px solid rgba(0, 0, 0, 0.12)',
      display: 'block',
      boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)'
    }}>
      <table style={{ 
        borderCollapse: 'collapse', 
        width: '100%', 
        display: 'table',
        minWidth: '100%',
        backgroundColor: 'transparent'
      }}>
        {children}
      </table>
    </div>
  ),
  thead: ({ children }) => (
    <thead style={{ 
      display: 'table-header-group',
      backgroundColor: 'rgba(0, 0, 0, 0.04)'
    }}>
      {children}
    </thead>
  ),
  tbody: ({ children }) => (
    <tbody style={{ 
      display: 'table-row-group'
    }}>
      {children}
    </tbody>
  ),
  tr: ({ children }) => (
    <tr style={{ 
      display: 'table-row',
      borderBottom: '1px solid rgba(0, 0, 0, 0.08)'
    }}>
      {children}
    </tr>
  ),
  th: ({ children }) => (
    <th style={{ 
      border: '1px solid rgba(0, 0, 0, 0.12)', 
      padding: '14px 18px', 
      textAlign: 'left', 
      fontWeight: 600, 
      backgroundColor: 'rgba(0, 0, 0, 0.05)',
      display: 'table-cell',
      verticalAlign: 'middle',
      fontSize: '0.95em',
      color: 'inherit'
    }}>
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td style={{ 
      border: '1px solid rgba(0, 0, 0, 0.1)', 
      padding: '14px 18px',
      display: 'table-cell',
      verticalAlign: 'top',
      lineHeight: 1.7
    }}>
      {children}
    </td>
  ),
  hr: () => (
    <hr style={{
      border: 'none',
      borderTop: '2px solid rgba(0, 0, 0, 0.1)',
      margin: '32px 0',
      display: 'block'
    }} />
  ),
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
      // No citations, render with improved markdown components and GFM support for tables
      return (
        <ReactMarkdown 
          components={markdownComponents}
          remarkPlugins={[remarkGfm]}
        >
          {text}
        </ReactMarkdown>
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
    
    // Render with markdown for non-citation parts - TRUE INLINE to preserve flow (Harvey/Perplexity style)
    // Собираем текст обратно с плейсхолдерами для citations
    const citationPlaceholders: React.ReactElement[] = []
    let reconstructedText = ''
    
    parts.forEach((part, idx) => {
      if (React.isValidElement(part)) {
        // Используем уникальный плейсхолдер который не будет в тексте
        reconstructedText += `⟦CITE_${idx}⟧`
        citationPlaceholders.push(React.cloneElement(part, { key: `citation-inline-${idx}` }))
      } else {
        reconstructedText += part
      }
    })
    
    // Рендерим весь текст как единый markdown
    return (
      <div className="prose-inline-citations">
        <ReactMarkdown 
          components={{
            ...markdownComponents,
            // Переопределяем p чтобы вставлять citations inline
            p: ({ children }) => {
              // Преобразуем children в массив и обрабатываем плейсхолдеры
              const processChildren = (child: React.ReactNode): React.ReactNode => {
                if (typeof child === 'string') {
                  // Разбиваем строку по плейсхолдерам и вставляем компоненты
                  const parts = child.split(/(⟦CITE_\d+⟧)/g)
                  return parts.map((part, partIdx) => {
                    const match = part.match(/⟦CITE_(\d+)⟧/)
                    if (match) {
                      const citationIdx = parseInt(match[1], 10)
                      return citationPlaceholders[citationIdx] || <span key={`text-${partIdx}`}>{part}</span>
                    }
                    return <span key={`text-${partIdx}`}>{part}</span>
                  })
                }
                if (Array.isArray(child)) {
                  return child.map(processChildren)
                }
                return child
              }
              
              const processedChildren = React.Children.map(children, processChildren)
              
              return (
                <p style={{ 
                  margin: '0 0 16px 0', 
                  lineHeight: 1.75, 
                  display: 'block',
                  color: 'inherit'
                }}>
                  {processedChildren}
                </p>
              )
            }
          }}
          remarkPlugins={[remarkGfm]}
        >
          {reconstructedText}
        </ReactMarkdown>
      </div>
    )
  }

  return (
    <div style={{
      maxWidth: '100%',
      wordWrap: 'break-word',
      overflowWrap: 'break-word'
    }}>
      {processContent(content)}
      {isStreaming && <span className="streaming-cursor" aria-hidden="true" />}
    </div>
  )
}

export default MessageContent
