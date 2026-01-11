import React, { useEffect } from 'react'
import { DocumentWithMetadata } from './DocumentsList'
import PDFViewer from './PDFViewer'
import { OpenInNew as OpenInNewIcon } from '@mui/icons-material'
import { IconButton, Box, Typography, Button } from '@mui/material'
import './Documents.css'

interface DocumentViewerProps {
  document: DocumentWithMetadata | null
  caseId: string
  onNavigateNext?: () => void
  onNavigatePrev?: () => void
}

const DocumentViewer: React.FC<DocumentViewerProps> = ({
  document,
  caseId,
}) => {
  const handleOpenOriginal = async () => {
    if (!document?.id || !caseId) return
    try {
      const baseUrl = import.meta.env.VITE_API_URL || ''
      const url = baseUrl 
        ? `${baseUrl}/api/cases/${caseId}/files/${document.id}/download`
        : `/api/cases/${caseId}/files/${document.id}/download`
      const response = await fetch(url, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`
        }
      })
      if (response.ok) {
        const blob = await response.blob()
        const blobUrl = window.URL.createObjectURL(blob)
        window.open(blobUrl, '_blank')
        setTimeout(() => window.URL.revokeObjectURL(blobUrl), 100)
      }
    } catch (error) {
      console.error('Ошибка при открытии документа:', error)
    }
  }

  useEffect(() => {
    // Для не-PDF файлов сразу открываем в оригинале
    if (document?.id && document.file_type !== 'pdf' && caseId) {
      handleOpenOriginal()
    }
  }, [document?.id, caseId, document?.file_type])

  if (!document) {
    return (
      <div className="document-viewer-empty">
        <div className="document-viewer-empty-content">
          <div className="document-viewer-empty-icon">📄</div>
          <h3>Выберите документ для просмотра</h3>
          <p>Кликните на документ в левой панели, чтобы открыть его здесь</p>
        </div>
      </div>
    )
  }

  return (
    <div className="document-viewer" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div className="document-viewer-content" style={{ flex: 1, overflow: 'auto' }}>
        {document.file_type === 'pdf' ? (
          <PDFViewer
            fileId={document.id}
            caseId={caseId}
            filename={document.filename}
            onError={(error) => {
              console.error('PDF viewer error:', error)
            }}
            showTabs={false}
            showAbout={false}
          />
        ) : (
          <div className="document-viewer-text" style={{ padding: '20px', textAlign: 'center', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
            <Typography variant="body1" sx={{ mb: 2 }}>
              Документ открывается в оригинальном формате...
            </Typography>
            <Button
              variant="contained"
              startIcon={<OpenInNewIcon />}
              onClick={handleOpenOriginal}
              sx={{ textTransform: 'none' }}
            >
              Открыть оригинальный файл
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}

export default DocumentViewer

