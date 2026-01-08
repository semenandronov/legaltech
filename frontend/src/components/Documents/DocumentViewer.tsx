import React, { useState, useEffect } from 'react'
import { DocumentWithMetadata } from './DocumentsList'
import PDFViewer from './PDFViewer'
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
  const [documentText, setDocumentText] = useState<string>('')

  useEffect(() => {
    if (document?.id && document.file_type !== 'pdf') {
      loadDocumentText()
    }
  }, [document?.id, caseId])

  const loadDocumentText = async () => {
    if (!document?.id || !caseId) return
    try {
      const response = await fetch(`/api/cases/${caseId}/files/${document.id}/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`
        }
      })
      if (response.ok) {
        const text = await response.text()
        setDocumentText(text)
      }
    } catch (err) {
      console.error('Ошибка при загрузке текста документа:', err)
      setDocumentText('Ошибка при загрузке содержимого документа')
    }
  }

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
              loadDocumentText()
            }}
            showTabs={false}
            showAbout={false}
          />
        ) : (
          <div className="document-viewer-text" style={{ padding: '20px' }}>
            {documentText ? (
              <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: 0 }}>
                {documentText}
              </pre>
            ) : (
              <div className="document-viewer-placeholder">
                <p>Загрузка содержимого документа...</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default DocumentViewer
