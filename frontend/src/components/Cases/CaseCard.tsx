import React from 'react'
import { useNavigate } from 'react-router-dom'
import { FileText, Calendar } from 'lucide-react'
import { CaseListItem } from '../../services/api'

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
    <div 
      className="cursor-pointer rounded-xl p-6 border transition-all duration-150 hover:bg-bg-hover"
      style={{
        backgroundColor: 'var(--color-bg-elevated)',
        borderColor: 'var(--color-border)',
        padding: 'var(--space-6)',
      }}
      onClick={() => navigate(`/cases/${caseItem.id}/chat`)}
    >
      <div className="space-y-5" style={{ gap: 'var(--space-5)' }}>
        {/* Название */}
        <h3 
          className="text-xl font-display leading-tight tracking-tight"
          style={{
            fontFamily: 'var(--font-display)',
            color: 'var(--color-text-primary)',
            letterSpacing: 'var(--tracking-tight)',
          }}
        >
          {caseItem.title || 'Без названия'}
        </h3>
        
        {/* Статистика */}
        <div 
          className="flex items-center gap-6 text-sm"
          style={{ 
            gap: 'var(--space-6)',
            color: 'var(--color-text-secondary)'
          }}
        >
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
            <span className="font-medium">{caseItem.num_documents} документов</span>
          </div>
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
            <span>{formatDate(caseItem.updated_at)}</span>
          </div>
        </div>
        
        {/* Кнопка открыть */}
        <div 
          className="pt-4 border-t"
          style={{ 
            paddingTop: 'var(--space-4)',
            borderTopColor: 'var(--color-border)'
          }}
        >
          <button
            className="w-full px-4 py-2.5 rounded-lg font-medium text-sm transition-all duration-150"
            style={{
              backgroundColor: 'var(--color-accent)',
              color: 'var(--color-bg-primary)',
            }}
            onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
              e.stopPropagation()
              navigate(`/cases/${caseItem.id}/chat`)
            }}
          >
            Открыть дело
          </button>
        </div>
      </div>
    </div>
  )
}

export default CaseCard
