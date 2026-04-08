import React, { useState, useEffect } from 'react'
import { DocumentWithMetadata } from './DocumentsList'
import PDFViewer from './PDFViewer'
import DOCXViewer from './DOCXViewer'
import './Documents.css'

// File types that browsers cannot display inline — must be downloaded
const DOWNLOAD_ONLY_TYPES = new Set(['xlsx', 'xls', 'csv', 'pptx', 'ppt', 'ods', 'odt'])

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
  const [fileUrl, setFileUrl] = useState<string | null>(null)

  useEffect(() => {
    // Загружаем файл и создаем blob URL только для файлов, которые не PDF и не DOCX
    // (DOCX загружается в DOCXViewer, PDF загружается в PDFViewer)
    const isDocx = document?.file_type === 'docx' || document?.filename.toLowerCase().endsWith('.docx')
    const ext = (document?.file_type || document?.filename?.split('.').pop() || '').toLowerCase()
    const isDownloadOnly = DOWNLOAD_ONLY_TYPES.has(ext)

    if (document?.id && document.file_type !== 'pdf' && !isDocx && !isDownloadOnly && caseId) {
      const loadFile = async () => {
        try {
          const baseUrl = import.meta.env.VITE_API_URL || ''
          // Используем /content endpoint для просмотра (inline), а не /download (attachment)
          const url = baseUrl 
            ? `${baseUrl}/api/cases/${caseId}/files/${document.id}/content`
            : `/api/cases/${caseId}/files/${document.id}/content`
          
          const response = await fetch(url, {
            headers: {
              'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
          })
          
          if (response.ok) {
            const blob = await response.blob()
            const blobUrl = window.URL.createObjectURL(blob)
            setFileUrl(blobUrl)
          }
        } catch (error) {
          console.error('Ошибка при загрузке файла:', error)
        }
      }
      
      loadFile()
      
      // Cleanup: revoke blob URL при размонтировании или смене документа
      return () => {
        setFileUrl(prevUrl => {
          if (prevUrl) {
            window.URL.revokeObjectURL(prevUrl)
          }
          return null
        })
      }
    } else {
      // Очищаем blob URL при смене на PDF/DOCX или отсутствии документа
      setFileUrl(prevUrl => {
        if (prevUrl) {
          window.URL.revokeObjectURL(prevUrl)
        }
        return null
      })
    }
  }, [document?.id, caseId, document?.file_type, document?.filename])

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

  // Определяем, является ли файл DOCX
  const isDocx = document.file_type === 'docx' || document.filename.toLowerCase().endsWith('.docx')
  const ext = (document.file_type || document.filename.split('.').pop() || '').toLowerCase()
  const isDownloadOnly = DOWNLOAD_ONLY_TYPES.has(ext)

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
        ) : isDocx ? (
          <DOCXViewer
            fileId={document.id}
            caseId={caseId}
            filename={document.filename}
            onError={(error) => {
              console.error('DOCX viewer error:', error)
            }}
            showAbout={false}
          />
        ) : isDownloadOnly ? (
          <div style={{ padding: '40px 24px', textAlign: 'center', color: 'var(--color-text-secondary)' }}>
            <div style={{ fontSize: 40, marginBottom: 16 }}>📊</div>
            <p style={{ marginBottom: 8, fontWeight: 500 }}>Предпросмотр недоступен</p>
            <p style={{ fontSize: 13, marginBottom: 24, color: 'var(--color-text-muted)' }}>
              Файлы формата {ext.toUpperCase()} нельзя открыть в браузере.<br />
              Скачайте файл, чтобы открыть его в Excel или другом приложении.
            </p>
            <a
              href={`${import.meta.env.VITE_API_URL || ''}/api/cases/${caseId}/files/${document.id}/content`}
              download={document.filename}
              style={{
                display: 'inline-block',
                padding: '8px 20px',
                borderRadius: 8,
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-primary)',
                fontSize: 13,
                textDecoration: 'none',
              }}
            >
              Скачать {document.filename}
            </a>
          </div>
        ) : fileUrl ? (
          <iframe
            src={fileUrl}
            style={{ width: '100%', height: '100%', border: 'none', flex: 1 }}
            title={document.filename}
          />
        ) : (
          <div style={{ padding: '20px', textAlign: 'center' }}>
            Загрузка документа...
          </div>
        )}
      </div>
    </div>
  )
}

export default DocumentViewer

