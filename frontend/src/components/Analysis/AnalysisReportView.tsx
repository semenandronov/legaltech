import React from 'react'
import { AnalysisReport } from '../../services/api'
import './Analysis.css'

interface AnalysisReportViewProps {
  report: AnalysisReport
  onFileClick?: (fileId: string) => void
}

const AnalysisReportView: React.FC<AnalysisReportViewProps> = ({
  report,
  onFileClick
}) => {
  const { categorization, statistics, summary } = report

  return (
    <div className="analysis-report-view">
      <div className="analysis-report-header">
        <h2>Analysis Report: {report.case_title || report.case_id}</h2>
        <div className="analysis-report-summary">
          {summary.message}
        </div>
      </div>

      <div className="analysis-report-categorization">
        <div className="analysis-report-category high-relevance">
          <div className="analysis-report-category-header">
            <span className="analysis-report-category-icon">✅</span>
            <h3>{categorization.high_relevance.label}</h3>
            <span className="analysis-report-category-count">
              {categorization.high_relevance.count}
            </span>
          </div>
          <div className="analysis-report-category-files">
            {categorization.high_relevance.files.slice(0, 10).map((file: any, idx: number) => (
              <div
                key={idx}
                className="analysis-report-file-item"
                onClick={() => onFileClick?.(file.file_id)}
                style={{ cursor: onFileClick ? 'pointer' : 'default' }}
              >
                {file.filename}
              </div>
            ))}
            {categorization.high_relevance.files.length > 10 && (
              <div className="analysis-report-more">
                +{categorization.high_relevance.files.length - 10} more
              </div>
            )}
          </div>
        </div>

        <div className="analysis-report-category privileged">
          <div className="analysis-report-category-header">
            <span className="analysis-report-category-icon">🔒</span>
            <h3>{categorization.privileged.label}</h3>
            <span className="analysis-report-category-count critical">
              {categorization.privileged.count}
            </span>
          </div>
          {categorization.privileged.warning && (
            <div className="analysis-report-warning">
              ⚠️ {categorization.privileged.warning}
            </div>
          )}
          <div className="analysis-report-category-files">
            {categorization.privileged.files.slice(0, 10).map((file: any, idx: number) => (
              <div
                key={idx}
                className="analysis-report-file-item privileged"
                onClick={() => onFileClick?.(file.file_id)}
                style={{ cursor: onFileClick ? 'pointer' : 'default' }}
              >
                {file.filename}
              </div>
            ))}
            {categorization.privileged.files.length > 10 && (
              <div className="analysis-report-more">
                +{categorization.privileged.files.length - 10} more
              </div>
            )}
          </div>
        </div>

        <div className="analysis-report-category low-relevance">
          <div className="analysis-report-category-header">
            <span className="analysis-report-category-icon">🗑️</span>
            <h3>{categorization.low_relevance.label}</h3>
            <span className="analysis-report-category-count">
              {categorization.low_relevance.count}
            </span>
          </div>
        </div>
      </div>

      <div className="analysis-report-statistics">
        <h3>Statistics</h3>
        <div className="analysis-report-stats-grid">
          <div className="analysis-report-stat-item">
            <span className="analysis-report-stat-label">Total Entities:</span>
            <span className="analysis-report-stat-value">{statistics.total_entities}</span>
          </div>
          <div className="analysis-report-stat-item">
            <span className="analysis-report-stat-label">Timeline Events:</span>
            <span className="analysis-report-stat-value">{statistics.timeline_events}</span>
          </div>
          <div className="analysis-report-stat-item">
            <span className="analysis-report-stat-label">Discrepancies:</span>
            <span className="analysis-report-stat-value">{statistics.discrepancies}</span>
          </div>
          <div className="analysis-report-stat-item">
            <span className="analysis-report-stat-label">Classified Files:</span>
            <span className="analysis-report-stat-value">{statistics.classified_files}</span>
          </div>
          <div className="analysis-report-stat-item">
            <span className="analysis-report-stat-label">Privilege Checked:</span>
            <span className="analysis-report-stat-value">{statistics.privilege_checked_files}</span>
          </div>
        </div>

        {Object.keys(statistics.entities_by_type).length > 0 && (
          <div className="analysis-report-entities-by-type">
            <h4>Entities by Type:</h4>
            <div className="analysis-report-entities-grid">
              {Object.entries(statistics.entities_by_type).map(([type, count]) => (
                <div key={type} className="analysis-report-entity-type">
                  <span className="analysis-report-entity-type-name">{type}:</span>
                  <span className="analysis-report-entity-type-count">{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default AnalysisReportView
