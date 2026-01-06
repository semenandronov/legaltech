import { FileText, ExternalLink } from 'lucide-react'
import { Card } from '../UI/Card'

interface Risk {
  id: string
  level: 'high-risk' | 'medium-risk' | 'low-risk'
  title: string
  description: string
  location: string
  document: string
  page?: number
  section?: string
  analysis?: string
}

interface RiskCardsProps {
  risks: Risk[]
  onViewDocument?: (document: string, page?: number) => void
}

const RiskCards = ({ risks, onViewDocument }: RiskCardsProps) => {
  if (risks.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-body text-text-secondary">Риски не выявлены</p>
      </div>
    )
  }

  const getRiskStyles = (level: string) => {
    switch (level) {
      case 'high-risk':
        return {
          border: 'border-l-4 border-error',
          badge: 'bg-error-bg text-error border border-error/30',
          icon: '🔴'
        }
      case 'medium-risk':
        return {
          border: 'border-l-4 border-warning',
          badge: 'bg-warning-bg text-warning border border-warning/30',
          icon: '🟡'
        }
      default:
        return {
          border: 'border-l-4 border-success',
          badge: 'bg-success-bg text-success border border-success/30',
          icon: '🟢'
        }
    }
  }
  
  return (
    <div className="space-y-4">
      {risks.map((risk, index) => {
        const styles = getRiskStyles(risk.level)
        return (
          <Card 
            key={risk.id} 
            className={`${styles.border} hoverable`}
            style={{ animationDelay: `${index * 0.05}s` }}
          >
            <div className="space-y-4">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <span className={`px-3 py-1 rounded-full text-xs font-medium ${styles.badge}`}>
                    {styles.icon} {risk.level === 'high-risk' ? 'High' : risk.level === 'medium-risk' ? 'Medium' : 'Low'}
                  </span>
                  <h3 className="font-display text-h3 text-text-primary">{risk.title}</h3>
                </div>
              </div>
              
              <p className="text-body text-text-primary">{risk.description}</p>
              
              <div className="flex items-center gap-2 text-sm text-text-secondary">
                <FileText className="w-4 h-4" />
                <span>
                  {risk.location}
                  {risk.section && `, ${risk.section}`}
                </span>
              </div>
              
              {risk.analysis && (
                <div className="bg-bg-secondary rounded-lg p-4 border border-border">
                  <p className="text-sm text-text-secondary italic">"{risk.analysis}"</p>
                </div>
              )}
              
              <div className="flex items-center gap-2 pt-3 border-t border-border">
                <button
                  onClick={() => onViewDocument?.(risk.document, risk.page)}
                  className="px-4 py-2 bg-accent text-bg-primary text-sm font-medium rounded-lg hover:bg-accent-hover transition-all duration-300 flex items-center gap-2"
                >
                  <ExternalLink className="w-4 h-4" />
                  Открыть в документе
                </button>
              </div>
            </div>
          </Card>
        )
      })}
    </div>
  )
}

export default RiskCards
