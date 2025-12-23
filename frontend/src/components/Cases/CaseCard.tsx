import React from 'react'
import { useNavigate } from 'react-router-dom'
import { FileText, Calendar } from 'lucide-react'
import { CaseListItem } from '../../services/api'
import { Card } from '../UI/Card'
import { Button } from '../UI/Button'

interface CaseCardProps {
  caseItem: CaseListItem
}

const CaseCard = ({ caseItem }: CaseCardProps) => {
  const navigate = useNavigate()
  
  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffTime = Math.abs(now.getTime() - date.getTime())
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))
    
    if (diffDays === 1) return '1 день назад'
    if (diffDays < 7) return `${diffDays} дня назад`
    if (diffDays < 30) return `${Math.ceil(diffDays / 7)} недели назад`
    return date.toLocaleDateString('ru-RU')
  }
  
  return (
    <Card hoverable className="cursor-pointer" onClick={() => navigate(`/cases/${caseItem.id}/workspace`)}>
      <div className="space-y-4">
        {/* Название */}
        <h3 className="text-h3 text-primary">{caseItem.title || 'Без названия'}</h3>
        
        {/* Статистика */}
        <div className="flex items-center gap-6 text-small text-secondary">
          <div className="flex items-center gap-1">
            <FileText className="w-4 h-4" />
            <span>{caseItem.num_documents} документов</span>
          </div>
          <div className="flex items-center gap-1">
            <Calendar className="w-4 h-4" />
            <span>Обновлено: {formatDate(caseItem.updated_at)}</span>
          </div>
        </div>
        
        {/* Кнопка открыть */}
        <div className="pt-2 border-t border-border">
          <Button
            variant="primary"
            size="sm"
            onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
              e.stopPropagation()
              navigate(`/cases/${caseItem.id}/workspace`)
            }}
          >
            Открыть
          </Button>
        </div>
      </div>
    </Card>
  )
}

export default CaseCard
