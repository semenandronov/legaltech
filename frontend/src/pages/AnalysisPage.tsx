import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Sidebar from '../components/Layout/Sidebar'
import Header from '../components/Layout/Header'
import TimelineTab from '../components/Analysis/TimelineTab'
import DiscrepanciesTab from '../components/Analysis/DiscrepanciesTab'
import KeyFactsTab from '../components/Analysis/KeyFactsTab'
import SummaryTab from '../components/Analysis/SummaryTab'
import RiskAnalysisTab from '../components/Analysis/RiskAnalysisTab'
import { startAnalysis, getAnalysisStatus } from '../services/api'
import './AnalysisPage.css'

const AnalysisPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('timeline')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (caseId) {
      loadStatus()
    }
  }, [caseId])

  if (!caseId) {
    return <div>Дело не найдено</div>
  }

  const loadStatus = async () => {
    if (!caseId) return
    try {
      await getAnalysisStatus(caseId)
      // Status loaded, can be used in future
    } catch (error) {
      console.error('Ошибка при загрузке статуса анализа:', error)
    }
  }

  const handleStartAnalysis = async (types: string[]) => {
    if (!caseId) return
    setLoading(true)
    try {
      await startAnalysis(caseId, types)
      // Poll for status updates
      setTimeout(() => loadStatus(), 2000)
    } catch (error) {
      console.error('Ошибка при запуске анализа:', error)
    } finally {
      setLoading(false)
    }
  }

  const tabs = [
    { id: 'timeline', label: '📅 Таймлайн', icon: '📅' },
    { id: 'discrepancies', label: '⚠️ Противоречия', icon: '⚠️' },
    { id: 'key_facts', label: '🎯 Ключевые факты', icon: '🎯' },
    { id: 'summary', label: '📊 Резюме', icon: '📊' },
    { id: 'risks', label: '📈 Анализ рисков', icon: '📈' },
  ]

  return (
    <div className="analysis-page-root">
      <Sidebar />
      <div className="analysis-page-content" style={{ marginLeft: '250px' }}>
        <Header />
        <main className="analysis-page-main">
          <div className="analysis-page-header">
            <div className="analysis-page-header-left">
              <button className="analysis-back-btn" onClick={() => navigate('/')}>
                ← Назад к Dashboard
              </button>
              <h1 className="analysis-page-title">Анализ дела</h1>
            </div>
            <div className="analysis-page-header-right">
              <button
                className="analysis-start-btn"
                onClick={() => handleStartAnalysis(['timeline', 'discrepancies', 'key_facts', 'summary', 'risk_analysis'])}
                disabled={loading}
              >
                {loading ? 'Запуск...' : 'Запустить полный анализ'}
              </button>
            </div>
          </div>

          <div className="analysis-page-tabs">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                className={`analysis-tab ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                <span className="analysis-tab-icon">{tab.icon}</span>
                <span className="analysis-tab-label">{tab.label}</span>
              </button>
            ))}
          </div>

          <div className="analysis-page-content-area">
            {activeTab === 'timeline' && caseId && <TimelineTab caseId={caseId} />}
            {activeTab === 'discrepancies' && caseId && <DiscrepanciesTab caseId={caseId} />}
            {activeTab === 'key_facts' && caseId && <KeyFactsTab caseId={caseId} />}
            {activeTab === 'summary' && caseId && <SummaryTab caseId={caseId} />}
            {activeTab === 'risks' && caseId && <RiskAnalysisTab caseId={caseId} />}
          </div>
        </main>
      </div>
    </div>
  )
}

export default AnalysisPage

