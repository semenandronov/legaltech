import { useEffect, useState } from 'react'
import { getTimeline, TimelineEvent } from '../../services/api'
import TimelineVisualization from './TimelineVisualization'
import './Analysis.css'

interface TimelineTabProps {
  caseId: string
}

const TimelineTab = ({ caseId }: TimelineTabProps) => {
  const [events, setEvents] = useState<TimelineEvent[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadTimeline()
  }, [caseId])

  const loadTimeline = async () => {
    setLoading(true)
    try {
      const data = await getTimeline(caseId)
      setEvents(data.events)
    } catch (error) {
      console.error('Ошибка при загрузке таймлайна:', error)
    } finally {
      setLoading(false)
    }
  }

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
        <h2>Таймлайн событий ({events.length})</h2>
      </div>
      <TimelineVisualization events={events} />
      <div className="timeline-events-list">
        {events.map((event) => (
          <div key={event.id} className="timeline-event-card">
            <div className="timeline-event-date">
              {new Date(event.date).toLocaleDateString('ru-RU', {
                year: 'numeric',
                month: 'long',
                day: 'numeric',
              })}
            </div>
            <div className="timeline-event-content">
              <div className="timeline-event-type">{event.event_type || 'Событие'}</div>
              <div className="timeline-event-description">{event.description}</div>
              <div className="timeline-event-source">
                Источник: {event.source_document}
                {event.source_page && `, стр. ${event.source_page}`}
                {event.source_line && `, строка ${event.source_line}`}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default TimelineTab

