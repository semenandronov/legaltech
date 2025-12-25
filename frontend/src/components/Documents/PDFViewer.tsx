import React, { useState, useEffect } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/esm/Page/AnnotationLayer.css'
import 'react-pdf/dist/esm/Page/TextLayer.css'
import './Documents.css'

// Set up PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.js`

interface PDFViewerProps {
  fileId: string
  caseId: string
  filename: string
  initialPage?: number
  onError?: (error: Error) => void
}

const PDFViewer: React.FC<PDFViewerProps> = ({
  fileId,
  caseId,
  filename: _filename,
  initialPage,
  onError
}) => {
  const [numPages, setNumPages] = useState<number | null>(null)
  const [pageNumber, setPageNumber] = useState(initialPage || 1)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [scale, setScale] = useState(1.2)

  useEffect(() => {
    loadPDF()
    return () => {
      // Cleanup: revoke object URL if it exists
      if (pdfUrl && pdfUrl.startsWith('blob:')) {
        URL.revokeObjectURL(pdfUrl)
      }
    }
  }, [fileId, caseId])

  const loadPDF = async () => {
    try {
      setLoading(true)
      setError(null)

      // Try to get PDF content from API
      const response = await fetch(
        `/api/cases/${caseId}/files/${fileId}/content`,
        {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`
          }
        }
      )

      if (!response.ok) {
        throw new Error(`Failed to load document: ${response.statusText}`)
      }

      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      setPdfUrl(url)
    } catch (err: any) {
      console.error('Error loading PDF:', err)
      setError(err.message || 'Ошибка при загрузке документа')
      if (onError) {
        onError(err)
      }
    } finally {
      setLoading(false)
    }
  }

  const onDocumentLoadSuccess = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages)
    // Set to initialPage if provided and valid, otherwise start at page 1
    if (initialPage && initialPage >= 1 && initialPage <= numPages) {
      setPageNumber(initialPage)
    } else {
      setPageNumber(1)
    }
  }

  const onDocumentLoadError = (error: Error) => {
    console.error('PDF load error:', error)
    setError('Ошибка при загрузке PDF документа')
    if (onError) {
      onError(error)
    }
  }

  const goToPrevPage = () => {
    setPageNumber(prev => Math.max(1, prev - 1))
  }

  const goToNextPage = () => {
    setPageNumber(prev => (numPages ? Math.min(numPages, prev + 1) : prev))
  }

  const handleZoomIn = () => {
    setScale(prev => Math.min(3, prev + 0.2))
  }

  const handleZoomOut = () => {
    setScale(prev => Math.max(0.5, prev - 0.2))
  }

  const handleZoomReset = () => {
    setScale(1.2)
  }

  if (loading) {
    return (
      <div className="pdf-viewer-loading">
        <div className="pdf-viewer-loading-spinner"></div>
        <p>Загрузка документа...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="pdf-viewer-error">
        <div className="pdf-viewer-error-icon">⚠️</div>
        <h3>Ошибка загрузки документа</h3>
        <p>{error}</p>
        <p className="pdf-viewer-error-hint">
          Документ может быть недоступен или иметь неподдерживаемый формат.
        </p>
      </div>
    )
  }

  if (!pdfUrl) {
    return (
      <div className="pdf-viewer-error">
        <div className="pdf-viewer-error-icon">📄</div>
        <h3>Документ не найден</h3>
        <p>Не удалось загрузить содержимое документа.</p>
      </div>
    )
  }

  return (
    <div className="pdf-viewer-container">
      <div className="pdf-viewer-controls">
        <div className="pdf-viewer-controls-left">
          <button
            className="pdf-viewer-control-btn"
            onClick={goToPrevPage}
            disabled={pageNumber <= 1}
            aria-label="Предыдущая страница"
          >
            ←
          </button>
          <span className="pdf-viewer-page-info">
            Страница {pageNumber} из {numPages || '?'}
          </span>
          <button
            className="pdf-viewer-control-btn"
            onClick={goToNextPage}
            disabled={!numPages || pageNumber >= numPages}
            aria-label="Следующая страница"
          >
            →
          </button>
        </div>
        <div className="pdf-viewer-controls-right">
          <button
            className="pdf-viewer-control-btn"
            onClick={handleZoomOut}
            aria-label="Уменьшить"
          >
            −
          </button>
          <span className="pdf-viewer-zoom-info">
            {Math.round(scale * 100)}%
          </span>
          <button
            className="pdf-viewer-control-btn"
            onClick={handleZoomReset}
            aria-label="Сбросить масштаб"
          >
            ↻
          </button>
          <button
            className="pdf-viewer-control-btn"
            onClick={handleZoomIn}
            aria-label="Увеличить"
          >
            +
          </button>
        </div>
      </div>

      <div className="pdf-viewer-content">
        <Document
          file={pdfUrl}
          onLoadSuccess={onDocumentLoadSuccess}
          onLoadError={onDocumentLoadError}
          loading={
            <div className="pdf-viewer-loading">
              <div className="pdf-viewer-loading-spinner"></div>
              <p>Загрузка PDF...</p>
            </div>
          }
        >
          <Page
            pageNumber={pageNumber}
            scale={scale}
            renderTextLayer={true}
            renderAnnotationLayer={true}
          />
        </Document>
      </div>
    </div>
  )
}

export default PDFViewer
