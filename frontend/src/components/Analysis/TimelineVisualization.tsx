import { useState, useMemo } from 'react'
import { TimelineEvent } from '../../services/api'
import './Analysis.css'

interface TimelineVisualizationProps {
  events: TimelineEvent[]
}

type GroupingPeriod = 'day' | 'week' | 'month' | 'year' | 'all'

const TimelineVisualization = ({ events }: TimelineVisualizationProps) => {
  const [grouping, setGrouping] = useState<GroupingPeriod>('month')
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())
  const [selectedEventType, setSelectedEventType] = useState<string>('all')

  // Получаем уникальные типы событий для фильтра
  const eventTypes = useMemo(() => {
    const types = new Set<string>()
    events.forEach(event => {
      if (event.event_type) {
        types.add(event.event_type)
      }
    })
    return Array.from(types).sort()
  }, [events])

  // Фильтруем события по типу
  const filteredEvents = useMemo(() => {
    if (selectedEventType === 'all') {
      return events
    }
    return events.filter(event => event.event_type === selectedEventType)
  }, [events, selectedEventType])

  // Группируем события по периодам
  const groupedEvents = useMemo(() => {
    if (grouping === 'all') {
      return { 'Все события': filteredEvents }
    }

    const groups: Record<string, TimelineEvent[]> = {}

    filteredEvents.forEach(event => {
      const date = new Date(event.date)
      let groupKey: string

      switch (grouping) {
        case 'year':
          groupKey = date.getFullYear().toString()
          break
        case 'month':
          groupKey = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
          break
        case 'week':
          const weekStart = new Date(date)
          weekStart.setDate(date.getDate() - date.getDay())
          groupKey = `${weekStart.getFullYear()}-W${String(Math.ceil((weekStart.getDate() + 6) / 7)).padStart(2, '0')}`
          break
        case 'day':
          groupKey = date.toISOString().split('T')[0]
          break
        default:
          groupKey = 'all'
      }

      if (!groups[groupKey]) {
        groups[groupKey] = []
      }
      groups[groupKey].push(event)
    })

    // Сортируем группы по дате
    const sortedGroups: Record<string, TimelineEvent[]> = {}
    Object.keys(groups)
      .sort((a, b) => {
        if (grouping === 'year') {
          return parseInt(a) - parseInt(b)
        }
        return a.localeCompare(b)
      })
      .forEach(key => {
        sortedGroups[key] = groups[key].sort(
          (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
        )
      })

    return sortedGroups
  }, [filteredEvents, grouping])

  // Форматируем название группы
  const formatGroupLabel = (key: string): string => {
    if (key === 'Все события') return key
    
    switch (grouping) {
      case 'year':
        return `${key} год`
      case 'month':
        const [year, month] = key.split('-')
        const monthNames = [
          'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
          'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'
        ]
        return `${monthNames[parseInt(month) - 1]} ${year}`
      case 'week':
        return `Неделя ${key}`
      case 'day':
        const date = new Date(key)
        return date.toLocaleDateString('ru-RU', {
          year: 'numeric',
          month: 'long',
          day: 'numeric',
          weekday: 'long'
        })
      default:
        return key
    }
  }

  const toggleGroup = (key: string) => {
    const newExpanded = new Set(expandedGroups)
    if (newExpanded.has(key)) {
      newExpanded.delete(key)
    } else {
      newExpanded.add(key)
    }
    setExpandedGroups(newExpanded)
  }

  // Разворачиваем все группы по умолчанию, если событий немного
  const shouldAutoExpand = filteredEvents.length < 50

  return (
    <div className="timeline-visualization-enhanced">
      <div className="timeline-controls">
        <div className="timeline-control-group">
          <label>Группировка:</label>
          <select
            value={grouping}
            onChange={(e) => setGrouping(e.target.value as GroupingPeriod)}
            className="timeline-select"
          >
            <option value="all">Все события</option>
            <option value="year">По годам</option>
            <option value="month">По месяцам</option>
            <option value="week">По неделям</option>
            <option value="day">По дням</option>
          </select>
        </div>

        {eventTypes.length > 0 && (
          <div className="timeline-control-group">
            <label>Тип события:</label>
            <select
              value={selectedEventType}
              onChange={(e) => setSelectedEventType(e.target.value)}
              className="timeline-select"
            >
              <option value="all">Все типы ({filteredEvents.length})</option>
              {eventTypes.map(type => (
                <option key={type} value={type}>
                  {type} ({events.filter(e => e.event_type === type).length})
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="timeline-stats">
          Всего событий: <strong>{filteredEvents.length}</strong>
        </div>
      </div>

      <div className="timeline-vertical">
        {Object.entries(groupedEvents).map(([groupKey, groupEvents]) => {
          const isExpanded = shouldAutoExpand || expandedGroups.has(groupKey)
          const groupLabel = formatGroupLabel(groupKey)

          return (
            <div key={groupKey} className="timeline-group">
              <div
                className="timeline-group-header"
                onClick={() => toggleGroup(groupKey)}
              >
                <div className="timeline-group-title">
                  <span className="timeline-group-icon">
                    {isExpanded ? '▼' : '▶'}
                  </span>
                  <span className="timeline-group-label">{groupLabel}</span>
                  <span className="timeline-group-count">({groupEvents.length})</span>
                </div>
              </div>

              {isExpanded && (
                <div className="timeline-events-container">
                  {groupEvents.map((event, index) => (
                    <div
                      key={event.id || index}
                      className="timeline-event-item"
                    >
                      <div className="timeline-event-line">
                        <div className="timeline-event-dot"></div>
                        {index < groupEvents.length - 1 && (
                          <div className="timeline-event-connector"></div>
                        )}
                      </div>
                      <div className="timeline-event-content">
                        <div className="timeline-event-header">
                          <div className="timeline-event-date">
                            {new Date(event.date).toLocaleDateString('ru-RU', {
                              year: 'numeric',
                              month: 'short',
                              day: 'numeric',
                            })}
                          </div>
                          {event.event_type && (
                            <div className="timeline-event-type-badge">
                              {event.event_type}
                            </div>
                          )}
                        </div>
                        <div className="timeline-event-description">
                          {event.description}
                        </div>
                        <div className="timeline-event-source">
                          📄 {event.source_document}
                          {event.source_page && `, стр. ${event.source_page}`}
                          {event.source_line && `, строка ${event.source_line}`}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default TimelineVisualization
