import * as React from "react"
import { cn } from "@/lib/utils"
import ReactMarkdown from "react-markdown"
import { Reasoning, ReasoningContent, ReasoningTrigger } from "./reasoning"
import { Tool, ToolInput, ToolOutput } from "./tool"
import { Response, ResponseContent, ResponseSources } from "./response"

// Animation styles
const fadeIn = "animate-in fade-in slide-in-from-bottom-2 duration-300"

export interface MessageProps {
  children: React.ReactNode
  role: "user" | "assistant"
  className?: string
}

export function Message({ children, role, className }: MessageProps) {
  return (
    <div
      className={cn(
        "flex",
        role === "user" ? "justify-end" : "justify-start",
        fadeIn,
        className
      )}
    >
      <div
        className={cn(
          "max-w-[75%] rounded-2xl px-4 py-3 transition-all",
          role === "user"
            ? "bg-blue-600 text-white"
            : "bg-gray-100 text-gray-800"
        )}
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
  sources?: Array<{ title?: string; url?: string; page?: number }>
  isStreaming?: boolean
  className?: string
  children?: React.ReactNode
}

export const AssistantMessage = React.memo(function AssistantMessage({
  content,
  reasoning,
  toolCalls,
  response,
  sources,
  isStreaming = false,
  className,
  children,
}: AssistantMessageProps) {
  const markdownComponents = {
    p: ({ children }: any) => <p className="mb-3 last:mb-0">{children}</p>,
    h1: ({ children }: any) => (
      <h1 className="text-xl font-bold mb-3 mt-4 first:mt-0">{children}</h1>
    ),
    h2: ({ children }: any) => (
      <h2 className="text-lg font-semibold mb-2 mt-3 first:mt-0">{children}</h2>
    ),
    h3: ({ children }: any) => (
      <h3 className="text-base font-semibold mb-2 mt-3 first:mt-0">{children}</h3>
    ),
    ul: ({ children }: any) => (
      <ul className="list-disc list-inside mb-3 space-y-1">{children}</ul>
    ),
    ol: ({ children }: any) => (
      <ol className="list-decimal list-inside mb-3 space-y-1">{children}</ol>
    ),
    li: ({ children }: any) => <li className="ml-2">{children}</li>,
    code: ({ children, className }: any) => {
      const isInline = !className
      return isInline ? (
        <code className="bg-gray-200 dark:bg-gray-700 px-1.5 py-0.5 rounded text-xs font-mono">
          {children}
        </code>
      ) : (
        <code className="block bg-gray-200 dark:bg-gray-700 p-3 rounded text-xs font-mono overflow-x-auto mb-3">
          {children}
        </code>
      )
    },
    pre: ({ children }: any) => (
      <pre className="bg-gray-200 dark:bg-gray-700 p-3 rounded text-xs font-mono overflow-x-auto mb-3">
        {children}
      </pre>
    ),
    strong: ({ children }: any) => (
      <strong className="font-semibold">{children}</strong>
    ),
    em: ({ children }: any) => <em className="italic">{children}</em>,
    table: ({ children }: any) => (
      <div className="overflow-x-auto mb-3">
        <table className="min-w-full border-collapse border border-gray-300">
          {children}
        </table>
      </div>
    ),
    thead: ({ children }: any) => (
      <thead className="bg-gray-200">{children}</thead>
    ),
    tbody: ({ children }: any) => <tbody>{children}</tbody>,
    tr: ({ children }: any) => (
      <tr className="border-b border-gray-200">{children}</tr>
    ),
    th: ({ children }: any) => (
      <th className="border border-gray-300 px-3 py-2 text-left font-semibold">
        {children}
      </th>
    ),
    td: ({ children }: any) => (
      <td className="border border-gray-300 px-3 py-2">{children}</td>
    ),
    blockquote: ({ children }: any) => (
      <blockquote className="border-l-4 border-gray-400 pl-4 italic my-3">
        {children}
      </blockquote>
    ),
  }

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

        {/* Main Content */}
        {content && (
          <div className="mb-4">
            <ReactMarkdown components={markdownComponents}>
              {content || "..."}
            </ReactMarkdown>
          </div>
        )}

        {/* Response */}
        {response && (
          <div className="mb-4">
            <Response status="completed">
              <ResponseContent markdown={true}>{response}</ResponseContent>
              {sources && sources.length > 0 && (
                <ResponseSources sources={sources} />
              )}
            </Response>
          </div>
        )}

        {/* Custom children (for PlanApprovalCard, etc.) */}
        {children}

        {/* Agent Steps will be rendered separately by EnhancedAgentStepsView */}
      </div>
    </Message>
  )
})

