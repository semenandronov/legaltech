import { DiscrepancyItem } from '../../services/api'
import './Analysis.css'

interface DiscrepancyCardProps {
  discrepancy: DiscrepancyItem
}

const DiscrepancyCard = ({ discrepancy }: DiscrepancyCardProps) => {
  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'HIGH':
        return '#ef4444'
      case 'MEDIUM':
        return '#f59e0b'
      case 'LOW':
        return '#10b981'
      default:
        return '#6b7280'
    }
  }

  const getSeverityLabel = (severity: string) => {
    switch (severity) {
      case 'HIGH':
        return 'Высокий риск'
      case 'MEDIUM':
        return 'Средний риск'
      case 'LOW':
        return 'Низкий риск'
      default:
        return severity
    }
  }

  return (
    <div className="discrepancy-card">
      <div className="discrepancy-card-header">
        <div className="discrepancy-card-type">{discrepancy.type}</div>
        <span
          className="discrepancy-card-severity"
          style={{
            backgroundColor: getSeverityColor(discrepancy.severity) + '20',
            color: getSeverityColor(discrepancy.severity),
          }}
        >
          {getSeverityLabel(discrepancy.severity)}
        </span>
      </div>
      <div className="discrepancy-card-description">{discrepancy.description}</div>
      {discrepancy.source_documents && discrepancy.source_documents.length > 0 && (
        <div className="discrepancy-card-sources">
          <div className="discrepancy-card-sources-title">Источники:</div>
          <div className="discrepancy-card-sources-list">
            {discrepancy.source_documents.map((source, idx) => (
              <span key={idx} className="discrepancy-card-source">
                📄 {source}
              </span>
            ))}
          </div>
        </div>
      )}
      {discrepancy.details && Object.keys(discrepancy.details).length > 0 && (
        <div className="discrepancy-card-details">
          <pre>{JSON.stringify(discrepancy.details, null, 2)}</pre>
        </div>
      )}
    </div>
  )
}

export default DiscrepancyCard

