import { useEffect, useState } from 'react'
import { getCasesList, CaseListItem, CasesListResponse } from '../../services/api'
import CaseCard from './CaseCard'
import './Dashboard.css'

interface CasesListProps {
  status?: string
  caseType?: string
}

const CasesList = ({ status, caseType }: CasesListProps) => {
  const [cases, setCases] = useState<CaseListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [skip, setSkip] = useState(0)
  const limit = 20

  useEffect(() => {
    loadCases()
  }, [status, caseType, skip])

  const loadCases = async () => {
    setLoading(true)
    try {
      const data: CasesListResponse = await getCasesList(skip, limit, status, caseType)
      setCases(data.cases)
      setTotal(data.total)
    } catch (error) {
      console.error('Ошибка при загрузке дел:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading && cases.length === 0) {
    return (
      <div className="cases-list">
        <div className="cases-list-loading">Загрузка дел...</div>
      </div>
    )
  }

  if (cases.length === 0) {
    return (
      <div className="cases-list">
        <div className="cases-list-empty">
          <div className="cases-list-empty-icon">📁</div>
          <h3>Нет дел</h3>
          <p>Загрузите документы, чтобы создать первое дело</p>
          <p style={{ marginTop: '16px', fontSize: '14px', color: '#a0aec0' }}>
            Нажмите кнопку "Загрузить новое дело" в верхней части страницы
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="cases-list">
      <div className="cases-list-header">
        <h2>Мои дела ({total})</h2>
      </div>
      <div className="cases-list-grid">
        {cases.map((caseItem) => (
          <CaseCard key={caseItem.id} caseItem={caseItem} />
        ))}
      </div>
      {total > skip + limit && (
        <div className="cases-list-pagination">
          <button
            className="cases-list-load-more"
            onClick={() => setSkip(skip + limit)}
            disabled={loading}
          >
            {loading ? 'Загрузка...' : 'Загрузить еще'}
          </button>
        </div>
      )}
    </div>
  )
}

export default CasesList

