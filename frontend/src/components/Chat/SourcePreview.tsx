import React from 'react'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '../UI/tooltip'
import { FileText, ExternalLink } from 'lucide-react'

interface SourcePreviewProps {
  source: {
    file?: string
    title?: string
    url?: string
    page?: number
    text_preview?: string
  }
  onOpenDocument?: (source: SourcePreviewProps['source']) => void
  children: React.ReactNode
}

export const SourcePreview: React.FC<SourcePreviewProps> = ({
  source,
  onOpenDocument,
  children,
}) => {
  const displayTitle = source.title || source.file || 'Источник'
  const pageInfo = source.page ? ` (стр. ${source.page})` : ''

  return (
    <TooltipProvider>
      <Tooltip delayDuration={300}>
        <TooltipTrigger asChild>
          {children}
        </TooltipTrigger>
        <TooltipContent 
          side="top" 
          className="max-w-sm p-0 bg-white border border-gray-200 shadow-lg rounded-lg"
        >
          <div className="p-3">
            <div className="flex items-start justify-between gap-2 mb-2">
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <FileText className="w-4 h-4 text-gray-500 flex-shrink-0" />
                <span className="text-sm font-medium text-gray-900 truncate">
                  {displayTitle}
                </span>
              </div>
              {source.page && (
                <span className="text-xs text-gray-500 flex-shrink-0">
                  стр. {source.page}
                </span>
              )}
            </div>
            
            {source.text_preview && (
              <div className="mb-3">
                <p className="text-xs text-gray-600 line-clamp-3">
                  {source.text_preview}
                </p>
              </div>
            )}
            
            <div className="flex items-center gap-2 pt-2 border-t border-gray-100">
              {onOpenDocument && (
                <button
                  onClick={(e) => {
                    e.preventDefault()
                    onOpenDocument(source)
                  }}
                  className="flex items-center gap-1.5 px-2 py-1 text-xs font-medium text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded transition-colors"
                >
                  <ExternalLink className="w-3 h-3" />
                  Открыть документ
                </button>
              )}
              {source.url && (
                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 px-2 py-1 text-xs font-medium text-gray-600 hover:text-gray-700 hover:bg-gray-50 rounded transition-colors"
                  onClick={(e) => e.stopPropagation()}
                >
                  <ExternalLink className="w-3 h-3" />
                  Открыть ссылку
                </a>
              )}
            </div>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

