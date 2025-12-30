import * as React from "react"
import { cn } from "@/lib/utils"
import { FileText, CheckCircle2 } from "lucide-react"
import { Card, CardContent, CardHeader } from "@/components/UI/Card"
import ReactMarkdown from "react-markdown"

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
  sources?: Array<{ title?: string; url?: string; page?: number }>
  className?: string
}

export function ResponseSources({ sources, className }: ResponseSourcesProps) {
  if (!sources || sources.length === 0) {
    return null
  }

  return (
    <div className={cn("mt-4 pt-4 border-t border-gray-200", className)}>
      <div className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">
        Источники
      </div>
      <div className="space-y-1">
        {sources.map((source, index) => (
          <div key={index} className="text-xs text-gray-600">
            {source.title && <span className="font-medium">{source.title}</span>}
            {source.page && <span className="text-gray-500"> (стр. {source.page})</span>}
            {source.url && (
              <a 
                href={source.url} 
                target="_blank" 
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline ml-2"
              >
                Открыть
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

