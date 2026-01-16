import * as React from "react"
import { cn } from "@/lib/utils"
import { Reasoning, ReasoningContent, ReasoningTrigger } from "./reasoning"
import { Tool, ToolInput, ToolOutput } from "./tool"
import MessageContent from "../Chat/MessageContent"
import { SourceInfo } from "@/services/api"

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
      <div
        className={cn(
          "max-w-[75%] rounded-lg px-4 py-3 transition-all duration-150",
          role === "user"
            ? "bg-bg-elevated text-text-primary border border-border"
            : "bg-bg-secondary text-text-primary border border-border-subtle"
        )}
        style={{
          backgroundColor: role === "user" 
            ? 'var(--color-bg-elevated)' 
            : 'var(--color-bg-secondary)',
          color: 'var(--color-text-primary)',
          borderColor: role === "user"
            ? 'var(--color-border)'
            : 'var(--color-border-subtle)',
        }}
      >
        {children}
      </div>
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
  toolCalls?: Array<{
    name: string
    input?: any
    output?: any
    status?: "pending" | "running" | "completed" | "error"
  }>
  response?: string
  sources?: Array<{ title?: string; url?: string; page?: number; text_preview?: string; file?: string }>
  citations?: Array<{  // EnhancedCitation для подсветки
    source_id: string
    file_name: string
    page: number
    quote: string
    char_start: number
    char_end: number
    context_before?: string
    context_after?: string
  }>
  isStreaming?: boolean
  onSourceClick?: (source: { title?: string; url?: string; page?: number; file?: string; source_id?: string; char_start?: number; char_end?: number; quote?: string }) => void
  className?: string
  children?: React.ReactNode
}

export const AssistantMessage = React.memo(function AssistantMessage({
  content,
  reasoning,
  toolCalls,
  response,
  sources,
  citations,
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
        page: citation.page,
        text_preview: citation.quote,
        char_start: citation.char_start,
        char_end: citation.char_end,
        quote: citation.quote,
        source_id: citation.source_id,
        context_before: citation.context_before,
        context_after: citation.context_after,
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
  return (
    <Message role="assistant" className={className}>
      <div className="text-sm leading-relaxed prose prose-sm max-w-none">
        {/* Reasoning */}
        {reasoning && (
          <div className="mb-4">
            <Reasoning isStreaming={isStreaming}>
              <ReasoningTrigger />
              <ReasoningContent>{reasoning}</ReasoningContent>
            </Reasoning>
          </div>
        )}

        {/* Tool Calls */}
        {toolCalls && toolCalls.length > 0 && (
          <div className="mb-4 space-y-2">
            {toolCalls.map((toolCall, idx) => (
              <Tool
                key={idx}
                name={toolCall.name}
                status={toolCall.status || "completed"}
              >
                {toolCall.input && <ToolInput>{toolCall.input}</ToolInput>}
                {toolCall.output && <ToolOutput>{toolCall.output}</ToolOutput>}
              </Tool>
            ))}
          </div>
        )}

        {/* Main Content - с обработкой встроенных сносок */}
        {content && (
          <div className="mb-4">
            <MessageContent
              content={content}
              sources={effectiveSources}
              onCitationClick={(source) => {
                if (onSourceClick) {
                  onSourceClick({
                    file: source.file,
                    title: source.file || source.title,
                    page: source.page,
                    source_id: source.source_id,
                    char_start: source.char_start,
                    char_end: source.char_end,
                    quote: source.quote,
                  })
                }
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
              onCitationClick={(source) => {
                if (onSourceClick) {
                  onSourceClick({
                    file: source.file,
                    title: source.file || source.title,
                    page: source.page,
                    source_id: source.source_id,
                    char_start: source.char_start,
                    char_end: source.char_end,
                    quote: source.quote,
                  })
                }
              }}
              isStreaming={isStreaming}
            />
          </div>
        )}

        {/* Custom children (for PlanApprovalCard, etc.) */}
        {children}

        {/* Agent Steps will be rendered separately by EnhancedAgentStepsView */}
      </div>
    </Message>
  )
})

