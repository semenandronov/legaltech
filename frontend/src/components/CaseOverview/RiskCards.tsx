import { FileText, ExternalLink } from 'lucide-react'
import Card from '../UI/Card'
import Badge from '../UI/Badge'
import Button from '../UI/Button'

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
      <div className="text-center py-8">
        <p className="text-body text-secondary">Риски не выявлены</p>
      </div>
    )
  }
  
  return (
    <div className="space-y-4">
      {risks.map((risk) => (
        <Card key={risk.id} variant="accent" className="border-l-4">
          <div className="space-y-3">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <Badge variant={risk.level}>
                  {risk.level === 'high-risk' && '🔴'}
                  {risk.level === 'medium-risk' && '🟡'}
                  {risk.level === 'low-risk' && '🟢'}
                  {' '}
                  {risk.level === 'high-risk' && 'High'}
                  {risk.level === 'medium-risk' && 'Medium'}
                  {risk.level === 'low-risk' && 'Low'}
                </Badge>
                <h3 className="text-h3 text-primary">{risk.title}</h3>
              </div>
            </div>
            
            <p className="text-body text-primary">{risk.description}</p>
            
            <div className="flex items-center gap-2 text-small text-secondary">
              <FileText className="w-4 h-4" />
              <span>
                {risk.location}
                {risk.section && `, ${risk.section}`}
              </span>
            </div>
            
            {risk.analysis && (
              <div className="bg-tertiary rounded-md p-3">
                <p className="text-small text-secondary italic">"{risk.analysis}"</p>
              </div>
            )}
            
            <div className="flex items-center gap-2 pt-2 border-t border-border">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onViewDocument?.(risk.document, risk.page)}
              >
                <ExternalLink className="w-4 h-4 mr-2" />
                Открыть в документе
              </Button>
            </div>
          </div>
        </Card>
      ))}
    </div>
  )
}

export default RiskCards
