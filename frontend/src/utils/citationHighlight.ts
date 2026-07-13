/**
 * Единая логика поиска цитаты в тексте и подсветки в HTML.
 * Приоритет: fuzzy match по буквам/цифрам (устойчив к пунктуации и пробелам),
 * затем literal substring с укороченными префиксами.
 *
 * Для Excel/HTML-таблиц: найти ячейку-кандидата → подсветить всю <tr>.
 */

export const CITATION_HIGHLIGHT_MARK_ID = 'citation-highlight'
export const CITATION_ROW_CLASS = 'citation-row-highlight'

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
  alternates?: Array<string | null | undefined> | null,
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

/**
 * Try candidates in order. Cell values (Excel/HTML) may be shorter than narrative quotes.
 */
export function findQuoteMatchAmongCandidates(
  fullText: string,
  candidates: Array<string | null | undefined>,
  options?: { minLen?: number },
): { start: number; end: number; matched: string } | null {
  const minLen = options?.minLen ?? MIN_QUOTE_LEN
  for (const raw of candidates) {
    const quote = (raw ?? '').trim()
    if (quote.length < 4) continue

    // Short cell values: literal case-insensitive match first (dates/amounts).
    if (quote.length < MIN_QUOTE_LEN) {
      if (quote.length < Math.min(minLen, 4)) continue
      const lower = fullText.toLowerCase()
      const idx = lower.indexOf(quote.toLowerCase())
      if (idx !== -1) {
        return { start: idx, end: idx + quote.length, matched: quote }
      }
      continue
    }

    const hit = findQuoteMatchInPlain(fullText, quote)
    if (hit) {
      return { ...hit, matched: quote }
    }
  }
  return null
}

function candidateMatchesText(text: string, candidate: string): boolean {
  return Boolean(findQuoteMatchAmongCandidates(text, [candidate], { minLen: 4 }))
}

export type TableRowScore = {
  index: number
  hits: number
  score: number
  uniqueHits: number
}

/**
 * Score HTML table rows for citation candidates (DOM-free, unit-testable).
 *
 * Prefers rows that match more candidates (description + amount + date),
 * then longer matches, then uniquely matched values (not shared across rows).
 */
export function scoreTableRowsForCandidates(
  rowTexts: string[],
  candidates: Array<string | null | undefined>,
): TableRowScore | null {
  const cleaned = candidates
    .map((c) => (c ?? '').trim())
    .filter((c) => c.length >= 4)
  if (!rowTexts.length || !cleaned.length) return null

  const matchMatrix: boolean[][] = rowTexts.map((text) =>
    cleaned.map((candidate) => candidateMatchesText(text, candidate)),
  )

  const uniqueFlags = cleaned.map((_, cIdx) => {
    let count = 0
    for (const row of matchMatrix) {
      if (row[cIdx]) count += 1
    }
    return count === 1
  })

  const scores: TableRowScore[] = rowTexts.map((_, index) => {
    let hits = 0
    let score = 0
    let uniqueHits = 0
    for (let cIdx = 0; cIdx < cleaned.length; cIdx++) {
      if (!matchMatrix[index][cIdx]) continue
      hits += 1
      score += cleaned[cIdx].length
      if (uniqueFlags[cIdx]) {
        uniqueHits += 1
        score += cleaned[cIdx].length
      }
    }
    return { index, hits, score, uniqueHits }
  })

  const viable = scores.filter((s) => s.hits > 0)
  if (!viable.length) return null

  viable.sort(
    (a, b) =>
      b.uniqueHits - a.uniqueHits ||
      b.hits - a.hits ||
      b.score - a.score ||
      a.index - b.index,
  )

  // Prefer a uniquely identifying candidate when top ties on weak hits.
  for (const candidate of cleaned) {
    const matchingIndexes = rowTexts
      .map((text, index) => (candidateMatchesText(text, candidate) ? index : -1))
      .filter((index) => index >= 0)
    if (matchingIndexes.length === 1) {
      return scores[matchingIndexes[0]] ?? null
    }
  }

  return viable[0] ?? null
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

function isDataTableRow(row: Element): row is HTMLTableRowElement {
  if (!(row instanceof HTMLTableRowElement)) return false
  // Header-only rows (th without td) are not citation targets.
  return Boolean(row.querySelector('td'))
}

function markEntireTableRow(row: HTMLTableRowElement): void {
  row.id = CITATION_HIGHLIGHT_MARK_ID
  row.classList.add(CITATION_ROW_CLASS)
  row.setAttribute('data-citation-highlight', 'true')
  row.style.backgroundColor = '#fef08a'
  row.querySelectorAll('td, th').forEach((cell) => {
    const el = cell as HTMLElement
    el.style.backgroundColor = '#fef08a'
  })
}

/**
 * Table path: locate the best <tr> for cell candidates and highlight the whole row.
 * Returns true when a table row was highlighted.
 */
export function highlightTableRowInContainer(
  container: HTMLElement,
  candidates: Array<string | null | undefined>,
): boolean {
  const rows = Array.from(container.querySelectorAll('tr')).filter(isDataTableRow)
  if (!rows.length) return false

  const best = scoreTableRowsForCandidates(
    rows.map((row) => row.textContent || ''),
    candidates,
  )
  if (!best) return false

  const target = rows[best.index]
  if (!target) return false
  markEntireTableRow(target)
  return true
}

/** Подсветить цитату в HTML (DOCX prose / Excel table preview). */
export function highlightQuoteInHtml(
  html: string,
  quote: string,
  alternates?: Array<string | null | undefined> | null,
): string {
  const candidates = buildQuoteSearchCandidates(quote, alternates)
  if (candidates.length === 0) return html

  try {
    const container = document.createElement('div')
    container.innerHTML = html

    // Excel / HTML tables: whole-row highlight (production path for statements).
    if (highlightTableRowInContainer(container, candidates)) {
      return container.innerHTML
    }

    // DOCX / prose fallback: mark matched text span.
    const textNodes = collectTextNodes(container)
    const nodeTexts = textNodes.map((node) => node.textContent || '')
    const fullText = nodeTexts.join('')
    const match = findQuoteMatchAmongCandidates(fullText, candidates, { minLen: 4 })
    if (!match) return html

    wrapPlainRangeInDom(textNodes, nodeTexts, match.start, match.end)
    return container.innerHTML
  } catch {
    return html
  }
}
