import { useEffect, useState } from 'react'
import { getDiscrepancies, DiscrepancyItem } from '../../services/api'
import DiscrepancyCard from './DiscrepancyCard'
import './Analysis.css'

interface DiscrepanciesTabProps {
  caseId: string
}

const DiscrepanciesTab = ({ caseId }: DiscrepanciesTabProps) => {
  const [discrepancies, setDiscrepancies] = useState<DiscrepancyItem[]>([])
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'HIGH' | 'MEDIUM' | 'LOW'>('all')

  useEffect(() => {
    loadDiscrepancies()
  }, [caseId])

  const loadDiscrepancies = async () => {
    setLoading(true)
    try {
      const data = await getDiscrepancies(caseId)
      setDiscrepancies(data.discrepancies)
      setStats({
        total: data.total,
        high_risk: data.high_risk,
        medium_risk: data.medium_risk,
        low_risk: data.low_risk,
      })
    } catch (error) {
      console.error('Ошибка при загрузке противоречий:', error)
    } finally {
      setLoading(false)
    }
  }

  const filteredDiscrepancies = filter === 'all' 
    ? discrepancies 
    : discrepancies.filter(d => d.severity === filter)

  if (loading) {
    return <div className="analysis-tab-loading">Загрузка противоречий...</div>
  }

  if (discrepancies.length === 0) {
    return (
      <div className="analysis-tab-empty">
        <div className="analysis-tab-empty-icon">⚠️</div>
        <h3>Противоречия не найдены</h3>
        <p>Запустите анализ для поиска противоречий в документах</p>
      </div>
    )
  }

  return (
    <div className="discrepancies-tab">
      <div className="discrepancies-tab-header">
        <div>
          <h2>Найдено противоречий: {stats?.total || 0}</h2>
          <div className="discrepancies-stats">
            <span className="discrepancy-stat high">
              HIGH: {stats?.high_risk || 0}
            </span>
            <span className="discrepancy-stat medium">
              MEDIUM: {stats?.medium_risk || 0}
            </span>
            <span className="discrepancy-stat low">
              LOW: {stats?.low_risk || 0}
            </span>
          </div>
        </div>
        <div className="discrepancies-filters">
          <button
            className={`discrepancy-filter ${filter === 'all' ? 'active' : ''}`}
            onClick={() => setFilter('all')}
          >
            Все
          </button>
          <button
            className={`discrepancy-filter ${filter === 'HIGH' ? 'active' : ''}`}
            onClick={() => setFilter('HIGH')}
          >
            HIGH
          </button>
          <button
            className={`discrepancy-filter ${filter === 'MEDIUM' ? 'active' : ''}`}
            onClick={() => setFilter('MEDIUM')}
          >
            MEDIUM
          </button>
          <button
            className={`discrepancy-filter ${filter === 'LOW' ? 'active' : ''}`}
            onClick={() => setFilter('LOW')}
          >
            LOW
          </button>
        </div>
      </div>
      <div className="discrepancies-list">
        {filteredDiscrepancies.map((discrepancy) => (
          <DiscrepancyCard key={discrepancy.id} discrepancy={discrepancy} />
        ))}
      </div>
    </div>
  )
}

export default DiscrepanciesTab

