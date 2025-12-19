import React, { useState } from 'react'
import { TimelineEvent } from '../../services/api'
import ConfidenceBadge from '../Common/ConfidenceBadge'
import './Timeline.css'

interface TimelineEventComponentProps {
  event: TimelineEvent
  onClick?: () => void
  onDocumentClick?: (filename: string) => void
}

const TimelineEventComponent: React.FC<TimelineEventComponentProps> = ({
  event,
  onClick,
  onDocumentClick
}) => {
  const [showDetails, setShowDetails] = useState(false)

  const confidence = event.metadata?.confidence
    ? (typeof event.metadata.confidence === 'string'
        ? parseFloat(event.metadata.confidence)
        : event.metadata.confidence * 100)
    : null

  const reasoning = event.metadata?.reasoning

  return (
    <div
      className="timeline-event"
      onClick={onClick}
      style={{ cursor: onClick ? 'pointer' : 'default' }}
    >
      <div className="timeline-event-header">
        <div className="timeline-event-date">
          {new Date(event.date).toLocaleDateString('ru-RU', {
            day: 'numeric',
            month: 'short',
            year: 'numeric'
          })}
        </div>
        {event.event_type && (
          <span className="timeline-event-type">{event.event_type}</span>
        )}
        {confidence !== null && (
          <ConfidenceBadge confidence={confidence} size="small" />
        )}
      </div>

      <div className="timeline-event-description">
        {event.description}
      </div>

      <div className="timeline-event-source">
        <span className="timeline-event-source-label">Source:</span>
        <span
          className="timeline-event-source-document"
          onClick={(e) => {
            e.stopPropagation()
            onDocumentClick?.(event.source_document)
          }}
          style={{ cursor: onDocumentClick ? 'pointer' : 'default' }}
        >
          📄 {event.source_document}
        </span>
        {event.source_page && (
          <span className="timeline-event-source-page">
            (стр. {event.source_page})
          </span>
        )}
      </div>

      {reasoning && (
        <div className="timeline-event-reasoning">
          <button
            className="timeline-event-reasoning-toggle"
            onClick={(e) => {
              e.stopPropagation()
              setShowDetails(!showDetails)
            }}
          >
            {showDetails ? '▼' : '▶'} Reasoning
          </button>
          {showDetails && (
            <div className="timeline-event-reasoning-text">
              {reasoning}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default TimelineEventComponent
