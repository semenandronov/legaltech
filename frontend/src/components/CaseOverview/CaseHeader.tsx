import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Settings, HelpCircle, User } from 'lucide-react'
import { CaseResponse } from '../../services/api'
import { Badge } from '../UI/Badge'
import { Button } from '../UI/Button'
import Breadcrumbs from '../UI/Breadcrumbs'

interface CaseHeaderProps {
  caseData: CaseResponse
}

const CaseHeader = ({ caseData }: CaseHeaderProps) => {
  const navigate = useNavigate()
  
  const getRiskBadge = (): 'high-risk' | 'medium-risk' | 'low-risk' => {
    // В реальном приложении это должно приходить с API
    return 'high-risk'
  }
  
  const getStatusBadge = (status: string) => {
    const statusMap: Record<string, { variant: 'pending' | 'completed' | 'flagged', label: string }> = {
      'review': { variant: 'pending', label: 'Review' },
      'investigation': { variant: 'flagged', label: 'Investigation' },
      'litigation': { variant: 'flagged', label: 'Litigation' },
      'completed': { variant: 'completed', label: 'Completed' },
    }
    return statusMap[status] || { variant: 'pending' as const, label: status }
  }
  
  const statusInfo = getStatusBadge(caseData.status)
  const riskLevel = getRiskBadge()
  
  const breadcrumbs = [
    { label: 'Дела', href: '/cases' },
    { label: caseData.title || 'Дело', href: undefined },
  ]
  
  return (
    <div className="border-b border-border bg-secondary">
      <div className="px-6 py-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-4">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => navigate('/cases')}
            >
              <ArrowLeft className="w-4 h-4" />
            </Button>
            <Breadcrumbs items={breadcrumbs} />
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm">
              <Settings className="w-4 h-4" />
            </Button>
            <Button variant="secondary" size="sm">
              <HelpCircle className="w-4 h-4" />
            </Button>
            <Button variant="secondary" size="sm">
              <User className="w-4 h-4" />
            </Button>
          </div>
        </div>
        
        <div className="space-y-3">
          <h1 className="text-h1 text-primary">
            {caseData.title || 'Без названия'} (ID: {caseData.id})
          </h1>
          
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2">
              <span className="text-body text-secondary">Статус:</span>
              <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-body text-secondary">Риск:</span>
              <Badge variant={riskLevel}>
                {riskLevel === 'high-risk' && '🔴 High'}
                {riskLevel === 'medium-risk' && '🟡 Medium'}
                {riskLevel === 'low-risk' && '🟢 Low'}
              </Badge>
            </div>
            <div className="text-body text-secondary">
              <span>Юрист: John Doe</span>
            </div>
            <div className="text-body text-secondary">
              <span>Создано: {new Date(caseData.created_at).toLocaleDateString('ru-RU')}</span>
            </div>
          </div>
          
          {caseData.description && (
            <p className="text-body text-secondary">{caseData.description}</p>
          )}
        </div>
      </div>
    </div>
  )
}

export default CaseHeader
