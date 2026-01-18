import React from 'react'
import {
  InlineCitation,
  InlineCitationCard,
  InlineCitationCardBody,
  InlineCitationCarousel,
  InlineCitationCarouselContent,
  InlineCitationCarouselItem,
  InlineCitationSource,
  InlineCitationQuote,
} from '../ai-elements/inline-citation'
import { SourceInfo } from '@/services/api'
import { HoverCardTrigger } from '@/components/UI/hover-card'

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
      <span className="text-gray-400 cursor-default">[{index}]</span>
    )
  }

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (onClick) {
      onClick(source)
    }
  }

  // Use quote if available, otherwise fallback to text_preview
  const quoteText = source.quote || source.text_preview || ''
  
  // Format short file name for display
  const shortFileName = source.file 
    ? source.file.replace(/\.[^/.]+$/, '').substring(0, 30) + (source.file.length > 30 ? '...' : '')
    : 'Документ'

  // Perplexity/Harvey style - компактный inline badge
  return (
    <InlineCitation>
      <InlineCitationCard>
        <HoverCardTrigger asChild>
          <span 
            className="inline-flex items-center justify-center w-5 h-5 text-[10px] font-semibold text-blue-700 bg-blue-50 border border-blue-200 rounded-full cursor-pointer hover:bg-blue-100 hover:border-blue-300 transition-all duration-150 align-super ml-0.5 shadow-sm"
            onClick={handleClick}
            style={{ 
              verticalAlign: 'super',
              fontSize: '10px',
              lineHeight: 1,
              marginTop: '-2px'
            }}
          >
            {index}
          </span>
        </HoverCardTrigger>
        <InlineCitationCardBody>
          <InlineCitationCarousel>
            <InlineCitationCarouselContent>
              <InlineCitationCarouselItem>
                <InlineCitationSource
                  title={shortFileName}
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
                      📄 Страница {source.page}
                    </div>
                  )}
                  {quoteText && (
                    <InlineCitationQuote className="mt-2">
                      "{quoteText.length > 150
                        ? quoteText.substring(0, 150) + '...'
                        : quoteText}"
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

