import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getReportsList, generateReport, AvailableReport } from '../services/api'
import MainLayout from '../components/Layout/MainLayout'
import CaseNavigation from '../components/CaseOverview/CaseNavigation'
import Card from '../components/UI/Card'
import Button from '../components/UI/Button'
import Radio from '../components/UI/Radio'
import Checkbox from '../components/UI/Checkbox'
import Select from '../components/UI/Select'
import Input from '../components/UI/Input'
import Spinner from '../components/UI/Spinner'

const ReportsPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()
  const [availableReports, setAvailableReports] = useState<AvailableReport[]>([])
  const [loading, setLoading] = useState(true)
  const [reportType, setReportType] = useState('case_memo')
  const [sections, setSections] = useState<string[]>(['executive_summary'])
  const [format, setFormat] = useState('docx')
  const [email, setEmail] = useState('')
  const [downloading, setDownloading] = useState(false)
  
  useEffect(() => {
    if (caseId) {
      loadReports()
    }
  }, [caseId])
  
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
  
  const handleSectionToggle = (section: string) => {
    setSections(prev =>
      prev.includes(section)
        ? prev.filter(s => s !== section)
        : [...prev, section]
    )
  }
  
  const handleGenerate = async () => {
    if (!caseId) return
    setDownloading(true)
    try {
      await generateReport(caseId, reportType, format)
      // TODO: handle download or email sending
      alert('Отчет успешно сгенерирован!')
    } catch (error) {
      console.error('Ошибка при генерации отчета:', error)
      alert('Ошибка при генерации отчета')
    } finally {
      setDownloading(false)
    }
  }
  
  const sectionOptions = [
    { value: 'executive_summary', label: 'Executive Summary' },
    { value: 'key_facts', label: 'Key Facts & Timeline' },
    { value: 'risk_assessment', label: 'Risk Assessment (High/Medium/Low)' },
    { value: 'contradictions', label: 'Contradictions & Issues' },
    { value: 'recommendations', label: 'Recommendations' },
    { value: 'document_index', label: 'Document Index' },
    { value: 'sources', label: 'Sources & Methodology' },
  ]
  
  if (loading) {
    return (
      <MainLayout>
        <div className="flex items-center justify-center h-full">
          <Spinner size="lg" />
        </div>
      </MainLayout>
    )
  }
  
  return (
    <MainLayout>
      <div className="flex h-full">
        {caseId && <CaseNavigation caseId={caseId} />}
        <div className="flex-1 overflow-y-auto p-6">
          <h1 className="text-h1 text-primary mb-6">📊 Генерация отчёта</h1>
          
          <Card className="max-w-3xl">
            <div className="space-y-6">
              {/* Report Type */}
              <div>
                <h3 className="text-h3 text-primary mb-4">Тип отчёта</h3>
                <div className="space-y-2">
                  <Radio
                    label="Case Memo (обзор + рекомендации)"
                    checked={reportType === 'case_memo'}
                    onChange={() => setReportType('case_memo')}
                  />
                  <Radio
                    label="Risk Report (детальный анализ рисков)"
                    checked={reportType === 'risk_report'}
                    onChange={() => setReportType('risk_report')}
                  />
                  <Radio
                    label="Document Index (список с аннотациями)"
                    checked={reportType === 'document_index'}
                    onChange={() => setReportType('document_index')}
                  />
                </div>
              </div>
              
              {/* Sections */}
              <div>
                <h3 className="text-h3 text-primary mb-4">Секции отчёта</h3>
                <div className="space-y-2">
                  {sectionOptions.map((option) => (
                    <Checkbox
                      key={option.value}
                      label={option.label}
                      checked={sections.includes(option.value)}
                      onChange={(e) => handleSectionToggle(option.value)}
                    />
                  ))}
                </div>
              </div>
              
              {/* Format */}
              <div>
                <h3 className="text-h3 text-primary mb-4">Формат</h3>
                <div className="space-y-2">
                  <Radio
                    label="DOCX (редактируемый в Word)"
                    checked={format === 'docx'}
                    onChange={() => setFormat('docx')}
                  />
                  <Radio
                    label="PDF (для обмена, защищённый)"
                    checked={format === 'pdf'}
                    onChange={() => setFormat('pdf')}
                  />
                  <Radio
                    label="HTML (для веб-обмена)"
                    checked={format === 'html'}
                    onChange={() => setFormat('html')}
                  />
                </div>
              </div>
              
              {/* Recipient */}
              <div>
                <h3 className="text-h3 text-primary mb-4">Получатель</h3>
                <Input
                  type="email"
                  placeholder="Email для отправки (опционально)"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
                <p className="text-small text-secondary mt-2">
                  Или оставьте пустым, чтобы скачать файл
                </p>
              </div>
              
              {/* Actions */}
              <div className="flex items-center gap-4 pt-4 border-t border-border">
                <Button
                  variant="primary"
                  onClick={handleGenerate}
                  isLoading={downloading}
                >
                  {downloading ? 'Генерация...' : 'Сгенерировать и отправить'}
                </Button>
                <Button variant="secondary" onClick={() => navigate(-1)}>
                  Отмена
                </Button>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </MainLayout>
  )
}

export default ReportsPage