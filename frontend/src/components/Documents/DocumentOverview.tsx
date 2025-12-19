import React, { useState } from 'react'
import './Documents.css'

interface DocumentOverviewProps {
  totalFiles: number
  relevantCount: number
  privilegedCount: number
  notRelevantCount: number
  processingTime?: string
  todayProcessed?: number
  onDownloadAuditLog?: () => void
}

const DocumentOverview: React.FC<DocumentOverviewProps> = ({
  totalFiles,
  relevantCount,
  privilegedCount,
  notRelevantCount,
  processingTime,
  todayProcessed,
  onDownloadAuditLog
}) => {
  const [isCollapsed, setIsCollapsed] = useState(false)

  const relevantPercent = totalFiles > 0 ? Math.round((relevantCount / totalFiles) * 100) : 0
  const privilegedPercent = totalFiles > 0 ? Math.round((privilegedCount / totalFiles) * 100) : 0
  const notRelevantPercent = totalFiles > 0 ? Math.round((notRelevantCount / totalFiles) * 100) : 0

  if (isCollapsed) {
    return (
      <div className="document-overview collapsed">
        <button
          className="document-overview-toggle"
          onClick={() => setIsCollapsed(false)}
          aria-label="Развернуть overview"
        >
          <span>📊</span>
          <span>Overview</span>
          <span>▼</span>
        </button>
      </div>
    )
  }

  return (
    <div className="document-overview">
      <div className="document-overview-header">
        <h3 className="document-overview-title">📊 Overview</h3>
        <button
          className="document-overview-toggle"
          onClick={() => setIsCollapsed(true)}
          aria-label="Свернуть overview"
        >
          ▲
        </button>
      </div>
      
      <div className="document-overview-stats">
        <div className="document-overview-stat">
          <span className="document-overview-stat-label">📈 Total:</span>
          <span className="document-overview-stat-value">{totalFiles.toLocaleString()}</span>
        </div>
        
        <div className="document-overview-stat">
          <span className="document-overview-stat-label">🟢 Relevant:</span>
          <span className="document-overview-stat-value">{relevantCount.toLocaleString()} ({relevantPercent}%)</span>
        </div>
        
        <div className="document-overview-stat">
          <span className="document-overview-stat-label">🔒 Privileged:</span>
          <span className="document-overview-stat-value">{privilegedCount.toLocaleString()} ({privilegedPercent}%)</span>
        </div>
        
        <div className="document-overview-stat">
          <span className="document-overview-stat-label">🔴 Not relevant:</span>
          <span className="document-overview-stat-value">{notRelevantCount.toLocaleString()} ({notRelevantPercent}%)</span>
        </div>
        
        {processingTime && (
          <div className="document-overview-stat">
            <span className="document-overview-stat-label">⏱️ Processing time:</span>
            <span className="document-overview-stat-value">{processingTime}</span>
          </div>
        )}
        
        {todayProcessed !== undefined && (
          <div className="document-overview-stat">
            <span className="document-overview-stat-label">📊 Today:</span>
            <span className="document-overview-stat-value">+{todayProcessed.toLocaleString()} processed</span>
          </div>
        )}
      </div>
      
      {onDownloadAuditLog && (
        <button
          className="document-overview-download-btn"
          onClick={onDownloadAuditLog}
          aria-label="Скачать Audit Log PDF"
        >
          📄 Download Audit Log PDF
        </button>
      )}
    </div>
  )
}

export default DocumentOverview
