import React, { useEffect, useRef } from "react"

interface TextHighlighterProps {
  text: string
  highlightText?: string | null
  className?: string
}

export const TextHighlighter: React.FC<TextHighlighterProps> = ({
  text,
  highlightText,
  className = "",
}) => {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!highlightText || !containerRef.current) return

    // Find and scroll to first occurrence
    const textContent = containerRef.current.textContent || ""
    const index = textContent.toLowerCase().indexOf(highlightText.toLowerCase())
    
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
        range.setEnd(targetNode, Math.min(targetOffset + highlightText.length, targetNode.textContent?.length || 0))
        
        // Scroll to the range
        range.getBoundingClientRect()
        targetNode.parentElement?.scrollIntoView({ behavior: "smooth", block: "center" })
      }
    }
  }, [highlightText, text])

  if (!highlightText) {
    return (
      <div ref={containerRef} className={className}>
        {text}
      </div>
    )
  }

  // Split text by highlightText (case-insensitive)
  const parts: Array<{ text: string; isHighlight: boolean }> = []
  let lastIndex = 0
  const searchText = text.toLowerCase()
  const highlightLower = highlightText.toLowerCase()
  let currentIndex = searchText.indexOf(highlightLower, lastIndex)

  while (currentIndex !== -1) {
    // Add text before highlight
    if (currentIndex > lastIndex) {
      parts.push({
        text: text.substring(lastIndex, currentIndex),
        isHighlight: false,
      })
    }

    // Add highlighted text
    parts.push({
      text: text.substring(currentIndex, currentIndex + highlightText.length),
      isHighlight: true,
    })

    lastIndex = currentIndex + highlightText.length
    currentIndex = searchText.indexOf(highlightLower, lastIndex)
  }

  // Add remaining text
  if (lastIndex < text.length) {
    parts.push({
      text: text.substring(lastIndex),
      isHighlight: false,
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
            className={part.isHighlight ? "bg-yellow-400 dark:bg-yellow-600/50 px-1 rounded" : ""}
          >
            {part.text}
          </span>
        ))
      )}
    </div>
  )
}

