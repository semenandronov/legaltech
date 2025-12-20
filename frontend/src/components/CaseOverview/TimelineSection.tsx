import { Calendar, AlertCircle, FileText, CheckCircle } from 'lucide-react'
import Card from '../UI/Card'

interface TimelineEvent {
  id: string
  date: string
  type: string
  description: string
  icon?: 'calendar' | 'alert' | 'file' | 'check'
}

interface TimelineSectionProps {
  events: TimelineEvent[]
}

const TimelineSection = ({ events }: TimelineSectionProps) => {
  const getIcon = (type?: string) => {
    switch (type) {
      case 'alert':
        return <AlertCircle className="w-4 h-4 text-warning" />
      case 'file':
        return <FileText className="w-4 h-4 text-primary" />
      case 'check':
        return <CheckCircle className="w-4 h-4 text-success" />
      default:
        return <Calendar className="w-4 h-4 text-primary" />
    }
  }
  
  return (
    <Card>
      <div className="space-y-4">
        {events.map((event, index) => (
          <div key={event.id} className="flex gap-4">
            <div className="flex flex-col items-center">
              <div className="w-8 h-8 rounded-full bg-tertiary flex items-center justify-center flex-shrink-0">
                {getIcon(event.icon)}
              </div>
              {index < events.length - 1 && (
                <div className="w-0.5 h-full bg-border mt-2" />
              )}
            </div>
            <div className="flex-1 pb-4">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-small font-medium text-primary">{event.date}</span>
                <span className="text-small text-secondary">{event.type}</span>
              </div>
              <p className="text-body text-primary">{event.description}</p>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

export default TimelineSection
