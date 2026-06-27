import React, { useEffect, useRef, useMemo } from "react"
import { findQuoteMatchInPlain } from "@/utils/citationHighlight"

interface TextHighlighterProps {
  text: string
  highlightText?: string | null
  highlightTexts?: string[]
  searchQuery?: string
  className?: string
}

type HighlightRange = { start: number; end: number; isSearch: boolean }

export const TextHighlighter: React.FC<TextHighlighterProps> = ({
  text,
  highlightText,
  highlightTexts = [],
  searchQuery,
  className = "",
}) => {
  const containerRef = useRef<HTMLDivElement>(null)

  const citationHighlights = useMemo(() => {
    const candidates = [
      ...(highlightText ? [highlightText] : []),
      ...highlightTexts,
    ].filter(Boolean) as string[]

    for (const candidate of candidates) {
      const match = findQuoteMatchInPlain(text, candidate)
      if (match) {
        return [{ start: match.start, end: match.end, isSearch: false }]
      }
    }
    return []
  }, [text, highlightText, highlightTexts])

  const ranges = useMemo((): HighlightRange[] => {
    const merged = [...citationHighlights]

    if (searchQuery?.trim()) {
      const q = searchQuery.trim().toLowerCase()
      const lower = text.toLowerCase()
      const idx = lower.indexOf(q)
      if (idx !== -1) {
        merged.push({ start: idx, end: idx + q.length, isSearch: true })
      }
    }

    merged.sort((a, b) => a.start - b.start)

    const out: HighlightRange[] = []
    for (const range of merged) {
      const last = out[out.length - 1]
      if (!last || range.start > last.end) {
        out.push(range)
      } else {
        last.end = Math.max(last.end, range.end)
        last.isSearch = last.isSearch || range.isSearch
      }
    }
    return out
  }, [citationHighlights, searchQuery, text])

  useEffect(() => {
    if (ranges.length === 0 || !containerRef.current) return

    const walker = document.createTreeWalker(
      containerRef.current,
      NodeFilter.SHOW_TEXT,
      null,
    )

    const targetStart = ranges[0].start
    let currentIndex = 0
    let node: Node | null

    while ((node = walker.nextNode())) {
      const nodeText = node.textContent || ""
      const nodeLength = nodeText.length
      if (currentIndex <= targetStart && targetStart < currentIndex + nodeLength) {
        ;(node as Text).parentElement?.scrollIntoView({ behavior: "smooth", block: "center" })
        break
      }
      currentIndex += nodeLength
    }
  }, [ranges, text])

  const citationMissed =
    Boolean(highlightText?.trim() || highlightTexts.length > 0) && citationHighlights.length === 0

  if (ranges.length === 0) {
    return (
      <div ref={containerRef} className={className}>
        {citationMissed ? (
          <div className="text-muted-foreground text-sm p-4 bg-muted/50 rounded-md">
            Текст для подсветки не найден в документе.
          </div>
        ) : (
          text
        )}
      </div>
    )
  }

  const parts: Array<{ text: string; isHighlight: boolean; isSearch: boolean }> = []
  let lastIndex = 0

  for (const range of ranges) {
    if (range.start > lastIndex) {
      parts.push({ text: text.substring(lastIndex, range.start), isHighlight: false, isSearch: false })
    }
    parts.push({
      text: text.substring(range.start, range.end),
      isHighlight: true,
      isSearch: range.isSearch,
    })
    lastIndex = range.end
  }

  if (lastIndex < text.length) {
    parts.push({ text: text.substring(lastIndex), isHighlight: false, isSearch: false })
  }

  return (
    <div ref={containerRef} className={className}>
      {parts.map((part, index) => (
        <span
          key={index}
          className={
            part.isHighlight
              ? part.isSearch
                ? "bg-accent-muted/40 dark:bg-secondary0/50 px-1 rounded"
                : "bg-[#fef08a] px-0.5 rounded"
              : ""
          }
        >
          {part.text}
        </span>
      ))}
    </div>
  )
}