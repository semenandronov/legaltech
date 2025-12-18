import { useNavigate } from 'react-router-dom'
import { CaseListItem } from '../../services/api'
import './Dashboard.css'

interface CaseCardProps {
  caseItem: CaseListItem
}

const CaseCard = ({ caseItem }: CaseCardProps) => {
  const navigate = useNavigate()

  const handleClick = () => {
    navigate(`/cases/${caseItem.id}/chat`)
  }

  const handleAnalysisClick = (e: React.MouseEvent) => {
    e.stopPropagation() // Prevent card click
    navigate(`/cases/${caseItem.id}/analysis`)
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return '#10b981'
      case 'processing':
        return '#f59e0b'
      case 'failed':
        return '#ef4444'
      default:
        return '#6b7280'
    }
  }

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'completed':
        return 'Завершено'
      case 'processing':
        return 'В процессе'
      case 'failed':
        return 'Ошибка'
      default:
        return 'Ожидает'
    }
  }

  const getTypeLabel = (type: string | null) => {
    if (!type) return 'Другое'
    const types: Record<string, string> = {
      litigation: 'Судебное дело',
      contracts: 'Контракты',
      dd: 'Due Diligence',
      compliance: 'Compliance',
    }
    return types[type] || type
  }

  return (
    <div className="case-card" onClick={handleClick}>
      <div className="case-card-header">
        <h3 className="case-card-title">{caseItem.title || 'Без названия'}</h3>
        <span
          className="case-card-status"
          style={{ backgroundColor: getStatusColor(caseItem.status) + '20', color: getStatusColor(caseItem.status) }}
        >
          {getStatusLabel(caseItem.status)}
        </span>
      </div>
      <div className="case-card-body">
        <div className="case-card-info">
          <span className="case-card-type">{getTypeLabel(caseItem.case_type)}</span>
          <span className="case-card-documents">{caseItem.num_documents} документов</span>
        </div>
        <div className="case-card-actions">
          <button
            className="case-card-analysis-btn"
            onClick={handleAnalysisClick}
            title="Перейти к анализу"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 12px',
              background: '#4299e1',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: '500',
              transition: 'all 0.2s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = '#3182ce'
              e.currentTarget.style.transform = 'translateY(-1px)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = '#4299e1'
              e.currentTarget.style.transform = 'translateY(0)'
            }}
          >
            <span>📊</span>
            <span>Анализ</span>
          </button>
        </div>
        <div className="case-card-date">
          Обновлено: {new Date(caseItem.updated_at).toLocaleDateString('ru-RU')}
        </div>
      </div>
    </div>
  )
}

export default CaseCard

