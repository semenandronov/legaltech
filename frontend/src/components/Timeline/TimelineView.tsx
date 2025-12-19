import React, { useState, useMemo } from 'react'
import { TimelineEvent } from '../../services/api'
import TimelineEventComponent from './TimelineEvent'
import './Timeline.css'

interface TimelineViewProps {
  events: TimelineEvent[]
  onEventClick?: (event: TimelineEvent) => void
  onDocumentClick?: (filename: string) => void
}

const TimelineView: React.FC<TimelineViewProps> = ({
  events,
  onEventClick,
  onDocumentClick
}) => {
  const [filterType, setFilterType] = useState<string>('all')
  const [zoomLevel, setZoomLevel] = useState<'month' | 'quarter' | 'year'>('month')

  // Фильтруем события
  const filteredEvents = useMemo(() => {
    if (filterType === 'all') return events
    return events.filter(e => e.event_type === filterType)
  }, [events, filterType])

  // Группируем по датам
  const eventsByDate = useMemo(() => {
    const grouped: Record<string, TimelineEvent[]> = {}
    filteredEvents.forEach(event => {
      const dateKey = new Date(event.date).toISOString().split('T')[0]
      if (!grouped[dateKey]) {
        grouped[dateKey] = []
      }
      grouped[dateKey].push(event)
    })
    return grouped
  }, [filteredEvents])

  // Получаем диапазон дат
  const dateRange = useMemo(() => {
    if (filteredEvents.length === 0) return { min: new Date(), max: new Date() }
    const dates = filteredEvents.map(e => new Date(e.date).getTime())
    return {
      min: new Date(Math.min(...dates)),
      max: new Date(Math.max(...dates))
    }
  }, [filteredEvents])

  const eventTypes = useMemo(() => {
    const types = new Set<string>()
    events.forEach(e => {
      if (e.event_type) types.add(e.event_type)
    })
    return ['all', ...Array.from(types)]
  }, [events])

  return (
    <div className="timeline-view">
      <div className="timeline-view-header">
        <h2>Timeline Events</h2>
        <div className="timeline-view-controls">
          <select
            className="timeline-view-filter"
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            aria-label="Фильтр по типу события"
          >
            {eventTypes.map(type => (
              <option key={type} value={type}>
                {type === 'all' ? 'All Types' : type}
              </option>
            ))}
          </select>
          <select
            className="timeline-view-zoom"
            value={zoomLevel}
            onChange={(e) => setZoomLevel(e.target.value as 'month' | 'quarter' | 'year')}
            aria-label="Уровень масштаба"
          >
            <option value="month">Month</option>
            <option value="quarter">Quarter</option>
            <option value="year">Year</option>
          </select>
        </div>
      </div>

      <div className="timeline-view-stats">
        <div className="timeline-view-stat">
          <span className="timeline-view-stat-label">Total Events:</span>
          <span className="timeline-view-stat-value">{filteredEvents.length}</span>
        </div>
        <div className="timeline-view-stat">
          <span className="timeline-view-stat-label">Date Range:</span>
          <span className="timeline-view-stat-value">
            {dateRange.min.toLocaleDateString('ru-RU')} - {dateRange.max.toLocaleDateString('ru-RU')}
          </span>
        </div>
      </div>

      <div className="timeline-view-container">
        <div className="timeline-view-timeline">
          {Object.entries(eventsByDate)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([date, dateEvents]) => (
              <div key={date} className="timeline-view-date-group">
                <div className="timeline-view-date-marker">
                  <div className="timeline-view-date-line" />
                  <div className="timeline-view-date-label">
                    {new Date(date).toLocaleDateString('ru-RU', {
                      year: 'numeric',
                      month: 'long',
                      day: 'numeric'
                    })}
                  </div>
                </div>
                <div className="timeline-view-events">
                  {dateEvents.map((event, idx) => (
                    <TimelineEventComponent
                      key={event.id || idx}
                      event={event}
                      onClick={() => onEventClick?.(event)}
                      onDocumentClick={onDocumentClick}
                    />
                  ))}
                </div>
              </div>
            ))}
        </div>
      </div>

      {filteredEvents.length === 0 && (
        <div className="timeline-view-empty">
          Нет событий, соответствующих фильтру
        </div>
      )}
    </div>
  )
}

export default TimelineView
