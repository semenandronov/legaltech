import React from 'react'
import {
  InlineCitation,
  InlineCitationText,
  InlineCitationCard,
  InlineCitationCardTrigger,
  InlineCitationCardBody,
  InlineCitationCarousel,
  InlineCitationCarouselContent,
  InlineCitationCarouselItem,
  InlineCitationSource,
  InlineCitationQuote,
} from '../ai-elements/inline-citation'
import { SourceInfo } from '@/services/api'

interface InlineCitationAdapterProps {
  index: number
  sources: SourceInfo[]
  onClick?: (source: SourceInfo) => void
}

export const InlineCitationAdapter: React.FC<InlineCitationAdapterProps> = ({
  index,
  sources,
  onClick,
}) => {
  const source = sources[index - 1] // Citations are 1-indexed

  if (!source) {
    return (
      <InlineCitation>
        <InlineCitationText className="text-gray-500">[{index}]</InlineCitationText>
      </InlineCitation>
    )
  }

  // Format short document name
  const formatShortName = (filename: string): string => {
    let name = filename.replace(/\.[^/.]+$/, '') // Remove extension
    const parts = name.split(/[_\-]/)
    if (parts.length > 2) {
      const dateMatch = parts.find(p => /^\d{8}$/.test(p))
      const typeMatch = parts.find(p => p.length > 5 && !/^\d+$/.test(p))
      if (dateMatch && typeMatch) {
        return `${typeMatch.substring(0, 12)}`
      }
    }
    return name.substring(0, 15)
  }

  const shortName = formatShortName(source.file)
  const pageInfo = source.page ? ` стр.${source.page}` : ''
  const displayText = `${shortName}${pageInfo}`

  // Create full URL for the source (InlineCitationCardTrigger needs full URL for hostname extraction)
  const sourceUrl = source.file 
    ? (source.file.startsWith('http') 
        ? source.file 
        : `${window.location.origin}/api/files/${encodeURIComponent(source.file)}`)
    : window.location.href

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (onClick) {
      onClick(source)
    }
  }

  return (
    <InlineCitation>
      <InlineCitationText>{displayText}</InlineCitationText>
      <InlineCitationCard>
        <InlineCitationCardTrigger 
          sources={[sourceUrl]}
          onClick={handleClick}
          className="cursor-pointer"
        />
        <InlineCitationCardBody>
          <InlineCitationCarousel>
            <InlineCitationCarouselContent>
              <InlineCitationCarouselItem>
                <InlineCitationSource
                  title={source.file}
                  url={sourceUrl}
                  description={
                    source.text_preview 
                      ? (source.text_preview.length > 200 
                          ? source.text_preview.substring(0, 200) + '...' 
                          : source.text_preview)
                      : undefined
                  }
                >
                  {source.page && (
                    <div className="text-xs text-muted-foreground mt-1">
                      Страница {source.page}
                    </div>
                  )}
                  {source.similarity_score !== undefined && (
                    <div className="text-xs text-green-600 mt-1">
                      Релевантность: {Math.round(source.similarity_score * 100)}%
                    </div>
                  )}
                  {source.text_preview && (
                    <InlineCitationQuote className="mt-2">
                      {source.text_preview.length > 200
                        ? source.text_preview.substring(0, 200) + '...'
                        : source.text_preview}
                    </InlineCitationQuote>
                  )}
                </InlineCitationSource>
              </InlineCitationCarouselItem>
            </InlineCitationCarouselContent>
          </InlineCitationCarousel>
        </InlineCitationCardBody>
      </InlineCitationCard>
    </InlineCitation>
  )
}

