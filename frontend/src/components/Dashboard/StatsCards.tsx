import { useEffect, useState } from 'react'
import { getDashboardStats, DashboardStats } from '../../services/api'
import './Dashboard.css'

const StatsCards = () => {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const loadStats = async () => {
      try {
        const data = await getDashboardStats()
        setStats(data)
        setError(null)
      } catch (error: any) {
        console.error('Ошибка при загрузке статистики:', error)
        setError('Не удалось загрузить статистику')
      } finally {
        setLoading(false)
      }
    }

    loadStats()
  }, [])

  if (loading) {
    return (
      <div className="stats-cards">
        <div className="stat-card loading">Загрузка...</div>
        <div className="stat-card loading">Загрузка...</div>
        <div className="stat-card loading">Загрузка...</div>
        <div className="stat-card loading">Загрузка...</div>
      </div>
    )
  }

  if (error || !stats) {
    return (
      <div className="stats-cards">
        <div className="stat-card" style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '20px' }}>
          <div style={{ color: '#ef4444' }}>⚠️ {error || 'Не удалось загрузить статистику'}</div>
        </div>
      </div>
    )
  }

  return (
    <div className="stats-cards">
      <div className="stat-card">
        <div className="stat-card-icon">📁</div>
        <div className="stat-card-content">
          <div className="stat-card-value">{stats.total_cases}</div>
          <div className="stat-card-label">Всего дел</div>
          <div className="stat-card-sublabel">+{stats.cases_this_month} в этом месяце</div>
        </div>
      </div>

      <div className="stat-card">
        <div className="stat-card-icon">📄</div>
        <div className="stat-card-content">
          <div className="stat-card-value">{stats.total_documents}</div>
          <div className="stat-card-label">Документов</div>
          <div className="stat-card-sublabel">+{stats.documents_this_month} в этом месяце</div>
        </div>
      </div>

      <div className="stat-card">
        <div className="stat-card-icon">🔍</div>
        <div className="stat-card-content">
          <div className="stat-card-value">{stats.total_analyses}</div>
          <div className="stat-card-label">Анализов</div>
          <div className="stat-card-sublabel">+{stats.analyses_this_month} в этом месяце</div>
        </div>
      </div>

      <div className="stat-card">
        <div className="stat-card-icon">⚡</div>
        <div className="stat-card-content">
          <div className="stat-card-value">
            {stats.total_cases > 0
              ? Math.round((stats.total_analyses / stats.total_cases) * 100)
              : 0}
            %
          </div>
          <div className="stat-card-label">Покрытие анализом</div>
          <div className="stat-card-sublabel">Процент проанализированных дел</div>
        </div>
      </div>
    </div>
  )
}

export default StatsCards

