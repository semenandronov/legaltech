import { useEffect, useState } from 'react'
import { getSummary } from '../../services/api'
import './Analysis.css'

interface SummaryTabProps {
  caseId: string
}

const SummaryTab = ({ caseId }: SummaryTabProps) => {
  const [summary, setSummary] = useState<string>('')
  const [keyFacts, setKeyFacts] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadSummary()
  }, [caseId])

  const loadSummary = async () => {
    setLoading(true)
    try {
      const data = await getSummary(caseId)
      setSummary(data.summary || '')
      setKeyFacts(data.key_facts)
    } catch (error) {
      console.error('Ошибка при загрузке резюме:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <div className="analysis-tab-loading">Загрузка резюме...</div>
  }

  if (!summary) {
    return (
      <div className="analysis-tab-empty">
        <div className="analysis-tab-empty-icon">📊</div>
        <h3>Резюме не найдено</h3>
        <p>Запустите анализ для генерации резюме</p>
      </div>
    )
  }

  return (
    <div className="summary-tab">
      <h2>Краткое резюме дела</h2>
      <div className="summary-content">
        <div className="summary-text">{summary}</div>
        {keyFacts && (
          <div className="summary-key-facts">
            <h3>Ключевые факты</h3>
            <pre>{JSON.stringify(keyFacts, null, 2)}</pre>
          </div>
        )}
      </div>
    </div>
  )
}

export default SummaryTab

