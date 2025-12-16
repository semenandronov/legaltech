import { useEffect, useState } from 'react'
import { getRisks } from '../../services/api'
import './Analysis.css'

interface RiskAnalysisTabProps {
  caseId: string
}

const RiskAnalysisTab = ({ caseId }: RiskAnalysisTabProps) => {
  const [analysis, setAnalysis] = useState<string>('')
  const [discrepancies, setDiscrepancies] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadRisks()
  }, [caseId])

  const loadRisks = async () => {
    setLoading(true)
    try {
      const data = await getRisks(caseId)
      setAnalysis(data.analysis || '')
      setDiscrepancies(data.discrepancies)
    } catch (error) {
      console.error('Ошибка при загрузке анализа рисков:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <div className="analysis-tab-loading">Загрузка анализа рисков...</div>
  }

  if (!analysis) {
    return (
      <div className="analysis-tab-empty">
        <div className="analysis-tab-empty-icon">📈</div>
        <h3>Анализ рисков не найден</h3>
        <p>Запустите анализ для оценки рисков</p>
      </div>
    )
  }

  return (
    <div className="risk-analysis-tab">
      <h2>Анализ рисков</h2>
      <div className="risk-analysis-content">
        <div className="risk-analysis-text">{analysis}</div>
        {discrepancies && (
          <div className="risk-analysis-discrepancies">
            <h3>Связанные противоречия</h3>
            <pre>{JSON.stringify(discrepancies, null, 2)}</pre>
          </div>
        )}
      </div>
    </div>
  )
}

export default RiskAnalysisTab

