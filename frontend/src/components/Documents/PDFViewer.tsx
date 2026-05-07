import React, { useState, useEffect, useRef, useMemo } from 'react'
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

/** Сначала подсветка текста в text layer; если фрагмент не найден — оверлей по bbox (как в chunk-lab при наличии координат). */
const PDF_CITATION_HIGHLIGHT = {
  fill: 'rgba(250, 204, 21, 0.42)',
  border: '1px solid rgba(234, 179, 8, 0.6)',
  textMark: 'rgba(250, 204, 21, 0.5)',
} as const

// Set up PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.js`

type PdfBBoxCompat = { x0?: number; y0?: number; x1?: number; y1?: number }

interface PDFViewerProps {
  fileId: string
  caseId: string
  filename: string
  initialPage?: number
  highlightText?: string
  highlightPage?: number
  highlightBBox?: PdfBBoxCompat
  highlightBBoxRegions?: PdfBBoxCompat[]
  highlightPageBBox?: { width?: number; height?: number }
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
  fileApiBase?: string
}

const PDFViewer: React.FC<PDFViewerProps> = ({
  fileId,
  caseId,
  filename: _filename,
  initialPage,
  highlightText,
  highlightPage: highlightPageProp,
  highlightBBox,
  highlightBBoxRegions,
  highlightPageBBox,
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
  const [pageTextItems, setPageTextItems] = useState<any[]>([])
  const [highlightItemIndices, setHighlightItemIndices] = useState<number[]>([])
  const [derivedPageBBox, setDerivedPageBBox] = useState<{ width: number; height: number } | null>(null)

  useEffect(() => {
    loadPDF()
    return () => {
      if (pdfUrl && pdfUrl.startsWith('blob:')) {
        URL.revokeObjectURL(pdfUrl)
      }
    }
  }, [fileId, caseId, apiBase])

  useEffect(() => {
    if (!initialPage || !numPages) return
    if (initialPage >= 1 && initialPage <= numPages) {
      setPageNumber(initialPage)
    }
  }, [initialPage, numPages])

  useEffect(() => {
    setPageTextItems([])
    setHighlightItemIndices([])
  }, [pageNumber, fileId])

  const handlePageLoadSuccess = (page: any) => {
    try {
      const viewport = page?.getViewport?.({ scale: 1 })
      const width = viewport?.width
      const height = viewport?.height
      if (typeof width === 'number' && typeof height === 'number' && width > 0 && height > 0) {
        setDerivedPageBBox({ width, height })
      }
    } catch {
      // ignore
    }
  }

  const handleGetTextSuccess = (textContent: any) => {
    const items = (textContent.items as any[]).filter(item => 'str' in item)
    setPageTextItems(items)
  }

  const normText = (s: string) =>
    s.toLowerCase()
      .replace(/[«»""„''‟]/g, ' ')
      .replace(/[^\p{L}\p{N}\s]/gu, ' ')
      .replace(/\s+/g, ' ')
      .trim()

  const bboxRegionsToDraw = useMemo((): PdfBBoxCompat[] => {
    if (highlightBBoxRegions && highlightBBoxRegions.length > 0) {
      return highlightBBoxRegions.filter(
        (r) =>
          r.x0 != null &&
          r.y0 != null &&
          r.x1 != null &&
          r.y1 != null &&
          r.x1 > r.x0 &&
          r.y1 > r.y0,
      )
    }
    if (
      highlightBBox &&
      highlightBBox.x0 != null &&
      highlightBBox.y0 != null &&
      highlightBBox.x1 != null &&
      highlightBBox.y1 != null &&
      highlightBBox.x1 > highlightBBox.x0 &&
      highlightBBox.y1 > highlightBBox.y0
    ) {
      return [highlightBBox]
    }
    return []
  }, [highlightBBoxRegions, highlightBBox])

  const effectivePageBBox = highlightPageBBox ?? derivedPageBBox ?? null
  const pageW = effectivePageBBox?.width
  const pageH = effectivePageBBox?.height

  const preferTextHighlight = (highlightText?.trim().length ?? 0) >= 2
  const textLayerReady = pageTextItems.length > 0
  const textMatchFound = highlightItemIndices.length > 0
  /** Не показывать bbox, пока ждём text layer (если хотим искать по тексту). */
  const waitingTextLayer = preferTextHighlight && !textLayerReady

  const useBboxHighlight =
    !waitingTextLayer &&
    bboxRegionsToDraw.length > 0 &&
    typeof pageW === 'number' &&
    typeof pageH === 'number' &&
    pageW > 0 &&
    pageH > 0 &&
    (highlightPageProp == null || highlightPageProp === pageNumber) &&
    (!preferTextHighlight || !textMatchFound)

  useEffect(() => {
    if (!highlightText || pageTextItems.length === 0) {
      setHighlightItemIndices([])
      return
    }

    const hlNorm = normText(highlightText)

    type RawItem = { origIdx: number; str: string; tx: number; ty: number }
    const rawItems: RawItem[] = []
    pageTextItems.forEach((item, origIdx) => {
      if (!item.str.trim()) return
      const [,,,, tx, ty] = item.transform || [1, 0, 0, 1, 0, 0]
      if (Math.abs(tx) < 1 && Math.abs(ty) < 1) return
      rawItems.push({ origIdx, str: item.str, tx, ty })
    })
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
    const windowVariants: string[] = []
    for (let i = 0; i < hlWords.length - 3; i++) {
      windowVariants.push(hlWords.slice(i, i + 4).join(' '))
    }

    const variants = [
      hlNorm,
      hlNorm.substring(0, 200),
      hlNorm.substring(0, 100),
      hlNorm.substring(0, 60),
      hlWords.slice(0, 10).join(' '),
      hlWords.slice(0, 8).join(' '),
      hlWords.slice(0, 6).join(' '),
      hlWords.slice(0, 4).join(' '),
      hlWords.slice(0, 3).join(' '),
      hlWords.slice(0, 2).join(' '),
      ...windowVariants,
    ].filter((v) => v.length >= 3)

    for (const text of variants) {
      const idx = normFullText.indexOf(text)
      if (idx === -1) continue
      const matched = itemPositions.filter(ip => ip.normEnd > idx && ip.normStart < idx + text.length)
      if (matched.length > 0) {
        const indices = matched.map(ip => ip.origIdx)

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
          if (norm.length >= 1 && hlNorm.includes(norm)) indices.push(ri.origIdx)
        }

        setHighlightItemIndices(indices)
        setTimeout(() => {
          const mark = containerRef.current?.querySelector('[data-pdf-mark]')
          if (mark) mark.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }, 300)
        return
      }
    }
    setHighlightItemIndices([])
  }, [highlightText, pageTextItems, pageNumber])

  useEffect(() => {
    if (!useBboxHighlight) return
    const t = window.setTimeout(() => {
      const mark = containerRef.current?.querySelector('[data-pdf-mark]')
      if (mark) mark.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 300)
    return () => window.clearTimeout(t)
  }, [useBboxHighlight, pageNumber, bboxRegionsToDraw])

  const customTextRenderer = ({ str, itemIndex }: { str: string; itemIndex: number }) => {
    if (!highlightItemIndices.includes(itemIndex)) return str
    const escaped = str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
    return `<mark data-pdf-mark="true" style="background-color:${PDF_CITATION_HIGHLIGHT.textMark};border-radius:2px;color:inherit;">${escaped}</mark>`
  }

  const loadPDF = async () => {
    try {
      setLoading(true)
      setError(null)

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
    const results: number[] = []
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

      <Box sx={{ flex: 1, overflow: 'auto', position: 'relative', display: 'flex' }}>
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
          <Box sx={{ position: 'relative', display: 'inline-block' }}>
            <Page
              pageNumber={pageNumber}
              scale={zoomFactor}
              renderTextLayer={true}
              renderAnnotationLayer={true}
              onLoadSuccess={handlePageLoadSuccess}
              onGetTextSuccess={handleGetTextSuccess}
              customTextRenderer={useBboxHighlight ? undefined : customTextRenderer}
            />
            {useBboxHighlight &&
              bboxRegionsToDraw.map((r, i) => {
                const x0 = r.x0 ?? 0
                const y0 = r.y0 ?? 0
                const x1 = r.x1 ?? 0
                const y1 = r.y1 ?? 0
                const leftPct = (x0 / (pageW as number)) * 100
                const topPct = (((pageH as number) - y1) / (pageH as number)) * 100
                const wPct = ((x1 - x0) / (pageW as number)) * 100
                const hPct = ((y1 - y0) / (pageH as number)) * 100
                return (
                  <Box
                    key={`bbox-${i}`}
                    data-pdf-mark="true"
                    sx={{
                      position: 'absolute',
                      left: `${leftPct}%`,
                      top: `${topPct}%`,
                      width: `${wPct}%`,
                      height: `${hPct}%`,
                      bgcolor: PDF_CITATION_HIGHLIGHT.fill,
                      border: PDF_CITATION_HIGHLIGHT.border,
                      borderRadius: '2px',
                      pointerEvents: 'none',
                      boxSizing: 'border-box',
                    }}
                  />
                )
              })}
          </Box>
        </Document>
        </Box>

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
