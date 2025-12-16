import { useState } from 'react'
import { generateReport } from '../../services/api'
import './Reports.css'

interface ReportTemplatesProps {
  caseId: string
  availableReports: any[]
}

const ReportTemplates = ({ caseId, availableReports }: ReportTemplatesProps) => {
  const [generating, setGenerating] = useState<string | null>(null)

  const handleGenerate = async (reportType: string, format: string) => {
    setGenerating(`${reportType}_${format}`)
    try {
      const blob = await generateReport(caseId, reportType, format)
      
      // Create download link
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${reportType}_${caseId}.${format === 'word' ? 'docx' : format === 'pdf' ? 'pdf' : 'xlsx'}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Ошибка при генерации отчета:', error)
      alert('Ошибка при генерации отчета')
    } finally {
      setGenerating(null)
    }
  }

  return (
    <div className="report-templates">
      <h2 className="report-templates-title">Шаблоны отчетов</h2>
      <div className="report-templates-grid">
        {availableReports.map((report) => (
          <div key={report.type} className="report-template-card">
            <h3 className="report-template-name">{report.name}</h3>
            <p className="report-template-description">{report.description}</p>
            <div className="report-template-formats">
              {report.formats.map((format: string) => (
                <button
                  key={format}
                  className="report-generate-btn"
                  onClick={() => handleGenerate(report.type, format)}
                  disabled={generating === `${report.type}_${format}`}
                >
                  {generating === `${report.type}_${format}` 
                    ? 'Генерация...' 
                    : `Скачать ${format.toUpperCase()}`}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default ReportTemplates

