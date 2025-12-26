import React, { useState, useEffect } from 'react'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/UI/sheet'
import { Button } from '@/components/UI/Button'
import { Badge } from '@/components/UI/Badge'
import { ScrollArea } from '@/components/UI/scroll-area'
import { Separator } from '@/components/UI/separator'
import { 
  FileText, 
  Download, 
  Copy, 
  Check,
  ChevronLeft,
  ChevronRight,
  Maximize2
} from 'lucide-react'
import { SourceInfo } from '@/services/api'

interface DocumentPreviewSheetProps {
  isOpen: boolean
  onClose: () => void
  source: SourceInfo | null
  caseId: string
  allSources?: SourceInfo[]
  onNavigate?: (source: SourceInfo) => void
}

const DocumentPreviewSheet: React.FC<DocumentPreviewSheetProps> = ({
  isOpen,
  onClose,
  source,
  caseId,
  allSources = [],
  onNavigate
}) => {
  const [copied, setCopied] = useState(false)
  const [documentContent, setDocumentContent] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const currentIndex = source ? allSources.findIndex(s => s.file === source.file) : -1
  const hasPrev = currentIndex > 0
  const hasNext = currentIndex < allSources.length - 1

  useEffect(() => {
    if (source && isOpen) {
      loadDocumentContent()
    }
  }, [source, isOpen])

  const loadDocumentContent = async () => {
    if (!source) return
    
    setLoading(true)
    try {
      // Try to get document content from API
      const response = await fetch(`/api/cases/${caseId}/files/${encodeURIComponent(source.file)}/content`)
      if (response.ok) {
        const data = await response.json()
        setDocumentContent(data.content || source.text_preview || '')
      } else {
        // Fallback to text_preview
        setDocumentContent(source.text_preview || 'Содержимое документа недоступно для предпросмотра')
      }
    } catch (error) {
      setDocumentContent(source.text_preview || 'Ошибка загрузки содержимого')
    } finally {
      setLoading(false)
    }
  }

  const handleCopy = async () => {
    if (documentContent) {
      await navigator.clipboard.writeText(documentContent)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handlePrev = () => {
    if (hasPrev && onNavigate) {
      onNavigate(allSources[currentIndex - 1])
    }
  }

  const handleNext = () => {
    if (hasNext && onNavigate) {
      onNavigate(allSources[currentIndex + 1])
    }
  }


  if (!source) return null

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <SheetContent 
        side="right" 
        className="w-full sm:max-w-xl lg:max-w-2xl p-0 flex flex-col"
      >
        {/* Header */}
        <div className="p-4 border-b bg-muted/30">
          <SheetHeader>
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <SheetTitle className="text-base font-semibold truncate flex items-center gap-2">
                  <FileText className="h-4 w-4 shrink-0 text-primary" />
                  <span className="truncate">{source.file}</span>
                </SheetTitle>
                <SheetDescription className="mt-1 flex items-center gap-2 flex-wrap">
                  {source.page && (
                    <Badge variant="secondary" className="text-xs">
                      Стр. {source.page}
                    </Badge>
                  )}
                  {source.similarity_score !== undefined && (
                    <Badge 
                      variant={source.similarity_score > 0.7 ? "default" : "secondary"}
                      className="text-xs"
                    >
                      {Math.round(source.similarity_score * 100)}% релевантность
                    </Badge>
                  )}
                </SheetDescription>
              </div>
            </div>
          </SheetHeader>
          
          {/* Navigation & Actions */}
          <div className="flex items-center justify-between mt-3 pt-3 border-t border-border/50">
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                onClick={handlePrev}
                disabled={!hasPrev}
                className="h-8 px-2"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="text-xs text-muted-foreground px-2">
                {currentIndex + 1} / {allSources.length}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleNext}
                disabled={!hasNext}
                className="h-8 px-2"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
            
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCopy}
                className="h-8 px-2"
              >
                {copied ? (
                  <Check className="h-4 w-4 text-green-500" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                asChild
                className="h-8 px-2"
              >
                <a 
                  href={`/api/cases/${caseId}/files/${encodeURIComponent(source.file)}/download`}
                  download
                >
                  <Download className="h-4 w-4" />
                </a>
              </Button>
              <Button
                variant="ghost"
                size="sm"
                asChild
                className="h-8 px-2"
              >
                <a 
                  href={`/cases/${caseId}/workspace?file=${encodeURIComponent(source.file)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Maximize2 className="h-4 w-4" />
                </a>
              </Button>
            </div>
          </div>
        </div>

        {/* Content */}
        <ScrollArea className="flex-1">
          <div className="p-4">
            {loading ? (
              <div className="space-y-3">
                <div className="h-4 bg-muted rounded animate-pulse" />
                <div className="h-4 bg-muted rounded animate-pulse w-3/4" />
                <div className="h-4 bg-muted rounded animate-pulse w-1/2" />
              </div>
            ) : (
              <>
                {source.text_preview && (
                  <div className="bg-primary/5 border border-primary/20 rounded-lg p-4 mb-4">
                    <div className="flex items-center gap-2 text-xs text-primary font-medium mb-2">
                      <span className="inline-block w-2 h-2 rounded-full bg-primary animate-pulse" />
                      Цитируемый фрагмент
                    </div>
                    <p className="text-sm leading-relaxed">
                      {source.text_preview}
                    </p>
                  </div>
                )}
                
                {documentContent && documentContent !== source.text_preview && (
                  <>
                    <Separator className="my-4" />
                    <div className="text-xs text-muted-foreground mb-2 font-medium">
                      Полный текст документа:
                    </div>
                    <div className="text-sm leading-relaxed whitespace-pre-wrap text-muted-foreground">
                      {documentContent}
                    </div>
                  </>
                )}
              </>
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  )
}

export default DocumentPreviewSheet

