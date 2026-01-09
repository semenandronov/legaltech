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

  // Use quote if available, otherwise fallback to text_preview
  const quoteText = source.quote || source.text_preview || ''

  return (
    <InlineCitation>
      <InlineCitationText>[{index}]</InlineCitationText>
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
                    quoteText 
                      ? (quoteText.length > 200 
                          ? quoteText.substring(0, 200) + '...' 
                          : quoteText)
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
                  {quoteText && (
                    <InlineCitationQuote className="mt-2">
                      {quoteText.length > 200
                        ? quoteText.substring(0, 200) + '...'
                        : quoteText}
                    </InlineCitationQuote>
                  )}
                  {(source.char_start !== undefined && source.char_end !== undefined) && (
                    <div className="text-xs text-muted-foreground mt-1">
                      Позиция: {source.char_start}–{source.char_end}
                    </div>
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

