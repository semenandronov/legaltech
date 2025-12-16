import './Reports.css'

interface ReportListProps {
  caseId: string
}

const ReportList = ({ caseId }: ReportListProps) => {
  // In future, this would load saved reports from backend
  const savedReports: any[] = []

  if (savedReports.length === 0) {
    return (
      <div className="report-list">
        <h2 className="report-list-title">Сохраненные отчеты</h2>
        <div className="report-list-empty">
          <p>Нет сохраненных отчетов</p>
        </div>
      </div>
    )
  }

  return (
    <div className="report-list">
      <h2 className="report-list-title">Сохраненные отчеты</h2>
      <div className="report-list-items">
        {savedReports.map((report) => (
          <div key={report.id} className="report-list-item">
            <div className="report-list-item-info">
              <div className="report-list-item-name">{report.name}</div>
              <div className="report-list-item-date">
                Создан: {new Date(report.created_at).toLocaleDateString('ru-RU')}
              </div>
            </div>
            <div className="report-list-item-actions">
              <button className="report-download-btn">Скачать</button>
              <button className="report-delete-btn">Удалить</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default ReportList

