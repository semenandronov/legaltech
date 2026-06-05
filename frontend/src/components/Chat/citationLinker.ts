/**
 * Детерминированная вставка инлайн-маркеров цитат по citation_id.
 * См. план inline citation linker: сегментация, скоринг по overlap с quote_anchor/quote/context, answer_blocks как ограничение кандидатов.
 */
import type { SourceInfo } from '@/services/api'
import type { AnswerBlockItem } from './AnswerBlocks'

export const CITE_ZW = '\u200B\u200B'
export const CITE_PREFIX = `${CITE_ZW}CITE_`
export const CITE_SUFFIX = `_ENDCITE${CITE_ZW}`

/** Текст уже содержит маркеры с бэкенда (expand_dc_markers) — не гонять через linkCitationsInline. */
export function hasEmbeddedCitationMarkers(text: string): boolean {
  return text.includes(CITE_PREFIX)
}

/** Маркер: CITE_<citation_id>_<displayN>_ENDCITE (citation_id обычно cit_<12 hex>). */
export function encodeCitationMarker(citationId: string, displayN: number): string {
  return `${CITE_PREFIX}${citationId}_${displayN}${CITE_SUFFIX}`
}

/** Legacy: один номер — индекс в упорядоченном списке источников (1-based). */
export function encodeLegacyCitationMarker(displayN: number): string {
  return `${CITE_PREFIX}${displayN}${CITE_SUFFIX}`
}

const TOKEN_SPLIT = /[^\p{L}\p{N}]+/gu

function tokenize(s: string): Set<string> {
  const t = s
    .toLowerCase()
    .replace(/[«»""„''‟]/g, ' ')
    .trim()
  if (!t) return new Set()
  const parts = t.split(TOKEN_SPLIT).filter((w) => w.length > 1 || /^\p{N}+$/u.test(w))
  return new Set(parts)
}

function citationTokens(source: SourceInfo): Set<string> {
  const chunks = [
    source.quote_anchor,
    source.quote,
    source.text_preview,
    source.context_before,
    source.context_after,
  ]
    .filter(Boolean)
    .join(' ')
  return tokenize(chunks)
}

function segmentTokens(s: string): Set<string> {
  return tokenize(s)
}

function jaccard(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0
  let inter = 0
  for (const x of a) {
    if (b.has(x)) inter++
  }
  const union = a.size + b.size - inter
  return union > 0 ? inter / union : 0
}

const STOP = new Set([
  'the',
  'and',
  'for',
  'that',
  'this',
  'with',
  'from',
  'был',
  'была',
  'было',
  'были',
  'как',
  'или',
  'для',
  'при',
  'так',
  'его',
  'её',
  'их',
  'что',
  'это',
  'все',
  'всё',
  'по',
  'на',
  'из',
  'к',
  'в',
  'не',
  'ни',
  'то',
  'же',
])

function rareBonus(seg: Set<string>, cit: Set<string>): number {
  let b = 0
  for (const w of seg) {
    if (w.length < 4 || STOP.has(w)) continue
    if (cit.has(w)) b += 0.04
  }
  return Math.min(b, 0.15)
}

function normalizeWhitespace(md: string): string {
  return md.replace(/\r\n/g, '\n')
}

/** Убрать модельные [N], чтобы не дублировать с инлайн-бейджами. */
export function stripBracketCitationNumbers(md: string): string {
  let t = normalizeWhitespace(md)
  t = t.replace(/\[(?:документ|doc|источник|файл|file|ref|ссылка)\s*\.?\s*(\d+)\s*\]/gi, '')
  t = t.replace(/\[(\d+(?:\s*,\s*\d+)+)\]/g, '')
  t = t.replace(/\[\d+\]/g, '')
  return t
}

function overlapText(a: string, b: string): number {
  const aa = a.trim().toLowerCase()
  const bb = b.trim().toLowerCase()
  if (aa.length < 8 || bb.length < 8) return 0
  if (aa.includes(bb.slice(0, Math.min(80, bb.length)))) return 0.6
  if (bb.includes(aa.slice(0, Math.min(80, aa.length)))) return 0.6
  const ta = tokenize(aa)
  const tb = tokenize(bb)
  return jaccard(ta, tb)
}

/** Какие citation_id допустимы для сегмента, если есть answer_blocks. */
function allowedIdsForSegment(
  segment: string,
  answerBlocks: AnswerBlockItem[] | undefined,
  allIds: Set<string>,
): Set<string> | null {
  if (!answerBlocks?.length) return null
  const allowed = new Set<string>()
  const seg = segment.trim()
  if (!seg) return allowed
  for (const b of answerBlocks) {
    const md = (b.markdown_text || '').trim()
    if (!md) continue
    const o = Math.max(overlapText(seg, md), overlapText(seg, md.slice(0, 200)))
    if (o > 0.12 || seg.includes(md.slice(0, 40)) || md.includes(seg.slice(0, 40))) {
      for (const id of b.citation_ids || []) {
        if (allIds.has(id)) allowed.add(id)
      }
    }
  }
  if (allowed.size === 0) {
    for (const b of answerBlocks) {
      for (const id of b.citation_ids || []) {
        if (allIds.has(id)) allowed.add(id)
      }
    }
  }
  return allowed
}

export interface LinkCitationsOptions {
  markdown: string
  sources: SourceInfo[]
  answerBlocks?: AnswerBlockItem[]
  minScore?: number
  secondGap?: number
}

export interface LinkCitationsResult {
  markdown: string
  orderedSources: SourceInfo[]
}

type MdPiece = { kind: 'text'; value: string } | { kind: 'code'; value: string }

/** Разделить markdown на чередование текста и fenced code (не вставляем маркеры в code). */
export function splitMarkdownTextAndFences(md: string): MdPiece[] {
  const text = normalizeWhitespace(md)
  const out: MdPiece[] = []
  let i = 0
  while (i < text.length) {
    const start = text.indexOf('```', i)
    if (start === -1) {
      if (i < text.length) out.push({ kind: 'text', value: text.slice(i) })
      break
    }
    if (start > i) out.push({ kind: 'text', value: text.slice(i, start) })
    const afterOpen = start + 3
    const close = text.indexOf('```', afterOpen)
    if (close === -1) {
      out.push({ kind: 'code', value: text.slice(start) })
      break
    }
    out.push({ kind: 'code', value: text.slice(start, close + 3) })
    i = close + 3
  }
  if (out.length === 0) out.push({ kind: 'text', value: text })
  return out
}

/**
 * Разбить текстовый фрагмент на сегменты (предложения и строки списков).
 */
export function segmentPlainTextForCitations(fragment: string): string[] {
  const acc: string[] = []
  const t = fragment.trim()
  if (!t) return acc

  const lines = t.split('\n')
  for (const line of lines) {
    const L = line.trim()
    if (!L) continue
    if (/^[-*+]\s+/.test(L) || /^\d+\.\s+/.test(L)) {
      acc.push(L)
      continue
    }
    const sents = L.split(/(?<=[.!?…])\s+/u)
    for (const s of sents) {
      const u = s.trim()
      if (u) acc.push(u)
    }
  }
  return acc.length ? acc : [t]
}

/** Индексы сегментов, где для citation_id нужно показать бейдж (последний в каждом «проходе» подряд). */
export function lastIndicesPerConsecutiveRuns(segmentIndices: number[]): Set<number> {
  const sorted = [...new Set(segmentIndices)].sort((a, b) => a - b)
  const mark = new Set<number>()
  let k = 0
  while (k < sorted.length) {
    let j = k
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j] + 1) j++
    mark.add(sorted[j])
    k = j + 1
  }
  return mark
}

function scoreSegmentForCitation(
  segTok: Set<string>,
  source: SourceInfo,
  citTok: Set<string>,
  segmentPlain: string,
): number {
  if (segmentPlain.length < 12) return 0
  let base = jaccard(segTok, citTok) + rareBonus(segTok, citTok)
  const qa = source.quote_anchor?.trim()
  if (qa && qa.length >= 8 && segmentPlain.includes(qa.slice(0, Math.min(30, qa.length)))) {
    base += 0.25
  }
  return Math.min(base, 1.2)
}

function pickCitationsForSegment(
  segment: string,
  sourcesWithId: SourceInfo[],
  allowed: Set<string> | null,
  minScore: number,
  secondGap: number,
): string[] {
  const segTok = segmentTokens(segment)
  const scored: { id: string; s: number }[] = []
  for (const src of sourcesWithId) {
    const id = src.citation_id!
    if (allowed && !allowed.has(id)) continue
    const citTok = citationTokens(src)
    const s = scoreSegmentForCitation(segTok, src, citTok, segment)
    if (s >= minScore) scored.push({ id, s })
  }
  scored.sort((a, b) => b.s - a.s)
  if (scored.length === 0) return []
  const top = scored[0]
  if (scored.length === 1 || top.s - scored[1].s >= secondGap) return [top.id]
  return [top.id, scored[1].id].filter((v, i, a) => a.indexOf(v) === i)
}

function appendMarkersAtEnd(
  segment: string,
  orderedCids: string[],
  getDisplay: (cid: string) => number,
): string {
  if (orderedCids.length === 0) return segment
  const markers = orderedCids.map((cid) => encodeCitationMarker(cid, getDisplay(cid))).join('')
  const m = segment.match(/([.!?…])(\s*)$/)
  if (m) {
    return segment.slice(0, -m[0].length) + m[1] + markers + m[2]
  }
  return segment + markers
}

export function linkCitationsInline(opts: LinkCitationsOptions): LinkCitationsResult {
  const {
    markdown,
    sources,
    answerBlocks,
    minScore = 0.08,
    secondGap = 0.06,
  } = opts

  const stripped = stripBracketCitationNumbers(markdown)
  const idToSource = new Map<string, SourceInfo>()
  const sourcesWithId = sources.filter((s) => s.citation_id)
  for (const s of sourcesWithId) {
    idToSource.set(s.citation_id!, s)
  }

  if (sourcesWithId.length === 0) {
    return { markdown: stripped, orderedSources: sources }
  }

  const allIds = new Set(sourcesWithId.map((s) => s.citation_id!))
  const globalCitationOrder: string[] = []
  const globalDisplayById = new Map<string, number>()
  const bumpDisplay = (cid: string): number => {
    if (!globalDisplayById.has(cid)) {
      globalCitationOrder.push(cid)
      globalDisplayById.set(cid, globalCitationOrder.length)
    }
    return globalDisplayById.get(cid)!
  }

  const pieces = splitMarkdownTextAndFences(stripped)
  const processedPieces: string[] = []

  for (const piece of pieces) {
    if (piece.kind === 'code') {
      processedPieces.push(piece.value)
      continue
    }

    const segments = segmentPlainTextForCitations(piece.value)
    if (segments.length === 0) {
      processedPieces.push(piece.value)
      continue
    }

    const perSeg: string[][] = segments.map((seg) =>
      pickCitationsForSegment(seg, sourcesWithId, allowedIdsForSegment(seg, answerBlocks, allIds), minScore, secondGap),
    )

    const idToSegIndices = new Map<string, number[]>()
    for (let i = 0; i < perSeg.length; i++) {
      for (const cid of perSeg[i]) {
        if (!idToSegIndices.has(cid)) idToSegIndices.set(cid, [])
        idToSegIndices.get(cid)!.push(i)
      }
    }

    const showMarkerOnSeg = new Set<string>()
    for (const [cid, indices] of idToSegIndices) {
      const lastInRuns = lastIndicesPerConsecutiveRuns(indices)
      for (const idx of lastInRuns) {
        if (perSeg[idx].includes(cid)) showMarkerOnSeg.add(`${idx}:${cid}`)
      }
    }

    const outSegs = segments.map((seg, i) => {
      const ids = perSeg[i].filter((cid) => showMarkerOnSeg.has(`${i}:${cid}`))
      if (ids.length === 0) return seg
      for (const cid of ids) bumpDisplay(cid)
      return appendMarkersAtEnd(seg, ids, (cid) => globalDisplayById.get(cid)!)
    })

    processedPieces.push(outSegs.join('\n\n'))
  }

  const outMd = processedPieces.join('')
  const orderedSources = globalCitationOrder.map((id) => idToSource.get(id)!).filter(Boolean)

  return {
    markdown: outMd,
    orderedSources: orderedSources.length ? orderedSources : sources,
  }
}
