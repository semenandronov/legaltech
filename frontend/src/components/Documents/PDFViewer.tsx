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
  highlightText?: string // Текст для автоматического поиска и подсветки (для citations)
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
  fileApiBase?: string // Override API base (e.g. for global assistant files)
}

const PDFViewer: React.FC<PDFViewerProps> = ({
  fileId,
  caseId,
  filename: _filename,
  initialPage,
  highlightText,
  onError,
  showTabs = false,
  tabs = [],
  onTabChange,
  showAbout = false,
  metadata,
  fileApiBase,
}) => {
  const apiBase = fileApiBase ?? `/api/cases/${caseId}`
  const [numPages, setNumPages] = useState<number | null>(null)
  const [pageNumber, setPageNumber] = useState(initialPage || 1)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [zoomFactor, setZoomFactor] = useState(1.0)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<number[]>([])
  const [currentSearchIndex, setCurrentSearchIndex] = useState(0)
  const [activeTab, setActiveTab] = useState(0)
  const [showAboutPanel, setShowAboutPanel] = useState(showAbout)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  // customTextRenderer approach: work with pdf.js text items directly
  const [pageTextItems, setPageTextItems] = useState<any[]>([])
  const [highlightItemIndices, setHighlightItemIndices] = useState<number[]>([])

  useEffect(() => {
    loadPDF()
    return () => {
      if (pdfUrl && pdfUrl.startsWith('blob:')) {
        URL.revokeObjectURL(pdfUrl)
      }
    }
  }, [fileId, caseId])

  // Reset text items when page changes
  useEffect(() => {
    setPageTextItems([])
    setHighlightItemIndices([])
  }, [pageNumber, fileId])

  // Called by react-pdf when page text content is ready
  const handleGetTextSuccess = (textContent: any) => {
    // Keep ALL TextItems (with 'str' property) to preserve index alignment with
    // customTextRenderer's itemIndex, which counts all str-items including empty ones
    const items = (textContent.items as any[]).filter(item => 'str' in item)
    setPageTextItems(items)
  }

  // Normalize text: lowercase, strip punctuation/quotes, collapse spaces
  const normText = (s: string) =>
    s.toLowerCase()
      .replace(/[«»""„''‟]/g, ' ')
      .replace(/[^\p{L}\p{N}\s]/gu, ' ')
      .replace(/\s+/g, ' ')
      .trim()

  // Compute which item indices to highlight
  useEffect(() => {
    if (!highlightText || pageTextItems.length === 0) {
      setHighlightItemIndices([])
      return
    }

    const hlNorm = normText(highlightText)

    // Build normalized full text with per-item positions
    // Sort by reading order (y DESC = top-of-page first, then x ASC = left-to-right)
    // PDF items are NOT guaranteed to be in reading order — sorting fixes multi-word matches
    type RawItem = { origIdx: number; str: string; tx: number; ty: number }
    const rawItems: RawItem[] = []
    pageTextItems.forEach((item, origIdx) => {
      if (!item.str.trim()) return // skip empty items (origIdx still tracks for itemIndex alignment)
      const [,,,, tx, ty] = item.transform || [1, 0, 0, 1, 0, 0]
      if (Math.abs(tx) < 1 && Math.abs(ty) < 1) return // skip ghost items at PDF origin
      rawItems.push({ origIdx, str: item.str, tx, ty })
    })
    // Sort: higher ty = higher on page (PDF y=0 is bottom); same line → left to right by tx
    // Use 8pt threshold — font baseline shifts (superscripts, quotes) can differ by a few units
    rawItems.sort((a, b) => {
      const tyDiff = b.ty - a.ty
      if (Math.abs(tyDiff) > 8) return tyDiff
      return a.tx - b.tx
    })

    let pos = 0
    const itemPositions: { origIdx: number; normStart: number; normEnd: number; str: string }[] = []
    rawItems.forEach(({ origIdx, str }) => {
      const normalized = normText(str)
      itemPositions.push({ origIdx, normStart: pos, normEnd: pos + normalized.length, str })
      pos += normalized.length + 1
    })
    const normFullText = itemPositions.map(ip => normText(ip.str)).join(' ')

    const hlWords = hlNorm.split(/\s+/)
    // Sliding window variants: try every 4-word window to find verbatim substrings
    // even when the quote starts with non-verbatim label text (e.g. "[сумма] 495 000,00 р.")
    const windowVariants: string[] = []
    for (let i = 0; i < hlWords.length - 3; i++) {
      windowVariants.push(hlWords.slice(i, i + 4).join(' '))
    }

    const variants = [
      hlNorm,
      hlNorm.substring(0, 100),
      hlNorm.substring(0, 60),
      hlWords.slice(0, 6).join(' '),
      hlWords.slice(0, 4).join(' '),
      hlWords.slice(0, 3).join(' '),
      ...windowVariants,
    ].filter(v => v.length > 5)

    for (const text of variants) {
      const idx = normFullText.indexOf(text)
      if (idx === -1) continue
      const matched = itemPositions.filter(ip => ip.normEnd > idx && ip.normStart < idx + text.length)
      if (matched.length > 0) {
        const indices = matched.map(ip => ip.origIdx)

        // Spatial extension: also highlight hlNorm words on the same visual line(s)
        // This handles cases where item ty differs slightly (e.g. quoted numbers «28»)
        const matchedTys = indices.map(oi => {
          const [,,,, , ty] = (pageTextItems[oi].transform || [1,0,0,1,0,0])
          return ty as number
        })
        const minTy = Math.min(...matchedTys)
        const maxTy = Math.max(...matchedTys)
        for (const ri of rawItems) {
          if (indices.includes(ri.origIdx)) continue
          if (ri.ty < minTy - 8 || ri.ty > maxTy + 8) continue
          const norm = normText(ri.str)
          // Check if item text (single or multi-word) is contained in hlNorm
          // min length 1 to catch abbreviated suffixes like "г." (год), "р." (рублей)
          if (norm.length >= 1 && hlNorm.includes(norm)) indices.push(ri.origIdx)
        }

        setHighlightItemIndices(indices)
        // Scroll to first highlighted element after render
        setTimeout(() => {
          const mark = containerRef.current?.querySelector('[data-pdf-mark]')
          if (mark) mark.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }, 300)
        return
      }
    }
    setHighlightItemIndices([])
  }, [highlightText, pageTextItems])

  // customTextRenderer: wrap matching items in a highlighted mark
  const customTextRenderer = ({ str, itemIndex }: { str: string; itemIndex: number }) => {
    if (!highlightItemIndices.includes(itemIndex)) return str
    const escaped = str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
    return `<mark data-pdf-mark="true" style="background-color:rgba(59,130,246,0.45);border-radius:2px;color:inherit;">${escaped}</mark>`
  }

  const loadPDF = async () => {
    try {
      setLoading(true)
      setError(null)

      // Try to get PDF content from API
      const response = await fetch(
        `${apiBase}/files/${fileId}/content`,
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
    setZoomFactor(prev => Math.min(3, prev + 0.2))
  }

  const handleZoomOut = () => {
    setZoomFactor(prev => Math.max(0.3, prev - 0.2))
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
            {Math.round(zoomFactor * 100)}%
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
        <Box 
          ref={containerRef}
          sx={{ flex: 1, overflow: 'auto', p: 2, display: 'flex', justifyContent: 'center' }}
        >
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
            scale={zoomFactor}
            renderTextLayer={true}
            renderAnnotationLayer={true}
            onGetTextSuccess={handleGetTextSuccess}
            customTextRenderer={customTextRenderer}
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
