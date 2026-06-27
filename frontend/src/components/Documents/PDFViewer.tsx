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

/** При наличии bbox из Docling — только оверлей по координатам; text layer без bbox (сканы). */
const PDF_CITATION_HIGHLIGHT = {
  fill: 'rgba(250, 204, 21, 0.42)',
  border: '1px solid rgba(234, 179, 8, 0.6)',
  textMark: 'rgba(250, 204, 21, 0.5)',
} as const

// Set up PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.js`

/** Должен совпадать с тем, как ниже склеиваются строки при полнодокументном поиске цитаты. */
function normPdfPlain(s: string) {
  return s
    .replace(/\u00a0/g, ' ')
    .replace(/\u00ad/g, '')
    .replace(/[\u200b\u200c\u200d\ufeff]/g, '')
    .toLowerCase()
    .replace(/[«»""„''‟]/g, ' ')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Тот же порядок чтения страницы, что и подсветка: сортировка по PDF y,x, затем norm целиком на join(raw). */
function normPageTextFromPdfItems(items: any[]): string {
  type Raw = { str: string; tx: number; ty: number }
  const raw: Raw[] = []
  items.forEach((item) => {
    if (!item?.str?.trim()) return
    const [,,,, tx, ty] = item.transform || [1, 0, 0, 1, 0, 0]
    if (Math.abs(tx) < 1 && Math.abs(ty) < 1) return
    raw.push({ str: String(item.str), tx, ty })
  })
  raw.sort((a, b) => {
    const tyDiff = b.ty - a.ty
    if (Math.abs(tyDiff) > 8) return tyDiff
    return a.tx - b.tx
  })
  return normPdfPlain(raw.map((r) => r.str).join(' '))
}

function buildPdfCitationProbes(rawHighlight: string): string[] {
  const hlNorm = normPdfPlain(rawHighlight)
  if (hlNorm.length < 2) return []
  const hlWords = hlNorm.split(/\s+/).filter(Boolean)
  const probes: string[] = []
  const seen = new Set<string>()
  const add = (s: string) => {
    if (s.length < 2 || seen.has(s)) return
    seen.add(s)
    probes.push(s)
  }
  add(hlNorm)
  add(hlNorm.slice(0, Math.min(hlNorm.length, 200)))
  add(hlNorm.slice(0, 160))
  add(hlNorm.slice(0, 120))
  add(hlNorm.slice(0, 80))
  add(hlNorm.slice(0, 50))
  add(hlWords.slice(0, 12).join(' '))
  add(hlWords.slice(0, 8).join(' '))
  add(hlWords.slice(0, 6).join(' '))
  add(hlWords.slice(0, 4).join(' '))
  add(hlWords.slice(0, 3).join(' '))
  add(hlWords.slice(0, 2).join(' '))
  for (let i = 0; i < hlWords.length - 3; i++) {
    add(hlWords.slice(i, i + 4).join(' '))
  }
  return probes
}

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
  /** When highlightPage / bbox absent, scan pdf.js text on every page until highlightText matches (chat citations). */
  expandHighlightSearchAllPages?: boolean
  /** Доп. строки для поиска в text layer (например quote после text_preview в ассистенте). */
  highlightTextCandidates?: string[]
  /** Сброс подсветки при смене цитаты того же файла (tabular / assistant). */
  highlightFocusKey?: string
  /** Превью цитаты в чате: без поля поиска и без печати. */
  showDocumentSearch?: boolean
  showPrint?: boolean
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
  expandHighlightSearchAllPages = false,
  highlightTextCandidates,
  highlightFocusKey,
  showDocumentSearch = true,
  showPrint = true,
}) => {
  const apiBase = fileApiBase ?? `/api/cases/${caseId}`

  const highlightSearchStrings = useMemo(() => {
    const extra = (highlightTextCandidates ?? []).map((s) => String(s).trim()).filter((s) => s.length >= 2)
    const primary = highlightText?.trim() ? highlightText.trim() : ''
    const out: string[] = []
    const seen = new Set<string>()
    const add = (s: string) => {
      if (s.length < 2 || seen.has(s)) return
      seen.add(s)
      out.push(s)
    }
    add(primary)
    extra.forEach(add)
    return out
  }, [highlightText, highlightTextCandidates])
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
  const pdfDocRef = useRef<{ getPage: (n: number) => Promise<any>; numPages: number } | null>(null)
  /** Avoid stale closures in deferred full-document scan timeouts. */
  const highlightMatchRef = useRef(false)

  useEffect(() => {
    highlightMatchRef.current = false
    setHighlightItemIndices([])
  }, [highlightFocusKey])

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

  useEffect(() => {
    highlightMatchRef.current = highlightItemIndices.length > 0
  }, [highlightItemIndices])

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

  const hasCitationBbox = bboxRegionsToDraw.length > 0
  /** Текстовый поиск только если координат нет (скан); иначе bbox стабильнее и не «сужается» через несколько секунд. */
  const preferTextHighlight = highlightSearchStrings.length > 0 && !hasCitationBbox

  const useBboxHighlight =
    hasCitationBbox &&
    typeof pageW === 'number' &&
    typeof pageH === 'number' &&
    pageW > 0 &&
    pageH > 0 &&
    (highlightPageProp == null || highlightPageProp === pageNumber)

  useEffect(() => {
    if (hasCitationBbox) {
      setHighlightItemIndices([])
      return
    }
    if (highlightSearchStrings.length === 0 || pageTextItems.length === 0) {
      setHighlightItemIndices([])
      return
    }

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

    const MAX_WINDOW = Math.min(rawItems.length, 400)

    /** Не полагаемся на norm целой страницы — только скользящие окна (как в скане по документу). */
    let matchedRaw = ''
    let bestI = -1
    let bestJ = -1

    rawLoop: for (const raw of highlightSearchStrings) {
      const probes = [...buildPdfCitationProbes(raw)].sort((a, b) => b.length - a.length)
      for (const pr of probes) {
        let localBest = Infinity
        let li = -1
        let lj = -1
        for (let i = 0; i < rawItems.length; i++) {
          let acc = ''
          for (let j = i; j < Math.min(rawItems.length, i + MAX_WINDOW); j++) {
            acc = acc ? `${acc} ${rawItems[j].str}` : rawItems[j].str
            const cand = normPdfPlain(acc)
            if (!cand.includes(pr)) continue
            const span = j - i
            if (span < localBest) {
              localBest = span
              li = i
              lj = j
            }
            break
          }
        }
        if (li >= 0) {
          matchedRaw = raw
          bestI = li
          bestJ = lj
          break rawLoop
        }
      }
    }

    if (bestI < 0 || !matchedRaw) {
      setHighlightItemIndices([])
      return
    }

    const hlNorm = normPdfPlain(matchedRaw)

    const indices = rawItems.slice(bestI, bestJ + 1).map((r) => r.origIdx)
    const matchedTys = indices.map((oi) => {
      const [, , , , , ty] = pageTextItems[oi].transform || [1, 0, 0, 1, 0, 0]
      return ty as number
    })
    const minTy = Math.min(...matchedTys)
    const maxTy = Math.max(...matchedTys)
    for (const ri of rawItems) {
      if (indices.includes(ri.origIdx)) continue
      if (ri.ty < minTy - 8 || ri.ty > maxTy + 8) continue
      const normPiece = normPdfPlain(ri.str)
      if (normPiece.length >= 1 && hlNorm.includes(normPiece)) indices.push(ri.origIdx)
    }

    setHighlightItemIndices(indices)
    setTimeout(() => {
      const mark = containerRef.current?.querySelector('[data-pdf-mark]')
      if (mark) mark.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 300)
  }, [hasCitationBbox, highlightSearchStrings, pageTextItems, pageNumber])

  useEffect(() => {
    if (!useBboxHighlight) return
    const t = window.setTimeout(() => {
      const mark = containerRef.current?.querySelector('[data-pdf-mark]')
      if (mark) mark.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 300)
    return () => window.clearTimeout(t)
  }, [useBboxHighlight, pageNumber, bboxRegionsToDraw])

  const onDocumentLoadSuccess = (pdf: { numPages: number; getPage?: (n: number) => Promise<any> }) => {
    const n = pdf?.numPages ?? 0
    setNumPages(n)
    pdfDocRef.current = pdf as typeof pdfDocRef.current
    if (initialPage && initialPage >= 1 && initialPage <= n) {
      setPageNumber(initialPage)
    } else {
      setPageNumber(1)
    }
  }

  // Chat / citations: при отсутствии bbox ищем цитату по всему PDF. Если страница передана, но
  // на ней нет совпадения в text layer (или она ошибочна) — откладываем полный проход.
  useEffect(() => {
    if (!expandHighlightSearchAllPages || highlightSearchStrings.length === 0) return
    const hasBbox =
      (highlightBBoxRegions && highlightBBoxRegions.length > 0) ||
      !!(
        highlightBBox &&
        highlightBBox.x0 != null &&
        highlightBBox.y0 != null &&
        highlightBBox.x1 != null &&
        highlightBBox.y1 != null
      )
    if (hasBbox) return
    const pdf = pdfDocRef.current
    const n = numPages
    if (!pdf?.getPage || !n || n < 1) return

    let cancelled = false

    const runScan = async () => {
      for (const raw of highlightSearchStrings) {
        const probes = buildPdfCitationProbes(raw)
        if (probes.length === 0) continue
        for (let p = 1; p <= n; p++) {
          if (cancelled) return
          try {
            const page = await pdf.getPage(p)
            const textContent = await page.getTextContent()
            const items = (textContent.items as any[]).filter(
              (item) => item && typeof item.str === 'string' && item.str.trim(),
            )
            const joined = normPageTextFromPdfItems(items)
            for (const pr of probes) {
              if (joined.includes(pr)) {
                setPageNumber(p)
                setTimeout(() => {
                  const mark = containerRef.current?.querySelector('[data-pdf-mark]')
                  if (mark) mark.scrollIntoView({ behavior: 'smooth', block: 'center' })
                }, 400)
                return
              }
            }
          } catch {
            continue
          }
        }
      }
    }

    const hasPageHint = highlightPageProp != null && highlightPageProp >= 1

    if (!hasPageHint) {
      void runScan()
      return () => {
        cancelled = true
      }
    }

    if (pageNumber !== highlightPageProp) {
      return () => {
        cancelled = true
      }
    }

    const textLayerKnown = pageTextItems.length > 0
    const delayMs = textLayerKnown ? 450 : 900
    const t = window.setTimeout(() => {
      if (cancelled) return
      if (highlightMatchRef.current) return
      void runScan()
    }, delayMs)

    return () => {
      cancelled = true
      window.clearTimeout(t)
    }
  }, [
    expandHighlightSearchAllPages,
    highlightSearchStrings,
    highlightPageProp,
    highlightBBox,
    highlightBBoxRegions,
    numPages,
    fileId,
    pageNumber,
    pageTextItems,
    highlightItemIndices,
  ])

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
            'X-Access-Token': localStorage.getItem('access_token') || ''
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

        {showDocumentSearch && (
          <>
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
          </>
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
          {showPrint && (
            <IconButton size="small" onClick={handlePrint} aria-label="Печать">
              <PrintIcon />
            </IconButton>
          )}
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
              customTextRenderer={preferTextHighlight ? customTextRenderer : undefined}
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
