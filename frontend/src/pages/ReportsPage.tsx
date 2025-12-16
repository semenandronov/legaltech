import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Sidebar from '../components/Layout/Sidebar'
import Header from '../components/Layout/Header'
import ReportTemplates from '../components/Reports/ReportTemplates'
import ReportList from '../components/Reports/ReportList'
import { getReportsList } from '../services/api'
import './ReportsPage.css'

const ReportsPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()
  const [availableReports, setAvailableReports] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (caseId) {
      loadReports()
    }
  }, [caseId])

  if (!caseId) {
    return <div>Дело не найдено</div>
  }

  const loadReports = async () => {
    if (!caseId) return
    setLoading(true)
    try {
      const data = await getReportsList(caseId)
      setAvailableReports(data.available_reports || [])
    } catch (error) {
      console.error('Ошибка при загрузке отчетов:', error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="reports-page-root">
      <Sidebar />
      <div className="reports-page-content" style={{ marginLeft: '250px' }}>
        <Header />
        <main className="reports-page-main">
          <div className="reports-page-header">
            <button className="reports-back-btn" onClick={() => navigate('/')}>
              ← Назад к Dashboard
            </button>
            <h1 className="reports-page-title">Отчеты</h1>
          </div>

          {loading ? (
            <div className="reports-loading">Загрузка...</div>
          ) : (
            <div className="reports-content">
              {caseId && (
                <>
                  <ReportTemplates caseId={caseId} availableReports={availableReports} />
                  <ReportList caseId={caseId} />
                </>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

export default ReportsPage

