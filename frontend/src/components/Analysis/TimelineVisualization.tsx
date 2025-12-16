import { TimelineEvent } from '../../services/api'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import './Analysis.css'

interface TimelineVisualizationProps {
  events: TimelineEvent[]
}

const TimelineVisualization = ({ events }: TimelineVisualizationProps) => {
  // Group events by date
  const eventsByDate = events.reduce((acc, event) => {
    const date = event.date
    if (!acc[date]) {
      acc[date] = []
    }
    acc[date].push(event)
    return acc
  }, {} as Record<string, TimelineEvent[]>)

  // Prepare data for chart
  const chartData = Object.entries(eventsByDate)
    .map(([date, events]) => ({
      date: new Date(date).toLocaleDateString('ru-RU', { month: 'short', day: 'numeric' }),
      count: events.length,
      fullDate: date,
    }))
    .sort((a, b) => new Date(a.fullDate).getTime() - new Date(b.fullDate).getTime())

  if (chartData.length === 0) {
    return null
  }

  return (
    <div className="timeline-visualization">
      <h3>Визуализация событий</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f1f1f" />
          <XAxis dataKey="date" stroke="#a0a0a0" />
          <YAxis stroke="#a0a0a0" />
          <Tooltip
            contentStyle={{
              backgroundColor: '#111111',
              border: '1px solid #333',
              borderRadius: '8px',
              color: '#e5e5e5',
            }}
          />
          <Line type="monotone" dataKey="count" stroke="#667eea" strokeWidth={2} dot={{ fill: '#667eea' }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export default TimelineVisualization

