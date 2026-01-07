import React, { useState, useEffect, useRef } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/esm/Page/AnnotationLayer.css'
import 'react-pdf/dist/esm/Page/TextLayer.css'
import {
  Box,
  IconButton,
  TextField,
  InputAdornment,
  Stack,
  Typography,
  Tabs,
  Tab,
  Paper,
  Divider,
  Chip,
  Skeleton,
} from '@mui/material'
import {
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
  ZoomIn as ZoomInIcon,
  ZoomOut as ZoomOutIcon,
  Search as SearchIcon,
  Close as CloseIcon,
  Download as DownloadIcon,
  Print as PrintIcon,
  Info as InfoIcon,
} from '@mui/icons-material'
import './Documents.css'

// Set up PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.js`

interface PDFViewerProps {
  fileId: string
  caseId: string
  filename: string
  initialPage?: number
  onError?: (error: Error) => void
  showTabs?: boolean
  tabs?: Array<{ id: string; label: string; fileId: string }>
  onTabChange?: (fileId: string) => void
  showAbout?: boolean
  metadata?: {
    file_type?: string
    created_at?: string
    file_size?: number
    [key: string]: any
  }
}

const PDFViewer: React.FC<PDFViewerProps> = ({
  fileId,
  caseId,
  filename: _filename,
  initialPage,
  onError,
  showTabs = false,
  tabs = [],
  onTabChange,
  showAbout = false,
  metadata,
}) => {
  const [numPages, setNumPages] = useState<number | null>(null)
  const [pageNumber, setPageNumber] = useState(initialPage || 1)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [scale, setScale] = useState(1.2)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<number[]>([])
  const [currentSearchIndex, setCurrentSearchIndex] = useState(0)
  const [activeTab, setActiveTab] = useState(0)
  const [showAboutPanel, setShowAboutPanel] = useState(showAbout)
  const searchInputRef = useRef<HTMLInputElement>(null)

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


  const handleSearch = (query: string) => {
    setSearchQuery(query)
    if (!query.trim()) {
      setSearchResults([])
      setCurrentSearchIndex(0)
      return
    }
    
    // Basic search - in a real implementation, this would use PDF.js text layer
    // For now, we'll just highlight the query in the text layer
    // This is a simplified version - full implementation would require PDF.js text extraction
    const results: number[] = []
    // TODO: Implement proper PDF text search using PDF.js
    setSearchResults(results)
    setCurrentSearchIndex(0)
  }

  const handleNextSearch = () => {
    if (searchResults.length > 0) {
      const nextIndex = (currentSearchIndex + 1) % searchResults.length
      setCurrentSearchIndex(nextIndex)
      setPageNumber(searchResults[nextIndex])
    }
  }

  const handlePrevSearch = () => {
    if (searchResults.length > 0) {
      const prevIndex = currentSearchIndex === 0 ? searchResults.length - 1 : currentSearchIndex - 1
      setCurrentSearchIndex(prevIndex)
      setPageNumber(searchResults[prevIndex])
    }
  }

  const handleDownload = () => {
    if (pdfUrl) {
      const link = document.createElement('a')
      link.href = pdfUrl
      link.download = _filename || 'document.pdf'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    }
  }

  const handlePrint = () => {
    if (pdfUrl) {
      window.open(pdfUrl, '_blank')
    }
  }

  const handleTabChange = (_event: React.SyntheticEvent, newValue: number) => {
    setActiveTab(newValue)
    if (tabs[newValue] && onTabChange) {
      onTabChange(tabs[newValue].fileId)
    }
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', p: 3 }}>
        <Skeleton variant="rectangular" width="100%" height={400} sx={{ mb: 2 }} />
        <Typography variant="body2" color="text.secondary">Загрузка документа...</Typography>
      </Box>
    )
  }

  if (error) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', p: 3 }}>
        <Typography variant="h6" color="error" sx={{ mb: 1 }}>Ошибка загрузки документа</Typography>
        <Typography variant="body2" color="text.secondary">{error}</Typography>
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
          Документ может быть недоступен или иметь неподдерживаемый формат.
        </Typography>
      </Box>
    )
  }

  if (!pdfUrl) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', p: 3 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>Документ не найден</Typography>
        <Typography variant="body2" color="text.secondary">Не удалось загрузить содержимое документа.</Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Tabs for multiple documents */}
      {showTabs && tabs.length > 0 && (
        <Tabs
          value={activeTab}
          onChange={handleTabChange}
          variant="scrollable"
          scrollButtons="auto"
          sx={{ borderBottom: 1, borderColor: 'divider' }}
        >
          {tabs.map((tab) => (
            <Tab key={tab.id} label={tab.label} />
          ))}
        </Tabs>
      )}

      {/* Toolbar */}
      <Paper
        elevation={0}
        sx={{
          p: 1,
          borderBottom: 1,
          borderColor: 'divider',
          display: 'flex',
          alignItems: 'center',
          gap: 1,
        }}
      >
        {/* Navigation */}
        <Stack direction="row" spacing={0.5} alignItems="center">
          <IconButton
            size="small"
            onClick={goToPrevPage}
            disabled={pageNumber <= 1}
            aria-label="Предыдущая страница"
          >
            <ChevronLeftIcon />
          </IconButton>
          <Typography variant="body2" sx={{ minWidth: 120, textAlign: 'center' }}>
            Страница {pageNumber} из {numPages || '?'}
          </Typography>
          <IconButton
            size="small"
            onClick={goToNextPage}
            disabled={!numPages || pageNumber >= numPages}
            aria-label="Следующая страница"
          >
            <ChevronRightIcon />
          </IconButton>
        </Stack>

        <Divider orientation="vertical" flexItem sx={{ mx: 1 }} />

        {/* Search */}
        <TextField
          inputRef={searchInputRef}
          size="small"
          placeholder="Поиск в документе..."
          value={searchQuery}
          onChange={(e) => handleSearch(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
            endAdornment: searchQuery ? (
              <InputAdornment position="end">
                <IconButton
                  size="small"
                  onClick={() => {
                    setSearchQuery('')
                    setSearchResults([])
                  }}
                >
                  <CloseIcon fontSize="small" />
                </IconButton>
              </InputAdornment>
            ) : null,
          }}
          sx={{ width: 250 }}
        />
        {searchQuery && searchResults.length > 0 && (
          <Stack direction="row" spacing={0.5} alignItems="center">
            <Typography variant="caption" color="text.secondary">
              {currentSearchIndex + 1} / {searchResults.length}
            </Typography>
            <IconButton size="small" onClick={handlePrevSearch}>
              <ChevronLeftIcon fontSize="small" />
            </IconButton>
            <IconButton size="small" onClick={handleNextSearch}>
              <ChevronRightIcon fontSize="small" />
            </IconButton>
          </Stack>
        )}

        <Box sx={{ flexGrow: 1 }} />

        {/* Zoom controls */}
        <Stack direction="row" spacing={0.5} alignItems="center">
          <IconButton size="small" onClick={handleZoomOut} aria-label="Уменьшить">
            <ZoomOutIcon />
          </IconButton>
          <Typography variant="body2" sx={{ minWidth: 50, textAlign: 'center' }}>
            {Math.round(scale * 100)}%
          </Typography>
          <IconButton size="small" onClick={handleZoomIn} aria-label="Увеличить">
            <ZoomInIcon />
          </IconButton>
        </Stack>

        <Divider orientation="vertical" flexItem sx={{ mx: 1 }} />

        {/* Actions */}
        <Stack direction="row" spacing={0.5}>
          {showAbout && (
            <IconButton
              size="small"
              onClick={() => setShowAboutPanel(!showAboutPanel)}
              color={showAboutPanel ? 'primary' : 'default'}
            >
              <InfoIcon />
            </IconButton>
          )}
          <IconButton size="small" onClick={handleDownload} aria-label="Скачать">
            <DownloadIcon />
          </IconButton>
          <IconButton size="small" onClick={handlePrint} aria-label="Печать">
            <PrintIcon />
          </IconButton>
        </Stack>
      </Paper>

      {/* Content area */}
      <Box sx={{ flex: 1, overflow: 'auto', position: 'relative', display: 'flex' }}>
        {/* PDF Viewer */}
        <Box sx={{ flex: 1, overflow: 'auto', p: 2, display: 'flex', justifyContent: 'center' }}>
        <Document
          file={pdfUrl}
          onLoadSuccess={onDocumentLoadSuccess}
          onLoadError={onDocumentLoadError}
          loading={
              <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', p: 3 }}>
                <Skeleton variant="rectangular" width={600} height={800} />
                <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                  Загрузка PDF...
                </Typography>
              </Box>
          }
        >
          <Page
            pageNumber={pageNumber}
            scale={scale}
            renderTextLayer={true}
            renderAnnotationLayer={true}
          />
        </Document>
        </Box>

        {/* About/Metadata Panel */}
        {showAboutPanel && metadata && (
          <Paper
            elevation={0}
            sx={{
              width: 300,
              borderLeft: 1,
              borderColor: 'divider',
              p: 2,
              overflow: 'auto',
            }}
          >
            <Stack spacing={2}>
              <Typography variant="h6">О документе</Typography>
              <Divider />
              {metadata.file_type && (
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Тип файла
                  </Typography>
                  <Chip label={metadata.file_type.toUpperCase()} size="small" sx={{ mt: 0.5 }} />
                </Box>
              )}
              {metadata.created_at && (
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Дата создания
                  </Typography>
                  <Typography variant="body2">
                    {new Date(metadata.created_at).toLocaleDateString('ru-RU')}
                  </Typography>
                </Box>
              )}
              {metadata.file_size && (
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Размер файла
                  </Typography>
                  <Typography variant="body2">
                    {(metadata.file_size / 1024).toFixed(2)} KB
                  </Typography>
                </Box>
              )}
              {_filename && (
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Имя файла
                  </Typography>
                  <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>
                    {_filename}
                  </Typography>
                </Box>
              )}
            </Stack>
          </Paper>
        )}
      </Box>
    </Box>
  )
}

export default PDFViewer
