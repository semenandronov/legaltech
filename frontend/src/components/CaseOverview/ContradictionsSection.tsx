import { AlertTriangle, CheckCircle, XCircle } from 'lucide-react'
import { Card } from '../UI/Card'

interface Contradiction {
  id: string
  type: string
  description: string
  document1: string
  document2: string
  location1?: string
  location2?: string
  status: 'review' | 'resolved' | 'ignored'
  resolvedBy?: string
  resolvedAt?: string
  resolution?: string
}

interface ContradictionsSectionProps {
  contradictions: Contradiction[]
  onResolve?: (id: string) => void
  onIgnore?: (id: string) => void
  onViewDocument?: (document: string) => void
}

const ContradictionsSection = ({
  contradictions,
  onResolve,
  onIgnore,
  onViewDocument,
}: ContradictionsSectionProps) => {
  if (contradictions.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-body text-text-secondary">Противоречия не найдены</p>
      </div>
    )
  }
  
  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'resolved':
        return (
          <span className="px-3 py-1 rounded-full text-xs font-medium bg-success-bg text-success border border-success/30 flex items-center gap-1">
            <CheckCircle className="w-3 h-3" /> Resolved
          </span>
        )
      case 'ignored':
        return (
          <span className="px-3 py-1 rounded-full text-xs font-medium bg-bg-secondary text-text-secondary border border-border flex items-center gap-1">
            <XCircle className="w-3 h-3" /> Ignored
          </span>
        )
      default:
        return (
          <span className="px-3 py-1 rounded-full text-xs font-medium bg-warning-bg text-warning border border-warning/30 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" /> Review
          </span>
        )
    }
  }
  
  return (
    <div className="space-y-4">
      {contradictions.map((contradiction, index) => (
        <Card 
          key={contradiction.id} 
          className="border-l-4 border-l-warning hoverable"
          style={{ animationDelay: `${index * 0.05}s` }}
        >
          <div className="space-y-4">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <AlertTriangle className="w-5 h-5 text-warning" />
                <h3 className="font-display text-h3 text-text-primary">{contradiction.type}</h3>
              </div>
              {getStatusBadge(contradiction.status)}
            </div>
            
            <p className="text-body text-text-primary">{contradiction.description}</p>
            
            <div className="bg-bg-secondary rounded-lg p-4 border border-border space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-text-primary">Документ 1:</span>
                <button
                  onClick={() => onViewDocument?.(contradiction.document1)}
                  className="text-sm text-accent hover:text-accent-hover underline transition-colors"
                >
                  {contradiction.document1}
                </button>
                {contradiction.location1 && (
                  <span className="text-sm text-text-secondary">({contradiction.location1})</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-text-primary">Документ 2:</span>
                <button
                  onClick={() => onViewDocument?.(contradiction.document2)}
                  className="text-sm text-accent hover:text-accent-hover underline transition-colors"
                >
                  {contradiction.document2}
                </button>
                {contradiction.location2 && (
                  <span className="text-sm text-text-secondary">({contradiction.location2})</span>
                )}
              </div>
            </div>
            
            {contradiction.status === 'resolved' && contradiction.resolution && (
              <div className="bg-success-bg border border-success/30 rounded-lg p-4">
                <p className="text-sm text-text-primary">
                  <strong>Разрешено:</strong> {contradiction.resolution}
                </p>
                {contradiction.resolvedBy && (
                  <p className="text-xs text-text-secondary mt-1">
                    {contradiction.resolvedBy} • {contradiction.resolvedAt && new Date(contradiction.resolvedAt).toLocaleDateString('ru-RU')}
                  </p>
                )}
              </div>
            )}
            
            {contradiction.status === 'review' && (
              <div className="flex items-center gap-2 pt-3 border-t border-border">
                <button
                  onClick={() => onResolve?.(contradiction.id)}
                  className="px-4 py-2 bg-accent text-bg-primary text-sm font-medium rounded-lg hover:bg-accent-hover transition-all duration-300"
                >
                  Отметить как решённое
                </button>
                <button
                  onClick={() => onIgnore?.(contradiction.id)}
                  className="px-4 py-2 bg-bg-elevated border border-border text-text-secondary text-sm font-medium rounded-lg hover:bg-bg-hover transition-all duration-300"
                >
                  Игнорировать
                </button>
              </div>
            )}
          </div>
        </Card>
      ))}
    </div>
  )
}

export default ContradictionsSection
