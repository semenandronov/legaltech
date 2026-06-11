import * as React from "react"
import { cn } from "@/lib/utils"
import { Reasoning, ReasoningContent, ReasoningTrigger } from "./reasoning"
import MessageContent from "../Chat/MessageContent"
import { AnswerBlocks, type AnswerBlockItem, type AnswerBlockCitation } from "../Chat/AnswerBlocks"
import { SourceInfo } from "@/services/api"
import { ThinkingBlock, ThinkingStep } from "../Chat/ThinkingBlock"

type CitationRef = { citation_id?: string }

function _catalogOrderMap(citations: CitationRef[]): Map<string, number> {
  const m = new Map<string, number>()
  citations.forEach((c, i) => {
    const id = c.citation_id
    if (id && !m.has(String(id))) m.set(String(id), i)
  })
  return m
}

/** Уникальные citation_id в порядке чтения ответа; нумерация чипов будет 1…N. */
function _citationIdsReadingOrder(blocks: AnswerBlockItem[], catalog: CitationRef[]): string[] {
  const pos = _catalogOrderMap(catalog)
  const out: string[] = []
  const seen = new Set<string>()
  for (const b of blocks) {
    const ids = [...(b.citation_ids || [])].sort(
      (a, x) => (pos.get(String(a)) ?? 99999) - (pos.get(String(x)) ?? 99999),
    )
    for (const cid of ids) {
      const s = String(cid)
      if (seen.has(s)) continue
      seen.add(s)
      out.push(s)
    }
  }
  return out
}

// Animation styles - subtle fade in (Harvey style)
const fadeIn = "animate-fade-in"

export interface MessageProps {
  children: React.ReactNode
  role: "user" | "assistant"
  className?: string
}

export function Message({ children, role, className }: MessageProps) {
  return (
    <div
      className={cn(
        "flex mb-4",
        role === "user" ? "justify-end" : "justify-start",
        fadeIn,
        className
      )}
    >
      {role === "user" ? (
        <div
          className="max-w-[75%] rounded-2xl px-4 py-3 transition-all duration-150 font-body"
          style={{
            backgroundColor: 'var(--color-user-message-bg)',
            color: 'var(--color-user-message-text)',
            fontFamily: 'var(--font-body)',
          }}
        >
          {children}
        </div>
      ) : (
        <div
          className="max-w-[min(90%,42rem)] w-full font-body"
          style={{
            color: 'var(--color-text-primary)',
            fontFamily: 'var(--font-body)',
          }}
        >
          {children}
        </div>
      )}
    </div>
  )
}

export interface UserMessageProps {
  content: string
  className?: string
}

export const UserMessage = React.memo(function UserMessage({ content, className }: UserMessageProps) {
  return (
    <Message role="user" className={className}>
      <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
        {content}
      </div>
    </Message>
  )
})

export interface AssistantMessageProps {
  content?: string
  reasoning?: string
  reasoningSteps?: ThinkingStep[]  // Пошаговое мышление
  toolCalls?: Array<{
    name: string
    input?: any
    output?: any
    status?: "pending" | "running" | "completed" | "error"
  }>
  response?: string
  sources?: Array<{ title?: string; url?: string; page?: number; text_preview?: string; file?: string }>
  citations?: Array<{  // EnhancedCitation для подсветки
    citation_id?: string
    source_id: string
    file_name: string
    page?: number
    quote: string
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
  }>
  /** Phase 2: блоки для чипов цитат; при уже набранном тексте ответа не подменяют markdown — только для линкера/MessageContent */
  answerBlocks?: AnswerBlockItem[]
  /** Как у глобального ассистента: цитаты без linkCitationsInline (внутренний ассистент по делу). */
  preferLegacyCitations?: boolean
  isStreaming?: boolean
  /** Полный SourceInfo из inline-цитаты / блоков — не сужать, иначе теряются bbox_regions и текст для PDF. */
  onSourceClick?: (source: SourceInfo) => void
  className?: string
  children?: React.ReactNode
}

export const AssistantMessage = React.memo(function AssistantMessage({
  content,
  reasoning,
  reasoningSteps,
  toolCalls,
  response,
  sources,
  citations,
  answerBlocks,
  preferLegacyCitations = false,
  isStreaming = false,
  className,
  children,
  onSourceClick,
}: AssistantMessageProps) {
  // Преобразуем citations в SourceInfo[] для использования в MessageContent
  const effectiveSources: SourceInfo[] = React.useMemo(() => {
    if (citations && citations.length > 0) {
      // Преобразуем EnhancedCitation в SourceInfo
      return citations.map(citation => ({
        file: citation.file_name,
        title: citation.file_name,
        page: (citation.page ?? (citation as any).source_page) ?? undefined,
        citation_id: citation.citation_id,
        text_preview: citation.text_preview || citation.quote_anchor || citation.quote,
        quote_anchor: citation.quote_anchor,
        chunk_id: citation.chunk_id,
        char_start: citation.char_start,
        char_end: citation.char_end,
        quote: citation.quote,
        source_id: citation.source_id,
        context_before: citation.context_before,
        context_after: citation.context_after,
        bbox: citation.bbox,
        bbox_regions: citation.bbox_regions,
        page_bbox: citation.page_bbox,
        url: citation.url,
        source_type: citation.source_type,
      }))
    } else if (sources) {
      // Используем обычные sources если citations нет
      return sources.map(s => ({
        file: s.file || s.title || '',
        title: s.title || s.file || '',
        page: s.page,
        text_preview: s.text_preview,
      }))
    }
    return []
  }, [citations, sources])

  const citationsForBlockChips = React.useMemo(() => {
    if (!citations?.length) return []
    if (!answerBlocks?.length) return citations
    const order = _citationIdsReadingOrder(answerBlocks, citations)
    const byId = new Map(
      citations.filter((c) => c.citation_id).map((c) => [String(c.citation_id), c]),
    )
    return order.map((id) => byId.get(id)).filter((c): c is NonNullable<typeof citations[number]> => c != null)
  }, [citations, answerBlocks])

  const citeForBlocks: AnswerBlockCitation[] = React.useMemo(() => {
    if (!citationsForBlockChips.length) return []
    return citationsForBlockChips.map((c) => ({
      citation_id: c.citation_id,
      source_id: c.source_id,
      file_name: c.file_name,
      page: c.page,
      quote: c.quote,
      quote_anchor: c.quote_anchor,
      text_preview: c.text_preview,
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
    }))
  }, [citationsForBlockChips])

  /** Не подменяем потоковый ответ отдельной вёрсткой: при уже набранном тексте цитаты дорастают в том же markdown (линкер + CITE). */
  const hasStreamedBody = Boolean(
    (content && content.trim().length > 0) || (response && response.trim().length > 0),
  )
  const showAnswerBlocks = Boolean(answerBlocks?.length) && !hasStreamedBody

  return (
    <Message role="assistant" className={className}>
      <div className="text-sm leading-relaxed prose prose-sm max-w-none" style={{ fontFamily: 'var(--font-body)' }}>
        {/* Unified reasoning + tool calls display (Leya-style) */}
        {((toolCalls && toolCalls.length > 0) ||
          (reasoningSteps && reasoningSteps.length > 0) ||
          (isStreaming && !content)) && (
          <ThinkingBlock
            steps={reasoningSteps || []}
            toolCalls={toolCalls}
            isStreaming={isStreaming && !content}
            defaultOpen={true}
          />
        )}

        {/* Legacy Reasoning (для обратной совместимости) */}
        {reasoning && !reasoningSteps?.length && !toolCalls?.length && (
          <div className="mb-4">
            <Reasoning isStreaming={isStreaming}>
              <ReasoningTrigger />
              <ReasoningContent>{reasoning}</ReasoningContent>
            </Reasoning>
          </div>
        )}

        {showAnswerBlocks ? (
          <div className="mb-4">
            <AnswerBlocks
              blocks={answerBlocks!}
              citations={citeForBlocks}
              isStreaming={isStreaming}
              onCitationClick={(source) => {
                if (onSourceClick) onSourceClick(source)
              }}
            />
          </div>
        ) : (
          <>
            {/* Main Content - с обработкой встроенных сносок */}
            {content && (
              <div className="mb-4">
                <MessageContent
                  content={content}
                  sources={effectiveSources}
                  answerBlocks={answerBlocks}
                  preferLegacyCitations={preferLegacyCitations}
                  onCitationClick={(source) => {
                    if (onSourceClick) onSourceClick(source)
                  }}
                  isStreaming={isStreaming}
                />
              </div>
            )}

            {/* Response */}
            {response && (
              <div className="mb-4">
                <MessageContent
                  content={response}
                  sources={effectiveSources}
                  answerBlocks={answerBlocks}
                  preferLegacyCitations={preferLegacyCitations}
                  onCitationClick={(source) => {
                    if (onSourceClick) onSourceClick(source)
                  }}
                  isStreaming={isStreaming}
                />
              </div>
            )}
          </>
        )}

        {/* Custom children (for PlanApprovalCard, etc.) */}
        {children}

        {/* Agent Steps will be rendered separately by EnhancedAgentStepsView */}
      </div>
    </Message>
  )
})

