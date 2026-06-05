import React, { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'
import type { SourceInfo } from '@/services/api'

export type AnswerBlockItem = {
  block_id: string
  markdown_text: string
  citation_ids: string[]
}

export type AnswerBlockCitation = {
  citation_id?: string
  source_id: string
  file_name: string
  page?: number
  quote?: string
  quote_anchor?: string
  text_preview?: string
  chunk_id?: string
  char_start?: number
  char_end?: number
  context_before?: string
  context_after?: string
  bbox?: { x0?: number; y0?: number; x1?: number; y1?: number }
  bbox_regions?: Array<{ x0?: number; y0?: number; x1?: number; y1?: number }>
  page_bbox?: { width?: number; height?: number }
  url?: string
  source_type?: string
}

/** SourceInfo из чата → каталог для AnswerBlocks (по citation_id). */
export function sourceInfosToAnswerBlockCitations(sources: SourceInfo[]): AnswerBlockCitation[] {
  return (sources ?? []).map((s) => ({
    citation_id: s.citation_id,
    source_id: s.source_id ?? '',
    file_name: s.file || s.title || 'Документ',
    page: s.page,
    quote: s.quote,
    quote_anchor: s.quote_anchor,
    chunk_id: s.chunk_id,
    char_start: s.char_start,
    char_end: s.char_end,
    context_before: s.context_before,
    context_after: s.context_after,
    bbox: s.bbox,
    bbox_regions: s.bbox_regions,
    page_bbox: s.page_bbox,
    url: s.url,
    source_type: s.source_type,
  }))
}

function citationToSourceInfo(c: AnswerBlockCitation): SourceInfo {
  return {
    file: c.file_name,
    title: c.file_name,
    page: c.page,
    citation_id: c.citation_id,
    text_preview: c.text_preview || c.quote_anchor || c.quote,
    quote_anchor: c.quote_anchor,
    quote: c.quote,
    chunk_id: c.chunk_id,
    char_start: c.char_start,
    char_end: c.char_end,
    context_before: c.context_before,
    context_after: c.context_after,
    bbox: c.bbox,
    bbox_regions: c.bbox_regions,
    page_bbox: c.page_bbox,
    url: c.url,
    source_type: c.source_type,
    source_id: c.source_id,
  }
}

const markdownComponents: Components = {
  a: ({ node: _node, ...props }) => (
    <a {...props} target="_blank" rel="noopener noreferrer" />
  ),
}

export interface AnswerBlocksProps {
  blocks: AnswerBlockItem[]
  citations: AnswerBlockCitation[]
  onCitationClick?: (source: SourceInfo) => void
  isStreaming?: boolean
}

export const AnswerBlocks = React.memo(function AnswerBlocks({
  blocks,
  citations,
  onCitationClick,
  isStreaming: _isStreaming,
}: AnswerBlocksProps) {
  const byId = useMemo(() => {
    const m = new Map<string, AnswerBlockCitation>()
    for (const c of citations || []) {
      const id = c.citation_id
      if (id) m.set(String(id), c)
    }
    return m
  }, [citations])

  // Stable numbering across the whole message:
  // citation_id -> global index (1..N) in the order citations[] are provided.
  // This avoids confusing per-block numbering where each block starts from "1".
  const globalIndexById = useMemo(() => {
    const m = new Map<string, number>()
    let n = 0
    for (const c of citations || []) {
      const id = c.citation_id
      if (!id) continue
      const sid = String(id)
      if (m.has(sid)) continue
      n += 1
      m.set(sid, n)
    }
    return m
  }, [citations])

  if (!blocks?.length) return null

  return (
    <div
      className="assistant-markdown space-y-4 text-sm leading-relaxed max-w-none"
      style={{ fontFamily: 'var(--font-body)', color: 'var(--color-text-primary)', fontSize: '0.9375rem' }}
    >
      {blocks.map((block) => (
        <div key={block.block_id} className="space-y-2">
          <div className="text-[var(--color-text-primary)] [&_a]:text-blue-600 [&_a]:underline">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {block.markdown_text || ''}
            </ReactMarkdown>
          </div>
          {block.citation_ids?.length ? (
            <div className="flex flex-wrap gap-1.5 not-prose">
              {[...(block.citation_ids || [])]
                .sort((a, b) => {
                  const ia = globalIndexById.get(String(a)) ?? 99999
                  const ib = globalIndexById.get(String(b)) ?? 99999
                  return ia - ib || String(a).localeCompare(String(b))
                })
                .map((cid, idx) => {
                const c = byId.get(String(cid))
                const globalIdx = globalIndexById.get(String(cid))
                const label = String(globalIdx ?? (idx + 1))
                return (
                  <button
                    key={`${block.block_id}-${cid}-${idx}`}
                    type="button"
                    className="inline-flex min-h-[1.35rem] min-w-[1.35rem] items-center justify-center rounded-full border px-2 text-[0.65rem] font-bold transition-colors"
                    style={{
                      borderColor: 'color-mix(in srgb, var(--color-accent) 32%, var(--color-border))',
                      color: 'var(--color-accent)',
                      backgroundColor: 'color-mix(in srgb, var(--color-accent) 12%, var(--color-bg-elevated))',
                      boxShadow: '0 1px 2px color-mix(in srgb, var(--color-text-primary) 6%, transparent)',
                    }}
                    title={c?.file_name || `Источник ${label}`}
                    aria-label={`Открыть источник ${label}`}
                    onClick={() => {
                      if (!c || !onCitationClick) return
                      onCitationClick(citationToSourceInfo(c))
                    }}
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  )
})
