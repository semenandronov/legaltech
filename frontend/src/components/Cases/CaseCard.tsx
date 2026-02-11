import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileText, Calendar, MoreVertical, Trash2 } from 'lucide-react'
import { CaseListItem } from '../../services/api'

interface CaseCardProps {
  caseItem: CaseListItem
  onDelete?: (caseId: string) => void
}

const CaseCard = ({ caseItem, onDelete }: CaseCardProps) => {
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    if (!menuOpen) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [menuOpen])

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
      className="cursor-pointer rounded-xl p-6 border transition-all duration-150 hover:bg-bg-hover group relative"
      style={{
        backgroundColor: 'var(--color-bg-elevated)',
        borderColor: 'var(--color-border)',
        padding: 'var(--space-6)',
      }}
      onClick={() => navigate(`/cases/${caseItem.id}/chat`)}
    >
      {/* Context menu */}
      {onDelete && (
        <div ref={menuRef} className="absolute top-4 right-4" style={{ zIndex: 10 }}>
          <button
            className="p-1.5 rounded-md transition-all duration-150 opacity-0 group-hover:opacity-100"
            style={{ color: 'var(--color-text-secondary)' }}
            onClick={(e) => {
              e.stopPropagation()
              setMenuOpen(!menuOpen)
            }}
          >
            <MoreVertical className="w-4 h-4" />
          </button>
          {menuOpen && (
            <div
              className="absolute right-0 top-full mt-1 rounded-lg border shadow-lg py-1 min-w-[160px]"
              style={{
                backgroundColor: 'var(--color-bg-elevated)',
                borderColor: 'var(--color-border)',
                zIndex: 50,
              }}
            >
              <button
                className="w-full px-3 py-2 text-left text-sm flex items-center gap-2 transition-colors duration-100 hover:bg-[var(--color-bg-hover)]"
                style={{ color: 'var(--color-error, #dc2626)' }}
                onClick={(e) => {
                  e.stopPropagation()
                  setMenuOpen(false)
                  onDelete(caseItem.id)
                }}
              >
                <Trash2 className="w-4 h-4" />
                Удалить дело
              </button>
            </div>
          )}
        </div>
      )}

      <div className="space-y-5" style={{ gap: 'var(--space-5)' }}>
        {/* Название */}
        <h3
          className="text-xl font-display leading-tight tracking-tight pr-8"
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
