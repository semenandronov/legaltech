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
  const [error, setError] = useState<string | null>(null)
  const limit = 20

  useEffect(() => {
    loadCases()
  }, [status, caseType, skip])

  const loadCases = async () => {
    setLoading(true)
    setError(null)
    try {
      const data: CasesListResponse = await getCasesList(skip, limit, status, caseType)
      setCases(data.cases)
      setTotal(data.total)
    } catch (error: any) {
      console.error('Ошибка при загрузке дел:', error)
      setError(error.response?.data?.detail || 'Ошибка при загрузке дел. Попробуйте обновить страницу.')
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

  if (error && cases.length === 0) {
    return (
      <div className="cases-list">
        <div className="cases-list-empty">
          <div className="cases-list-empty-icon">⚠️</div>
          <h3>Ошибка загрузки</h3>
          <p>{error}</p>
          <button
            onClick={loadCases}
            style={{
              marginTop: '16px',
              padding: '8px 16px',
              background: '#4299e1',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer',
            }}
          >
            Попробовать снова
          </button>
        </div>
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
        {error && (
          <div style={{ color: '#ef4444', fontSize: '14px', marginTop: '8px' }}>
            ⚠️ {error}
          </div>
        )}
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

