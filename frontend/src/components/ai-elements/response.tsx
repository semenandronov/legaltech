import * as React from "react"
import { cn } from "@/lib/utils"
import { FileText, CheckCircle2 } from "lucide-react"
import { Card, CardContent, CardHeader } from "@/components/UI/Card"
import ReactMarkdown from "react-markdown"
import { SourcePreview } from "@/components/Chat/SourcePreview"

// Animation styles
const fadeIn = "animate-in fade-in slide-in-from-left-2 duration-300"

export interface ResponseProps {
  children: React.ReactNode
  className?: string
  status?: "pending" | "completed" | "error"
}

export function Response({ 
  children, 
  className,
  status = "completed"
}: ResponseProps) {
  const statusColors = {
    pending: "border-gray-200 bg-gray-50",
    completed: "border-green-200 bg-green-50",
    error: "border-red-200 bg-red-50"
  }

  return (
    <Card className={cn("border transition-all", fadeIn, statusColors[status], className)}>
      <CardHeader>
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-green-600" />
          <span className="text-sm font-semibold">Результат</span>
          {status === "completed" && (
            <CheckCircle2 className="w-4 h-4 text-green-600 ml-auto" />
          )}
        </div>
      </CardHeader>
      <CardContent>
        {children}
      </CardContent>
    </Card>
  )
}

export interface ResponseContentProps {
  children: React.ReactNode
  className?: string
  markdown?: boolean
}

export function ResponseContent({ 
  children, 
  className,
  markdown = true
}: ResponseContentProps) {
  if (markdown && typeof children === 'string') {
    return (
      <div className={cn("prose prose-sm max-w-none", className)}>
        <ReactMarkdown>{children}</ReactMarkdown>
      </div>
    )
  }

  return (
    <div className={cn("text-sm text-gray-700 leading-relaxed whitespace-pre-wrap", className)}>
      {children}
    </div>
  )
}

export interface ResponseSourcesProps {
  sources?: Array<{ title?: string; url?: string; page?: number; text_preview?: string; file?: string }>
  className?: string
  onSourceClick?: (source: { title?: string; url?: string; page?: number; file?: string }) => void
}

export function ResponseSources({ sources, className, onSourceClick }: ResponseSourcesProps) {
  if (!sources || sources.length === 0) {
    return null
  }

  return (
    <div className={cn("mt-4 pt-4 border-t border-gray-200", className)}>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
          Использовано {sources.length} {sources.length === 1 ? 'источник' : sources.length < 5 ? 'источника' : 'источников'}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {sources.map((source, index) => {
          const href = source.url || '#'
          const title = source.title || source.file || `Источник ${index + 1}`
          const displayText = `${title}${source.page ? ` (стр. ${source.page})` : ''}`
          
          const sourceElement = (
            <a
              key={index}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium bg-blue-50 text-blue-700 rounded-md hover:bg-blue-100 transition-colors cursor-pointer"
              onClick={(e) => {
                if (onSourceClick && source.file) {
                  e.preventDefault()
                  onSourceClick(source)
                }
              }}
            >
              <span>{displayText}</span>
              {source.page && (
                <span className="text-blue-500">• стр. {source.page}</span>
              )}
            </a>
          )

          // Wrap with SourcePreview if we have preview data
          if (source.text_preview || source.file) {
            return (
              <SourcePreview
                key={index}
                source={source}
                onOpenDocument={onSourceClick}
              >
                {sourceElement}
              </SourcePreview>
            )
          }

          return sourceElement
        })}
      </div>
    </div>
  )
}

