import React, { useEffect } from 'react'
import { DocumentWithMetadata } from './DocumentsList'
import PDFViewer from './PDFViewer'
import { OpenInNew as OpenInNewIcon } from '@mui/icons-material'
import { Typography, Button } from '@mui/material'
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
  // #region agent log
  const handleOpenOriginal = async () => {
    if (!document?.id || !caseId) return
    fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DocumentViewer.tsx:handleOpenOriginal',message:'handleOpenOriginal called',data:{fileId:document.id,fileType:document.file_type},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'A'})}).catch(()=>{});
    // #endregion
    try {
      const baseUrl = import.meta.env.VITE_API_URL || ''
      const url = baseUrl 
        ? `${baseUrl}/api/cases/${caseId}/files/${document.id}/download`
        : `/api/cases/${caseId}/files/${document.id}/download`
      
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DocumentViewer.tsx:handleOpenOriginal',message:'Fetching file',data:{url},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'B'})}).catch(()=>{});
      // #endregion
      
      const response = await fetch(url, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`
        }
      })
      
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DocumentViewer.tsx:handleOpenOriginal',message:'Response received',data:{ok:response.ok,status:response.status},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'C'})}).catch(()=>{});
      // #endregion
      
      if (response.ok) {
        const blob = await response.blob()
        const blobUrl = window.URL.createObjectURL(blob)
        
        // #region agent log
        fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DocumentViewer.tsx:handleOpenOriginal',message:'Blob created, creating link',data:{blobSize:blob.size,blobType:blob.type},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'D'})}).catch(()=>{});
        // #endregion
        
        // Создаем временную ссылку и кликаем по ней
        const link = document.createElement('a')
        link.href = blobUrl
        link.target = '_blank'
        link.rel = 'noopener noreferrer'
        link.style.display = 'none'
        document.body.appendChild(link)
        
        // #region agent log
        fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DocumentViewer.tsx:handleOpenOriginal',message:'Clicking link',data:{},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'E'})}).catch(()=>{});
        // #endregion
        
        link.click()
        document.body.removeChild(link)
        
        // Отложенная очистка blob URL
        setTimeout(() => {
          window.URL.revokeObjectURL(blobUrl)
        }, 1000)
      }
    } catch (error) {
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DocumentViewer.tsx:handleOpenOriginal',message:'Error occurred',data:{error:String(error)},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'F'})}).catch(()=>{});
      // #endregion
      console.error('Ошибка при открытии документа:', error)
    }
  }

  useEffect(() => {
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DocumentViewer.tsx:useEffect',message:'useEffect triggered',data:{hasDocument:!!document,fileType:document?.file_type,fileId:document?.id,caseId},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'G'})}).catch(()=>{});
    // #endregion
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

