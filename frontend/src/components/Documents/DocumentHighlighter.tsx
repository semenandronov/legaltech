import React, { useMemo, useEffect, useRef } from 'react'

export interface HighlightRange {
  char_start: number
  char_end: number
  color?: string
  id?: string
}

interface DocumentHighlighterProps {
  text: string
  highlights: HighlightRange[]
  className?: string
  highlightColor?: string
}

/**
 * Компонент для подсветки текста в документе по координатам символов
 * 
 * Используется для отображения цитат из EnhancedCitation с точными координатами
 */
export const DocumentHighlighter: React.FC<DocumentHighlighterProps> = ({
  text,
  highlights,
  className = '',
  highlightColor = '#fef08a' // Yellow background
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  
  // Сортируем highlights по char_start
  const sortedHighlights = useMemo(() => {
    return [...highlights].sort((a, b) => a.char_start - b.char_start)
  }, [highlights])
  
  // Автоскролл к первому highlight после рендера
  useEffect(() => {
    if (sortedHighlights.length === 0 || !containerRef.current) return
    
    // Находим первый элемент <mark> в контейнере
    const firstMark = containerRef.current.querySelector('mark')
    if (firstMark) {
      // Прокручиваем к первому подсвеченному элементу
      firstMark.scrollIntoView({ 
        behavior: 'smooth', 
        block: 'center',
        inline: 'nearest'
      })
    }
  }, [sortedHighlights, text]) // Зависимости: highlights и text

  // Разбиваем текст на части с подсветкой
  const parts = useMemo(() => {
    if (sortedHighlights.length === 0) {
      return [{ text, isHighlight: false, id: undefined }]
    }

    const result: Array<{ text: string; isHighlight: boolean; id?: string; color?: string }> = []
    let lastIndex = 0

    for (const highlight of sortedHighlights) {
      const { char_start, char_end, color: highlightColorOverride, id } = highlight

      // Добавляем текст до подсветки
      if (char_start > lastIndex) {
        result.push({
          text: text.substring(lastIndex, char_start),
          isHighlight: false
        })
      }

      // Добавляем подсвеченный текст
      if (char_end > char_start && char_end <= text.length) {
        result.push({
          text: text.substring(char_start, char_end),
          isHighlight: true,
          id,
          color: highlightColorOverride || highlightColor
        })
      }

      lastIndex = Math.max(lastIndex, char_end)
    }

    // Добавляем оставшийся текст
    if (lastIndex < text.length) {
      result.push({
        text: text.substring(lastIndex),
        isHighlight: false
      })
    }

    return result
  }, [text, sortedHighlights, highlightColor])

  return (
    <div ref={containerRef} className={className}>
      {parts.map((part, index) => {
        if (part.isHighlight) {
          return (
            <mark
              key={index}
              id={part.id}
              style={{
                backgroundColor: part.color,
                padding: '2px 0',
                borderRadius: '2px',
                cursor: part.id ? 'pointer' : 'default'
              }}
              title={part.id ? `Цитата ${part.id}` : undefined}
            >
              {part.text}
            </mark>
          )
        }
        return <span key={index}>{part.text}</span>
      })}
    </div>
  )
}

/**
 * Хук для преобразования SourceInfo с координатами в HighlightRange[]
 */
export const useCitationHighlights = (
  citations: Array<{
    char_start?: number
    char_end?: number
    source_id?: string
  }>
): HighlightRange[] => {
  return useMemo(() => {
    return citations
      .filter(c => c.char_start !== undefined && c.char_end !== undefined)
      .map(c => ({
        char_start: c.char_start!,
        char_end: c.char_end!,
        id: c.source_id,
        color: '#fef08a' // Yellow by default
      }))
  }, [citations])
}

