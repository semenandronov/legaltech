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
      className="card-hover cursor-pointer bg-white rounded-xl p-6 shadow-soft border border-[#E5E8EB]/50"
      onClick={() => navigate(`/cases/${caseItem.id}/workspace`)}
    >
      <div className="space-y-5">
        {/* Название */}
        <h3 className="text-xl font-display text-[#0F1419] leading-tight tracking-tight">
          {caseItem.title || 'Без названия'}
        </h3>
        
        {/* Статистика */}
        <div className="flex items-center gap-6 text-sm text-[#666B78]">
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-[#9CA3AF]" />
            <span className="font-medium">{caseItem.num_documents} документов</span>
          </div>
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-[#9CA3AF]" />
            <span>{formatDate(caseItem.updated_at)}</span>
          </div>
        </div>
        
        {/* Кнопка открыть */}
        <div className="pt-4 border-t border-[#E5E8EB]/50">
          <button
            className="w-full px-4 py-2.5 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white rounded-lg font-medium text-sm hover:shadow-lg hover:shadow-[#00D4FF]/25 transition-all duration-300 transform hover:scale-[1.02]"
            onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
              e.stopPropagation()
              navigate(`/cases/${caseItem.id}/workspace`)
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
