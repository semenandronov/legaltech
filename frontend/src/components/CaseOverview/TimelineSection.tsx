import { Calendar, AlertCircle, FileText, CheckCircle } from 'lucide-react'
import { Card } from '../UI/Card'

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
        return <AlertCircle className="w-5 h-5 text-[#F59E0B]" />
      case 'file':
        return <FileText className="w-5 h-5 text-[#00D4FF]" />
      case 'check':
        return <CheckCircle className="w-5 h-5 text-[#10B981]" />
      default:
        return <Calendar className="w-5 h-5 text-[#7C3AED]" />
    }
  }

  const getIconBg = (type?: string) => {
    switch (type) {
      case 'alert':
        return 'bg-gradient-to-br from-[#F59E0B]/20 to-[#D97706]/20 border-[#F59E0B]/30'
      case 'file':
        return 'bg-gradient-to-br from-[#00D4FF]/20 to-[#7C3AED]/20 border-[#00D4FF]/30'
      case 'check':
        return 'bg-gradient-to-br from-[#10B981]/20 to-[#059669]/20 border-[#10B981]/30'
      default:
        return 'bg-gradient-to-br from-[#7C3AED]/20 to-[#5B21B6]/20 border-[#7C3AED]/30'
    }
  }
  
  return (
    <Card className="hoverable">
      <div className="space-y-6">
        {events.map((event, index) => (
          <div 
            key={event.id} 
            className="flex gap-4"
            style={{ animationDelay: `${index * 0.05}s` }}
          >
            <div className="flex flex-col items-center">
              <div className={`w-10 h-10 rounded-full ${getIconBg(event.icon)} border flex items-center justify-center flex-shrink-0`}>
                {getIcon(event.icon)}
              </div>
              {index < events.length - 1 && (
                <div className="w-0.5 h-full bg-gradient-to-b from-[#E5E7EB] to-transparent mt-2" />
              )}
            </div>
            <div className="flex-1 pb-6">
              <div className="flex items-center gap-3 mb-2">
                <span className="text-sm font-display font-semibold text-[#1F2937]">{event.date}</span>
                <span className="text-sm text-[#6B7280]">{event.type}</span>
              </div>
              <p className="text-body text-[#374151]">{event.description}</p>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

export default TimelineSection
