import { useEffect, useState, useMemo } from 'react'
import { getTimeline, TimelineEvent } from '../../services/api'
import TimelineVisualization from './TimelineVisualization'
import './Analysis.css'

interface TimelineTabProps {
  caseId: string
}

const TimelineTab = ({ caseId }: TimelineTabProps) => {
  const [events, setEvents] = useState<TimelineEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [showStats, setShowStats] = useState(true)

  useEffect(() => {
    loadTimeline()
  }, [caseId])

  const loadTimeline = async () => {
    setLoading(true)
    try {
      const data = await getTimeline(caseId)
      // Сортируем события по дате
      const sortedEvents = [...data.events].sort(
        (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
      )
      setEvents(sortedEvents)
    } catch (error) {
      console.error('Ошибка при загрузке таймлайна:', error)
    } finally {
      setLoading(false)
    }
  }

  // Статистика по событиям
  const stats = useMemo(() => {
    const dateRange = events.length > 0
      ? {
          start: new Date(Math.min(...events.map(e => new Date(e.date).getTime()))),
          end: new Date(Math.max(...events.map(e => new Date(e.date).getTime())))
        }
      : null

    const eventTypesCount: Record<string, number> = {}
    events.forEach(event => {
      const type = event.event_type || 'Без типа'
      eventTypesCount[type] = (eventTypesCount[type] || 0) + 1
    })

    const documentsCount = new Set(events.map(e => e.source_document)).size

    return {
      total: events.length,
      dateRange,
      eventTypesCount,
      documentsCount
    }
  }, [events])

  // Фильтрация по поисковому запросу
  const filteredEvents = useMemo(() => {
    if (!searchQuery.trim()) {
      return events
    }

    const query = searchQuery.toLowerCase()
    return events.filter(event =>
      event.description.toLowerCase().includes(query) ||
      (event.event_type && event.event_type.toLowerCase().includes(query)) ||
      event.source_document.toLowerCase().includes(query)
    )
  }, [events, searchQuery])

  if (loading) {
    return <div className="analysis-tab-loading">Загрузка таймлайна...</div>
  }

  if (events.length === 0) {
    return (
      <div className="analysis-tab-empty">
        <div className="analysis-tab-empty-icon">📅</div>
        <h3>Таймлайн не найден</h3>
        <p>Запустите анализ для извлечения событий из документов</p>
      </div>
    )
  }

  return (
    <div className="timeline-tab">
      <div className="timeline-tab-header">
        <div className="timeline-header-top">
          <h2>Таймлайн событий</h2>
          <button
            className="timeline-refresh-btn"
            onClick={loadTimeline}
            title="Обновить таймлайн"
          >
            🔄 Обновить
          </button>
      </div>

        {showStats && stats.dateRange && (
          <div className="timeline-stats-panel">
            <div className="timeline-stat-item">
              <span className="timeline-stat-label">Всего событий:</span>
              <span className="timeline-stat-value">{stats.total}</span>
            </div>
            <div className="timeline-stat-item">
              <span className="timeline-stat-label">Период:</span>
              <span className="timeline-stat-value">
                {stats.dateRange.start.toLocaleDateString('ru-RU')} — {stats.dateRange.end.toLocaleDateString('ru-RU')}
              </span>
              </div>
            <div className="timeline-stat-item">
              <span className="timeline-stat-label">Документов:</span>
              <span className="timeline-stat-value">{stats.documentsCount}</span>
            </div>
            <button
              className="timeline-stats-toggle"
              onClick={() => setShowStats(false)}
            >
              ✕
            </button>
          </div>
        )}

        <div className="timeline-search-bar">
          <input
            type="text"
            placeholder="Поиск по событиям, типам, документам..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="timeline-search-input"
          />
          {searchQuery && (
            <button
              className="timeline-search-clear"
              onClick={() => setSearchQuery('')}
            >
              ✕
            </button>
          )}
          {searchQuery && (
            <span className="timeline-search-results">
              Найдено: {filteredEvents.length} из {events.length}
            </span>
          )}
        </div>
      </div>

      {filteredEvents.length === 0 ? (
        <div className="timeline-no-results">
          <p>По запросу "{searchQuery}" ничего не найдено</p>
          <button onClick={() => setSearchQuery('')}>Очистить поиск</button>
        </div>
      ) : (
        <TimelineVisualization events={filteredEvents} />
      )}
    </div>
  )
}

export default TimelineTab

