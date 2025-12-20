import { AlertTriangle, CheckCircle, XCircle } from 'lucide-react'
import Card from '../UI/Card'
import Button from '../UI/Button'
import Badge from '../UI/Badge'

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
      <div className="text-center py-8">
        <p className="text-body text-secondary">Противоречия не найдены</p>
      </div>
    )
  }
  
  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'resolved':
        return <Badge variant="completed"><CheckCircle className="w-3 h-3 inline mr-1" />Resolved</Badge>
      case 'ignored':
        return <Badge variant="pending"><XCircle className="w-3 h-3 inline mr-1" />Ignored</Badge>
      default:
        return <Badge variant="flagged"><AlertTriangle className="w-3 h-3 inline mr-1" />Review</Badge>
    }
  }
  
  return (
    <div className="space-y-4">
      {contradictions.map((contradiction) => (
        <Card key={contradiction.id} variant="accent" className="border-l-4 border-l-warning">
          <div className="space-y-3">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-warning" />
                <h3 className="text-h3 text-primary">{contradiction.type}</h3>
              </div>
              {getStatusBadge(contradiction.status)}
            </div>
            
            <p className="text-body text-primary">{contradiction.description}</p>
            
            <div className="bg-tertiary rounded-md p-3 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-small font-medium text-primary">Документ 1:</span>
                <button
                  onClick={() => onViewDocument?.(contradiction.document1)}
                  className="text-small text-primary hover:text-primary underline"
                >
                  {contradiction.document1}
                </button>
                {contradiction.location1 && (
                  <span className="text-small text-secondary">({contradiction.location1})</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-small font-medium text-primary">Документ 2:</span>
                <button
                  onClick={() => onViewDocument?.(contradiction.document2)}
                  className="text-small text-primary hover:text-primary underline"
                >
                  {contradiction.document2}
                </button>
                {contradiction.location2 && (
                  <span className="text-small text-secondary">({contradiction.location2})</span>
                )}
              </div>
            </div>
            
            {contradiction.status === 'resolved' && contradiction.resolution && (
              <div className="bg-success bg-opacity-10 border border-success border-opacity-30 rounded-md p-3">
                <p className="text-small text-primary">
                  <strong>Разрешено:</strong> {contradiction.resolution}
                </p>
                {contradiction.resolvedBy && (
                  <p className="text-tiny text-secondary mt-1">
                    {contradiction.resolvedBy} • {contradiction.resolvedAt && new Date(contradiction.resolvedAt).toLocaleDateString('ru-RU')}
                  </p>
                )}
              </div>
            )}
            
            {contradiction.status === 'review' && (
              <div className="flex items-center gap-2 pt-2 border-t border-border">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => onResolve?.(contradiction.id)}
                >
                  Отметить как решённое
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => onIgnore?.(contradiction.id)}
                >
                  Игнорировать
                </Button>
              </div>
            )}
          </div>
        </Card>
      ))}
    </div>
  )
}

export default ContradictionsSection
