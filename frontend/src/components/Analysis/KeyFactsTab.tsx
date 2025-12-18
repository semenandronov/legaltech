import { useEffect, useState } from 'react'
import { getKeyFacts } from '../../services/api'
import './Analysis.css'

interface KeyFactsTabProps {
  caseId: string
}

const KeyFactsTab = ({ caseId }: KeyFactsTabProps) => {
  const [facts, setFacts] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadKeyFacts()
  }, [caseId])

  const loadKeyFacts = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getKeyFacts(caseId)
      setFacts(data.facts)
    } catch (error: any) {
      console.error('Ошибка при загрузке ключевых фактов:', error)
      setError(error.response?.data?.detail || 'Ошибка при загрузке ключевых фактов')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <div className="analysis-tab-loading">Загрузка ключевых фактов...</div>
  }

  if (error) {
    return (
      <div className="analysis-tab-empty">
        <div className="analysis-tab-empty-icon">⚠️</div>
        <h3>Ошибка загрузки</h3>
        <p>{error}</p>
        <button
          onClick={loadKeyFacts}
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
    )
  }

  if (!facts || Object.keys(facts).length === 0) {
    return (
      <div className="analysis-tab-empty">
        <div className="analysis-tab-empty-icon">🎯</div>
        <h3>Ключевые факты не найдены</h3>
        <p>Запустите анализ для извлечения ключевых фактов</p>
      </div>
    )
  }

  return (
    <div className="key-facts-tab">
      <h2>Ключевые факты дела</h2>
      <div className="key-facts-content">
        {facts.parties && (
          <div className="key-facts-section">
            <h3>Стороны спора</h3>
            <div className="key-facts-item">
              <strong>Истец:</strong> {facts.parties.plaintiff || 'Не указан'}
            </div>
            <div className="key-facts-item">
              <strong>Ответчик:</strong> {facts.parties.defendant || 'Не указан'}
            </div>
          </div>
        )}

        {facts.amounts && (
          <div className="key-facts-section">
            <h3>Финансовые данные</h3>
            {facts.amounts.dispute_amount && (
              <div className="key-facts-item">
                <strong>Сумма спора:</strong> {facts.amounts.dispute_amount}
              </div>
            )}
            {facts.amounts.penalty && (
              <div className="key-facts-item">
                <strong>Неустойка:</strong> {facts.amounts.penalty}
              </div>
            )}
          </div>
        )}

        {facts.key_dates && Object.keys(facts.key_dates).length > 0 && (
          <div className="key-facts-section">
            <h3>Ключевые даты</h3>
            {Object.entries(facts.key_dates).map(([key, value]: [string, any]) => (
              <div key={key} className="key-facts-item">
                <strong>{key}:</strong> {value || 'Не указано'}
              </div>
            ))}
          </div>
        )}

        {facts.dispute_essence && (
          <div className="key-facts-section">
            <h3>Суть спора</h3>
            <div className="key-facts-item">{facts.dispute_essence}</div>
          </div>
        )}

        {facts.court && (
          <div className="key-facts-section">
            <h3>Суд</h3>
            {facts.court.name && (
              <div className="key-facts-item">
                <strong>Название:</strong> {facts.court.name}
              </div>
            )}
            {facts.court.judge && (
              <div className="key-facts-item">
                <strong>Судья:</strong> {facts.court.judge}
              </div>
            )}
          </div>
        )}

        {facts.other_facts && facts.other_facts.length > 0 && (
          <div className="key-facts-section">
            <h3>Другие факты</h3>
            <ul className="key-facts-list">
              {facts.other_facts.map((fact: string, idx: number) => (
                <li key={idx}>{fact}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

export default KeyFactsTab

