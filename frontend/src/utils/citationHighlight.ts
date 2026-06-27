/**
 * Единая логика поиска цитаты в тексте и подсветки в HTML.
 * Приоритет: fuzzy match по буквам/цифрам (устойчив к пунктуации и пробелам),
 * затем literal substring с укороченными префиксами.
 */

export const CITATION_HIGHLIGHT_MARK_ID = 'citation-highlight'

const MIN_QUOTE_LEN = 8
const MIN_SEGMENT_LEN = 6

export function normalizeForQuoteMatch(text: string): string {
  return text
    .replace(/\u00a0/g, ' ')
    .replace(/\u00ad/g, '')
    .replace(/[\u200b\u200c\u200d\ufeff]/g, '')
    .replace(/ё/g, 'е')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]/gu, '')
}

export function splitQuoteSegments(quote: string): string[] {
  return quote
    .split(/\.{3}|…/)
    .map((segment) => normalizeForQuoteMatch(segment.trim()))
    .filter((segment) => segment.length >= MIN_SEGMENT_LEN)
}

type StrippedIndex = {
  stripped: string
  /** stripped[i] → индекс символа в исходной строке */
  indexMap: number[]
}

function buildStrippedIndex(fullText: string): StrippedIndex {
  const indexMap: number[] = []
  let stripped = ''
  for (let i = 0; i < fullText.length; i++) {
    const ch = fullText[i]
    if (/[\p{L}\p{N}]/u.test(ch)) {
      stripped += ch.toLowerCase().replace(/ё/g, 'е')
      indexMap.push(i)
    }
  }
  return { stripped, indexMap }
}

/** Найти сегмент (только буквы/цифры) в plain text и вернуть диапазон в исходных координатах. */
export function findNormSegmentInPlain(
  fullText: string,
  normSegment: string,
): { start: number; end: number } | null {
  if (normSegment.length < MIN_SEGMENT_LEN) return null

  const { stripped, indexMap } = buildStrippedIndex(fullText)
  if (!stripped.length) return null

  const searchKey = normSegment.slice(0, Math.min(30, normSegment.length))
  const pos = stripped.indexOf(searchKey)
  if (pos === -1) return null

  const matchEnd = Math.min(pos + normSegment.length, indexMap.length)
  const origStart = indexMap[pos] ?? 0
  const lastIdx = matchEnd - 1
  const origEnd =
    lastIdx >= pos && lastIdx < indexMap.length
      ? indexMap[lastIdx] + 1
      : fullText.length

  return { start: origStart, end: Math.min(fullText.length, origEnd) }
}

/** Найти цитату в plain text. Возвращает [start, end) в координатах fullText. */
export function findQuoteMatchInPlain(
  fullText: string,
  quote: string,
): { start: number; end: number } | null {
  const trimmed = quote.replace(/\.{3}$/, '').trim()
  if (!trimmed || trimmed.length < MIN_QUOTE_LEN) return null

  const segments = splitQuoteSegments(quote)
  for (const segment of segments) {
    const hit = findNormSegmentInPlain(fullText, segment)
    if (hit) return hit
  }

  const lower = fullText.toLowerCase()
  const search = trimmed.toLowerCase()
  const lengths = [
    search.length,
    200,
    100,
    60,
    30,
  ].filter((len, idx, arr) => len >= MIN_QUOTE_LEN && arr.indexOf(len) === idx)

  for (const len of lengths) {
    const candidate = search.substring(0, Math.min(len, search.length))
    const idx = lower.indexOf(candidate)
    if (idx !== -1) {
      return { start: idx, end: idx + candidate.length }
    }
  }

  return null
}

export function buildQuoteSearchCandidates(
  primary?: string | null,
  alternates?: Array<string | null | undefined>,
): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  const add = (value?: string | null) => {
    const trimmed = (value ?? '').trim()
    if (trimmed.length < 2 || seen.has(trimmed)) return
    seen.add(trimmed)
    out.push(trimmed)
  }
  add(primary)
  alternates?.forEach(add)
  return out
}

function collectTextNodes(root: Node): Text[] {
  const nodes: Text[] = []
  const walk = (node: Node): void => {
    if (node.nodeType === Node.TEXT_NODE) {
      nodes.push(node as Text)
      return
    }
    Array.from(node.childNodes).forEach(walk)
  }
  walk(root)
  return nodes
}

function wrapPlainRangeInDom(
  textNodes: Text[],
  nodeTexts: string[],
  start: number,
  end: number,
): boolean {
  let currentPos = 0
  let firstMark = true

  for (let i = 0; i < textNodes.length; i++) {
    const nodeStart = currentPos
    const nodeText = nodeTexts[i]
    const nodeEnd = nodeStart + nodeText.length

    if (nodeEnd > start && nodeStart < end) {
      const hlStart = Math.max(0, start - nodeStart)
      const hlEnd = Math.min(nodeText.length, end - nodeStart)

      if (hlStart < hlEnd) {
        const parent = textNodes[i].parentNode
        if (!parent) continue

        const before = nodeText.substring(0, hlStart)
        const middle = nodeText.substring(hlStart, hlEnd)
        const after = nodeText.substring(hlEnd)

        const mark = document.createElement('mark')
        mark.style.backgroundColor = '#fef08a'
        mark.style.borderRadius = '2px'
        mark.style.padding = '2px 0'
        if (firstMark) {
          mark.id = CITATION_HIGHLIGHT_MARK_ID
          firstMark = false
        }
        mark.textContent = middle

        const frag = document.createDocumentFragment()
        if (before) frag.appendChild(document.createTextNode(before))
        frag.appendChild(mark)
        if (after) frag.appendChild(document.createTextNode(after))
        parent.replaceChild(frag, textNodes[i])
      }
    }
    currentPos = nodeEnd
  }

  return firstMark === false
}

/** Подсветить цитату в HTML-строке (DOCX preview). */
export function highlightQuoteInHtml(html: string, quote: string): string {
  if (!quote || quote.trim().length < MIN_QUOTE_LEN) return html

  try {
    const container = document.createElement('div')
    container.innerHTML = html

    const textNodes = collectTextNodes(container)
    const nodeTexts = textNodes.map((node) => node.textContent || '')
    const fullText = nodeTexts.join('')
    const match = findQuoteMatchInPlain(fullText, quote)
    if (!match) return html

    wrapPlainRangeInDom(textNodes, nodeTexts, match.start, match.end)
    return container.innerHTML
  } catch {
    return html
  }
}
