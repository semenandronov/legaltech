const PAGE_CITATION_RE = /\[\[page:(\d+)\|\|(?:quote:)?((?:[^\[\]]|\[[^\]]*\])+)\]\]/gi

export interface TabularParsedCitation {
  page: number
  quote: string
}

export function preprocessTabularCitations(text: string): {
  processed: string
  citations: TabularParsedCitation[]
} {
  const citations: TabularParsedCitation[] = []
  PAGE_CITATION_RE.lastIndex = 0
  const processed = text.replace(PAGE_CITATION_RE, (_, page, quote) => {
    const idx = citations.length
    citations.push({ page: parseInt(page, 10), quote: quote.trim() })
    return `§${idx}§`
  })
  return { processed, citations }
}

export function preprocessTabularCellMarkdown(text: string): {
  processed: string
  citations: TabularParsedCitation[]
  pills: string[]
} {
  const { processed: withCits, citations } = preprocessTabularCitations(text)
  const pills: string[] = []
  let out = withCits.replace(/\[\[([^\]]+)\]\]/g, (_, content: string) => {
    const idx = pills.length
    pills.push(content)
    return `\`§p${idx}§\`\u200B`
  })
  out = out.replace(/§(\d+)§/g, (_, idx) => `\`§c${idx}§\`\u200B`)
  return { processed: out, citations, pills }
}
