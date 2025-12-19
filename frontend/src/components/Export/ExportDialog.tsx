import React, { useState } from 'react'
import './Export.css'

export type ExportFormat = 'REL' | 'PDF' | 'CSV' | 'JSON' | 'EDRM_XML'

export interface ExportOptions {
  formats: ExportFormat[]
  includeAuditLog: boolean
  includeCertification: boolean
  includeChainOfCustody: boolean
  filters?: {
    status?: string[]
    dateFrom?: string
    dateTo?: string
    searchQuery?: string
  }
  destination?: 'download' | 'email' | 's3'
}

interface ExportDialogProps {
  caseId: string
  onClose: () => void
  onExport: (options: ExportOptions) => Promise<void>
}

const ExportDialog: React.FC<ExportDialogProps> = ({
  caseId,
  onClose,
  onExport
}) => {
  const [formats, setFormats] = useState<ExportFormat[]>(['REL'])
  const [includeAuditLog, setIncludeAuditLog] = useState(true)
  const [includeCertification, setIncludeCertification] = useState(false)
  const [includeChainOfCustody, setIncludeChainOfCustody] = useState(false)
  const [destination, setDestination] = useState<'download' | 'email' | 's3'>('download')
  const [loading, setLoading] = useState(false)

  const handleFormatToggle = (format: ExportFormat) => {
    setFormats(prev => {
      if (prev.includes(format)) {
        return prev.filter(f => f !== format)
      }
      return [...prev, format]
    })
  }

  const handleExport = async () => {
    if (formats.length === 0) {
      alert('Выберите хотя бы один формат')
      return
    }

    setLoading(true)
    try {
      await onExport({
        formats,
        includeAuditLog,
        includeCertification,
        includeChainOfCustody,
        destination
      })
      onClose()
    } catch (err) {
      console.error('Export error:', err)
      alert('Ошибка при экспорте')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="export-dialog-overlay" onClick={onClose}>
      <div className="export-dialog-modal" onClick={(e) => e.stopPropagation()}>
        <div className="export-dialog-header">
          <h2>Export Documents</h2>
          <button className="export-dialog-close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </div>

        <div className="export-dialog-content">
          <div className="export-dialog-section">
            <h3>Formats</h3>
            <div className="export-dialog-formats">
              <label className="export-dialog-checkbox">
                <input
                  type="checkbox"
                  checked={formats.includes('REL')}
                  onChange={() => handleFormatToggle('REL')}
                />
                <span>☑ REL format (для суда)</span>
              </label>
              <label className="export-dialog-checkbox">
                <input
                  type="checkbox"
                  checked={formats.includes('PDF')}
                  onChange={() => handleFormatToggle('PDF')}
                />
                <span>☑ PDF report (with bates numbers)</span>
              </label>
              <label className="export-dialog-checkbox">
                <input
                  type="checkbox"
                  checked={formats.includes('CSV')}
                  onChange={() => handleFormatToggle('CSV')}
                />
                <span>☑ CSV (with metadata)</span>
              </label>
              <label className="export-dialog-checkbox">
                <input
                  type="checkbox"
                  checked={formats.includes('JSON')}
                  onChange={() => handleFormatToggle('JSON')}
                />
                <span>☑ JSON (для API integration)</span>
              </label>
              <label className="export-dialog-checkbox">
                <input
                  type="checkbox"
                  checked={formats.includes('EDRM_XML')}
                  onChange={() => handleFormatToggle('EDRM_XML')}
                />
                <span>☑ EDRM XML</span>
              </label>
            </div>
          </div>

          <div className="export-dialog-section">
            <h3>Options</h3>
            <div className="export-dialog-options">
              <label className="export-dialog-checkbox required">
                <input
                  type="checkbox"
                  checked={includeAuditLog}
                  onChange={(e) => setIncludeAuditLog(e.target.checked)}
                />
                <span>☑ Include audit log (REQUIRED!)</span>
              </label>
              <label className="export-dialog-checkbox">
                <input
                  type="checkbox"
                  checked={includeCertification}
                  onChange={(e) => setIncludeCertification(e.target.checked)}
                />
                <span>☑ Certification statement</span>
              </label>
              <label className="export-dialog-checkbox">
                <input
                  type="checkbox"
                  checked={includeChainOfCustody}
                  onChange={(e) => setIncludeChainOfCustody(e.target.checked)}
                />
                <span>☑ Chain of custody</span>
              </label>
            </div>
          </div>

          <div className="export-dialog-section">
            <h3>Destination</h3>
            <div className="export-dialog-destination">
              <label className="export-dialog-radio">
                <input
                  type="radio"
                  name="destination"
                  value="download"
                  checked={destination === 'download'}
                  onChange={() => setDestination('download')}
                />
                <span>Download</span>
              </label>
              <label className="export-dialog-radio">
                <input
                  type="radio"
                  name="destination"
                  value="email"
                  checked={destination === 'email'}
                  onChange={() => setDestination('email')}
                />
                <span>Email</span>
              </label>
              <label className="export-dialog-radio">
                <input
                  type="radio"
                  name="destination"
                  value="s3"
                  checked={destination === 's3'}
                  onChange={() => setDestination('s3')}
                />
                <span>S3</span>
              </label>
            </div>
          </div>
        </div>

        <div className="export-dialog-actions">
          <button
            className="export-dialog-cancel"
            onClick={onClose}
            disabled={loading}
          >
            Cancel
          </button>
          <button
            className="export-dialog-export"
            onClick={handleExport}
            disabled={loading || formats.length === 0}
          >
            {loading ? 'Exporting...' : 'Export'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ExportDialog
