import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Settings, HelpCircle, User } from 'lucide-react'
import { CaseResponse } from '../../services/api'
import { Button } from '../UI/Button'
import Breadcrumbs from '../UI/Breadcrumbs'

interface CaseHeaderProps {
  caseData: CaseResponse
}

const CaseHeader = ({ caseData }: CaseHeaderProps) => {
  const navigate = useNavigate()
  
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
            {caseData.title || 'Без названия'}
          </h1>
          
          {caseData.description && (
            <p className="text-body text-secondary">{caseData.description}</p>
          )}
        </div>
      </div>
    </div>
  )
}

export default CaseHeader
