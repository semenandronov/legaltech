import React, { useEffect, useRef } from "react"

interface TextHighlighterProps {
  text: string
  highlightText?: string | null
  highlightTexts?: string[] // Multiple texts to highlight
  searchQuery?: string // Search query to highlight
  className?: string
}

export const TextHighlighter: React.FC<TextHighlighterProps> = ({
  text,
  highlightText,
  highlightTexts = [],
  searchQuery,
  className = "",
}) => {
  const containerRef = useRef<HTMLDivElement>(null)

  // Combine all highlight texts
  const allHighlights = [
    ...(highlightText ? [highlightText] : []),
    ...highlightTexts,
    ...(searchQuery ? [searchQuery] : []),
  ].filter(Boolean)

  useEffect(() => {
    if (allHighlights.length === 0 || !containerRef.current) return

    // Find and scroll to first occurrence
    const textContent = containerRef.current.textContent || ""
    const firstHighlight = allHighlights[0]
    const index = textContent.toLowerCase().indexOf(firstHighlight.toLowerCase())
    
    if (index !== -1) {
      // Find the element containing the highlighted text
      const walker = document.createTreeWalker(
        containerRef.current,
        NodeFilter.SHOW_TEXT,
        null
      )
      
      let node
      let currentIndex = 0
      let targetNode: Text | null = null
      let targetOffset = 0
      
      while ((node = walker.nextNode())) {
        const nodeText = node.textContent || ""
        const nodeLength = nodeText.length
        
        if (currentIndex <= index && index < currentIndex + nodeLength) {
          targetNode = node as Text
          targetOffset = index - currentIndex
          break
        }
        
        currentIndex += nodeLength
      }
      
      if (targetNode) {
        const range = document.createRange()
        range.setStart(targetNode, targetOffset)
        range.setEnd(targetNode, Math.min(targetOffset + firstHighlight.length, targetNode.textContent?.length || 0))
        
        // Scroll to the range
        range.getBoundingClientRect()
        targetNode.parentElement?.scrollIntoView({ behavior: "smooth", block: "center" })
      }
    }
  }, [allHighlights.join(","), text])

  if (allHighlights.length === 0) {
    return (
      <div ref={containerRef} className={className}>
        {text}
      </div>
    )
  }

  // Create a map of all highlight positions
  type HighlightRange = { start: number; end: number; text: string; isSearch: boolean }
  const ranges: HighlightRange[] = []
  
  allHighlights.forEach((highlight) => {
    const searchText = text.toLowerCase()
    // Убираем "..." в конце цитаты если есть
    const highlightLower = highlight.toLowerCase().replace(/\.{3}$/, '').trim()
    const isSearch = highlight === searchQuery

    // Стратегия 1: Полное совпадение
    let currentIndex = searchText.indexOf(highlightLower)
    if (currentIndex !== -1) {
      ranges.push({
        start: currentIndex,
        end: currentIndex + highlightLower.length,
        text: highlightLower,
        isSearch,
      })
      return // Нашли - выходим
    }
    
    // Стратегия 2: Первые 100 символов
    if (highlightLower.length > 100) {
      const shortHighlight = highlightLower.substring(0, 100)
      currentIndex = searchText.indexOf(shortHighlight)
      if (currentIndex !== -1) {
        ranges.push({
          start: currentIndex,
          end: currentIndex + 100,
          text: shortHighlight,
          isSearch,
        })
        return
      }
    }
    
    // Стратегия 3: Первые 50 символов
    if (highlightLower.length > 50) {
      const shortHighlight = highlightLower.substring(0, 50)
      currentIndex = searchText.indexOf(shortHighlight)
      if (currentIndex !== -1) {
        ranges.push({
          start: currentIndex,
          end: currentIndex + 50,
          text: shortHighlight,
          isSearch,
        })
        return
      }
    }
    
    // Стратегия 4: Первое предложение
    const firstSentence = highlightLower.split(/[.!?]/)[0]
    if (firstSentence && firstSentence.length > 15) {
      currentIndex = searchText.indexOf(firstSentence)
      if (currentIndex !== -1) {
        ranges.push({
          start: currentIndex,
          end: currentIndex + firstSentence.length,
          text: firstSentence,
          isSearch,
        })
        return
      }
    }
    
    // Стратегия 5: Уникальные длинные слова
    const uniqueWords = highlightLower
      .split(/\s+/)
      .filter(w => w.length > 10 && !['документа', 'документов', 'информации', 'предоставляет'].includes(w))
    
    for (const word of uniqueWords) {
      currentIndex = searchText.indexOf(word)
      if (currentIndex !== -1) {
        // Расширяем контекст вокруг слова
        const contextStart = Math.max(0, currentIndex - 30)
        const contextEnd = Math.min(text.length, currentIndex + word.length + 100)
        ranges.push({
          start: contextStart,
          end: contextEnd,
          text: text.substring(contextStart, contextEnd),
          isSearch,
        })
        return
      }
    }
  })

  // Sort ranges by start position
  ranges.sort((a, b) => a.start - b.start)

  // Merge overlapping ranges
  const mergedRanges: HighlightRange[] = []
  for (const range of ranges) {
    if (mergedRanges.length === 0) {
      mergedRanges.push(range)
    } else {
      const last = mergedRanges[mergedRanges.length - 1]
      if (range.start <= last.end) {
        // Merge ranges
        last.end = Math.max(last.end, range.end)
        if (range.isSearch) last.isSearch = true
      } else {
        mergedRanges.push(range)
      }
    }
  }

  // Build parts array
  const parts: Array<{ text: string; isHighlight: boolean; isSearch: boolean }> = []
  let lastIndex = 0

  for (const range of mergedRanges) {
    // Add text before highlight
    if (range.start > lastIndex) {
      parts.push({
        text: text.substring(lastIndex, range.start),
        isHighlight: false,
        isSearch: false,
      })
    }

    // Add highlighted text
    parts.push({
      text: text.substring(range.start, range.end),
      isHighlight: true,
      isSearch: range.isSearch,
    })

    lastIndex = range.end
  }

  // Add remaining text
  if (lastIndex < text.length) {
    parts.push({
      text: text.substring(lastIndex),
      isHighlight: false,
      isSearch: false,
    })
  }

  return (
    <div ref={containerRef} className={className}>
      {parts.length === 0 ? (
        <div className="text-muted-foreground text-sm p-4 bg-muted/50 rounded-md">
          Текст для подсветки не найден в документе. Возможно, документ был изменен.
        </div>
      ) : (
        parts.map((part, index) => (
          <span
            key={index}
            className={
              part.isHighlight
                ? part.isSearch
                  ? "bg-blue-300 dark:bg-blue-600/50 px-1 rounded"
                  : "bg-yellow-400 dark:bg-yellow-600/50 px-1 rounded"
                : ""
            }
          >
            {part.text}
          </span>
        ))
      )}
    </div>
  )
}

