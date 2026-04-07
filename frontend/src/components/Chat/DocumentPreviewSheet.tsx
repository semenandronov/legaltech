import { useState, useEffect, useRef } from 'react'
import {
  Drawer,
  Box,
  Typography,
  IconButton,
  Chip,
  Divider,
  Skeleton,
  Stack,
  Tooltip,
} from '@mui/material'
import {
  Description as DescriptionIcon,
  Download as DownloadIcon,
  ContentCopy as CopyIcon,
  Check as CheckIcon,
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
  OpenInNew as MaximizeIcon,
  Close as CloseIcon,
} from '@mui/icons-material'
import { SourceInfo } from '@/services/api'
import PDFViewer from '@/components/Documents/PDFViewer'
import { DocumentHighlighter } from '@/components/Documents/DocumentHighlighter'
import { TextHighlighter } from '@/components/TabularReview/TextHighlighter'


interface DocumentPreviewSheetProps {
  isOpen: boolean
  onClose: () => void
  source: SourceInfo | null
  caseId: string
  allSources?: SourceInfo[]
  onNavigate?: (source: SourceInfo) => void
  /** Override the API base used for file loading. Defaults to /api/cases/{caseId}. */
  filesApiBase?: string
}

const DocumentPreviewSheet = ({
  isOpen,
  onClose,
  source,
  caseId,
  allSources = [],
  onNavigate,
  filesApiBase,
}: DocumentPreviewSheetProps) => {
  // Compute API base: custom override or default case-based path
  const apiBase = filesApiBase ?? `/api/cases/${caseId}`
  const [copied, setCopied] = useState(false)
  const [documentContent, setDocumentContent] = useState<string | null>(null)
  const [documentText, setDocumentText] = useState<string | null>(null) // Текстовый контент для подсветки
  const [documentHtml, setDocumentHtml] = useState<string | null>(null) // HTML контент для DOCX
  const [loading, setLoading] = useState(false)
  const [fileInfo, setFileInfo] = useState<{ id: string; file_type: string; filename: string } | null>(null)
  const [fileUrl, setFileUrl] = useState<string | null>(null)

  const currentIndex = source ? allSources.findIndex(s => s.file === source.file) : -1
  const hasPrev = currentIndex > 0
  const hasNext = currentIndex < allSources.length - 1
  
  // Состояние для найденных позиций цитаты в документе
  const [foundHighlights, setFoundHighlights] = useState<Array<{char_start: number; char_end: number}>>([])
  
  /**
   * НОВАЯ ЛОГИКА ПОДСВЕТКИ (Harvey/Lexis+ style):
   * 
   * 1. ПРИОРИТЕТ: Используем ТОЧНЫЕ координаты char_start/char_end из chunk
   *    - Эти координаты сохранены при индексации и ГАРАНТИРОВАННО точные
   *    - Не нужен поиск по тексту - просто подсвечиваем по координатам
   * 
   * 2. FALLBACK: Если координат нет - ищем по тексту quote
   */
  useEffect(() => {
    // Приоритет 1: Используем ТОЧНЫЕ координаты из chunk (если есть)
    const hasExactCoordinates = 
      source?.char_start !== undefined && 
      source?.char_end !== undefined && 
      source.char_start >= 0 && 
      source.char_end > source.char_start &&
      source.char_end - source.char_start > 10 // Минимум 10 символов

    if (hasExactCoordinates) {
      const chunkStart = source!.char_start!
      const chunkEnd = source!.char_end!
      const chunkLen = chunkEnd - chunkStart

      // If chunk is large AND we have a quote, try to find the quote WITHIN the chunk
      // to get a tighter highlight instead of highlighting the whole chunk.
      if (chunkLen > 150 && source?.quote && documentText && source.quote.length >= 10) {
        const quoteLower = source.quote.trim().toLowerCase().replace(/\.{3}$/, '')
        const chunkText = documentText.toLowerCase().substring(chunkStart, chunkEnd)
        let qIdx = chunkText.indexOf(quoteLower)
        if (qIdx === -1 && quoteLower.length > 60) {
          qIdx = chunkText.indexOf(quoteLower.substring(0, 60))
        }
        if (qIdx !== -1) {
          const ql = qIdx === -1 ? 0 : Math.min(quoteLower.length, 120)
          console.log('[DocumentPreview] ✓ Narrowed chunk highlight via quote at offset', qIdx)
          setFoundHighlights([{ char_start: chunkStart + qIdx, char_end: chunkStart + qIdx + ql }])
          return
        }
      }

      // Chunk is small or no quote match — highlight the chunk, cap at 200 chars
      const cappedEnd = chunkLen > 200 ? chunkStart + 200 : chunkEnd
      console.log('[DocumentPreview] ✓ Using chunk coordinates (len=%d)', chunkLen)
      setFoundHighlights([{ char_start: chunkStart, char_end: cappedEnd }])
      return
    }
    
    // Fallback: Поиск по тексту quote (для старых документов без chunk_id)
    if (!documentText || !source?.quote) {
      setFoundHighlights([])
      return
    }
    
    const quoteToFind = source.quote.trim()
    const textLower = documentText.toLowerCase()
    const quoteLower = quoteToFind.toLowerCase().replace(/\.{3}$/, '') // Убираем "..."
    
    if (quoteToFind.length < 10) {
      setFoundHighlights([])
      return
    }
    
    console.log('[DocumentPreview] Fallback: Searching for quote in document...')
    console.log('[DocumentPreview] Quote length:', quoteToFind.length)
    
    let startIdx = -1
    let matchLength = quoteLower.length
    
    // Стратегия 1: Точное совпадение
    startIdx = textLower.indexOf(quoteLower)
    if (startIdx !== -1) {
      console.log('[DocumentPreview] ✓ Found exact match at:', startIdx)
    }
    
    // Стратегия 2: Первые 100 символов
    if (startIdx === -1 && quoteLower.length > 100) {
      const shortQuote = quoteLower.substring(0, 100)
      startIdx = textLower.indexOf(shortQuote)
      if (startIdx !== -1) {
        matchLength = 100
        console.log('[DocumentPreview] ✓ Found first 100 chars at:', startIdx)
      }
    }
    
    // Стратегия 3: Первые 50 символов
    if (startIdx === -1 && quoteLower.length > 50) {
      const shortQuote = quoteLower.substring(0, 50)
      startIdx = textLower.indexOf(shortQuote)
      if (startIdx !== -1) {
        matchLength = 50
        console.log('[DocumentPreview] ✓ Found first 50 chars at:', startIdx)
      }
    }
    
    if (startIdx !== -1) {
      setFoundHighlights([{
        char_start: startIdx,
        char_end: startIdx + matchLength
      }])
    } else {
      console.log('[DocumentPreview] ✗ Quote not found in document (fallback failed)')
      setFoundHighlights([])
    }
  }, [documentText, source?.quote, source?.char_start, source?.char_end, source?.chunk_id])
  
  // Используем найденные позиции
  const highlights = foundHighlights

  useEffect(() => {
    if (source && isOpen) {
      console.log('[DocumentPreview] Opening source (Harvey/Lexis+ style):', {
        file: source.file,
        page: source.page,
        chunk_id: source.chunk_id,  // Уникальный ID chunk'а
        char_start: source.char_start,  // ТОЧНЫЕ координаты
        char_end: source.char_end,      // ТОЧНЫЕ координаты
        quote_preview: source.quote?.substring(0, 80),
        source_id: source.source_id
      })
      loadDocumentInfo()
    }
  }, [source, isOpen])


  const loadDocumentInfo = async () => {
    if (!source) return

    // External sources (pravo.gov.ru, etc.) — don't try to load from case files
    if (source.url && source.url.startsWith('http')) {
      setDocumentContent(null)
      setFileInfo(null)
      setLoading(false)
      return
    }

    setLoading(true)
    setFileInfo(null)
    setDocumentContent(null)
    setDocumentText(null)
    setDocumentHtml(null)

    try {
      // Get list of files to find file by filename or id
      const filesResponse = await fetch(`${apiBase}/files`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`
        }
      })
      
      if (!filesResponse.ok) {
        setDocumentContent('Ошибка загрузки списка документов')
        return
      }
      
      const filesData = await filesResponse.json()
      
      // Try to find file: first by source_id (if available), then by filename, then by id
      let file = null
      if ((source as any).source_id) {
        file = filesData.documents?.find((f: any) => f.id === (source as any).source_id)
      }
      if (!file && source.file) {
        file = filesData.documents?.find((f: any) => f.filename === source.file || f.id === source.file)
      }
      
      if (file) {
        // Found file - open it completely, just like on Documents page
        setFileInfo({
          id: file.id,
          file_type: file.file_type || 'txt',
          filename: file.filename
        })
        
        // Загружаем контент для подсветки в зависимости от типа файла
        await loadDocumentContentForHighlight(file.id, file.file_type || 'txt', source)
      } else {
        // File not found - show preview text if available
        setDocumentContent(source.text_preview || 'Документ не найден')
      }
    } catch (error) {
      console.error('Error loading document:', error)
      setDocumentContent('Ошибка загрузки документа')
    } finally {
      setLoading(false)
    }
  }
  
  // Загрузка контента документа для подсветки
  const loadDocumentContentForHighlight = async (
    fileId: string, 
    fileType: string, 
    source: SourceInfo
  ) => {
    // Проверяем, есть ли координаты или цитата для подсветки
    // char_start может быть 0 для начала документа - это валидно
    const hasCoordinates = source.char_start !== undefined && source.char_end !== undefined && 
                           source.char_end > source.char_start && source.char_end > 0
    const hasQuote = !!source.quote && source.quote.length > 10
    
    console.log('[DocumentPreview] Loading highlight data:', {
      fileType,
      hasCoordinates,
      hasQuote,
      char_start: source.char_start,
      char_end: source.char_end,
      quote: source.quote?.substring(0, 50)
    })
    
    if (!hasCoordinates && !hasQuote) {
      console.log('[DocumentPreview] No highlight data available')
      return
    }
    
    try {
      const fileTypeLower = fileType.toLowerCase()
      const isTextFile = ['txt', 'html', 'md', 'json', 'xml', 'csv'].includes(fileTypeLower)
      const isDocx = fileTypeLower === 'docx'
      const isPdf = fileTypeLower === 'pdf'
      
      const authHeaders = { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }

      // Для DOCX - загружаем HTML версию
      if (isDocx) {
        try {
          console.log('[DocumentPreview] Loading DOCX as HTML for highlighting')
          const htmlRes = await fetch(`${apiBase}/files/${fileId}/html`, { headers: authHeaders })
          if (htmlRes.ok) {
            const htmlData = await htmlRes.json()
            setDocumentHtml(htmlData.html)
            console.log('[DocumentPreview] DOCX HTML loaded, length:', htmlData.html?.length)
          }
        } catch (error) {
          console.warn('Failed to load HTML content for DOCX highlighting:', error)
        }
        return
      }

      // Для текстовых файлов - загружаем текст
      if (isTextFile) {
        try {
          console.log('[DocumentPreview] Loading text file for highlighting')
          const textRes = await fetch(`${apiBase}/files/${fileId}/content`, { headers: authHeaders })
          if (textRes.ok) {
            const text = await textRes.text()
            setDocumentText(text)
            console.log('[DocumentPreview] Text loaded, length:', text?.length)
          }
        } catch (error) {
          console.warn('Failed to load text content for highlighting:', error)
        }
        return
      }

      // Для PDF - пока только переход на страницу (подсветка требует PDF.js text layer)
      if (isPdf) {
        console.log('[DocumentPreview] PDF file - using page navigation only')
        return
      }

      // Для остальных файлов - пробуем загрузить как текст
      try {
        console.log('[DocumentPreview] Trying to load unknown file type as text')
        const textRes = await fetch(`${apiBase}/files/${fileId}/content`, { headers: authHeaders })
        if (textRes.ok) {
          const text = await textRes.text()
          if (text && text.length > 0 && !text.includes('\x00')) {
            setDocumentText(text)
            console.log('[DocumentPreview] File loaded as text, length:', text?.length)
          }
        }
      } catch (error) {
        console.warn('Failed to load file as text:', error)
      }
    } catch (error) {
      console.warn('Error loading document content for highlighting:', error)
    }
  }

  useEffect(() => {
    // Загружаем файл и создаем blob URL только для файлов без специализированного рендерера.
    // PDF → PDFViewer, DOCX → HTML via getFileHtml. Остальные — blob URL + <object>.
    if (isOpen && fileInfo && fileInfo.file_type !== 'pdf' && fileInfo.file_type !== 'docx' && fileInfo.id && (caseId || filesApiBase)) {
      const loadFile = async () => {
        try {
          const baseUrl = import.meta.env.VITE_API_URL || ''
          const url = `${baseUrl}${apiBase}/files/${fileInfo.id}/content`

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
      
      // Cleanup: revoke blob URL при размонтировании или смене файла
      return () => {
        setFileUrl(prevUrl => {
          if (prevUrl) {
            window.URL.revokeObjectURL(prevUrl)
          }
          return null
        })
      }
    } else {
      // Очищаем blob URL при смене на PDF или отсутствии файла
      setFileUrl(prevUrl => {
        if (prevUrl) {
          window.URL.revokeObjectURL(prevUrl)
        }
        return null
      })
    }
  }, [isOpen, fileInfo?.id, fileInfo?.file_type, caseId])

  const handleCopy = async () => {
    if (documentContent) {
      await navigator.clipboard.writeText(documentContent)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handlePrev = () => {
    if (hasPrev && onNavigate) {
      onNavigate(allSources[currentIndex - 1])
    }
  }

  const handleNext = () => {
    if (hasNext && onNavigate) {
      onNavigate(allSources[currentIndex + 1])
    }
  }


  // Ref for DOCX content container — used to auto-scroll to the highlighted mark
  const docxContainerRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to the first <mark id="citation-highlight"> after DOCX content renders
  useEffect(() => {
    if (!docxContainerRef.current || !documentHtml) return
    const mark = docxContainerRef.current.querySelector('#citation-highlight')
    if (mark) {
      mark.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [documentHtml])

  if (!source) return null

  /**
   * Highlight a quote inside an HTML string using DOM text-node traversal.
   * Regex-based search fails when HTML tags split the matched text (e.g. <strong>text</strong>).
   * This function walks all text nodes, builds the full plain-text string, finds the quote
   * position, then wraps the matching segment(s) with <mark> elements in the real DOM tree.
   */
  const insertMarkInHtml = (html: string, quote: string): string => {
    if (!quote || quote.length < 10) return html
    const searchText = quote.replace(/\.{3}$/, '').trim()
    if (searchText.length < 10) return html
    try {
      const container = window.document.createElement('div')
      container.innerHTML = html

      // Collect all leaf text nodes
      const textNodes: Text[] = []
      const walk = (node: Node): void => {
        if (node.nodeType === Node.TEXT_NODE) {
          textNodes.push(node as Text)
        } else {
          Array.from(node.childNodes).forEach(walk)
        }
      }
      walk(container)

      const nodeTexts = textNodes.map(n => n.textContent || '')
      const fullText = nodeTexts.join('')
      const fullTextLower = fullText.toLowerCase()

      // Try progressively shorter prefixes of the quote until a match is found
      let pos = -1
      let matchLength = 0
      for (const len of [200, 100, 60, 30]) {
        const candidate = searchText.substring(0, len).toLowerCase()
        if (candidate.length < 10) continue
        const idx = fullTextLower.indexOf(candidate)
        if (idx !== -1) {
          pos = idx
          matchLength = candidate.length
          break
        }
      }
      if (pos === -1) return html

      const endPos = pos + matchLength
      let currentPos = 0
      let firstMark = true

      for (let i = 0; i < textNodes.length; i++) {
        const nodeStart = currentPos
        const nodeText = nodeTexts[i]
        const nodeEnd = nodeStart + nodeText.length

        if (nodeEnd > pos && nodeStart < endPos) {
          const hlStart = Math.max(0, pos - nodeStart)
          const hlEnd = Math.min(nodeText.length, endPos - nodeStart)

          if (hlStart < hlEnd) {
            const parent = textNodes[i].parentNode
            if (parent) {
              const before = nodeText.substring(0, hlStart)
              const middle = nodeText.substring(hlStart, hlEnd)
              const after = nodeText.substring(hlEnd)

              const mark = window.document.createElement('mark')
              mark.style.backgroundColor = '#fef08a'
              mark.style.borderRadius = '2px'
              mark.style.padding = '2px 0'
              if (firstMark) {
                mark.id = 'citation-highlight'
                firstMark = false
              }
              mark.textContent = middle

              const frag = window.document.createDocumentFragment()
              if (before) frag.appendChild(window.document.createTextNode(before))
              frag.appendChild(mark)
              if (after) frag.appendChild(window.document.createTextNode(after))
              parent.replaceChild(frag, textNodes[i])
            }
          }
        }
        currentPos = nodeEnd
      }

      return container.innerHTML
    } catch {
      return html
    }
  }

  return (
    <Drawer
      anchor="right"
      open={isOpen}
      onClose={onClose}
      PaperProps={{
        sx: {
          width: { xs: '100%', sm: '500px', lg: '600px' },
        },
      }}
    >
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
        }}
      >
        {/* Header */}
        <Box
          sx={{
            p: 2,
            borderBottom: '1px solid',
            borderColor: 'divider',
            bgcolor: 'action.hover',
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 2, mb: 2 }}>
            <DescriptionIcon color="primary" sx={{ mt: 0.5 }} />
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography
                variant="h6"
                sx={{
                  fontWeight: 600,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {source.file}
              </Typography>
              <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: 'wrap' }}>
                {source.page != null && (
                  <Chip
                    label={`Стр. ${source.page + 1}`}
                    size="small"
                    variant="outlined"
                  />
                )}
                {source.similarity_score !== undefined && (
                  <Chip
                    label={`${Math.round(source.similarity_score * 100)}% релевантность`}
                    size="small"
                    color={source.similarity_score > 0.7 ? 'primary' : 'default'}
                    variant="outlined"
                  />
                )}
              </Stack>
            </Box>
          </Box>
          
          {/* Navigation & Actions */}
          <Divider sx={{ my: 1.5 }} />
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <Stack direction="row" spacing={0.5} alignItems="center">
              <IconButton
                size="small"
                onClick={handlePrev}
                disabled={!hasPrev}
              >
                <ChevronLeftIcon />
              </IconButton>
              <Typography variant="caption" color="text.secondary" sx={{ px: 1 }}>
                {currentIndex + 1} / {allSources.length}
              </Typography>
              <IconButton
                size="small"
                onClick={handleNext}
                disabled={!hasNext}
              >
                <ChevronRightIcon />
              </IconButton>
            </Stack>

            <Stack direction="row" spacing={0.5}>
              <Tooltip title="Копировать">
                <IconButton size="small" onClick={handleCopy}>
                  {copied ? (
                    <CheckIcon color="success" fontSize="small" />
                  ) : (
                    <CopyIcon fontSize="small" />
                  )}
                </IconButton>
              </Tooltip>
              <Tooltip title="Скачать">
                <IconButton
                  size="small"
                  component="a"
                  href={fileInfo ? `${apiBase}/files/${fileInfo.id}/download` : `#`}
                  download
                >
                  <DownloadIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              {!filesApiBase && (
                <Tooltip title="Открыть в полном окне">
                  <IconButton
                    size="small"
                    component="a"
                    href={`/cases/${caseId}/chat?file=${encodeURIComponent(source.file)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <MaximizeIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              )}
              <Tooltip title="Закрыть">
                <IconButton size="small" onClick={onClose}>
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Stack>
          </Box>
        </Box>

        {/* Content */}
        <Box
          sx={{
            flex: 1,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {source?.url && source.url.startsWith('http') ? (
            // External source (pravo.gov.ru) — show link to open in browser
            <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', p: 4, gap: 2 }}>
              <Typography variant="body2" color="text.secondary" textAlign="center">
                Документ опубликован на официальном портале.<br />Откройте его в браузере для просмотра.
              </Typography>
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: '8px 16px',
                  backgroundColor: '#1976d2',
                  color: '#fff',
                  borderRadius: 6,
                  textDecoration: 'none',
                  fontSize: '0.875rem',
                  fontWeight: 500,
                }}
              >
                Открыть на pravo.gov.ru ↗
              </a>
            </Box>
          ) : loading ? (
            <Box sx={{ p: 2 }}>
              <Stack spacing={1}>
                <Skeleton variant="text" width="100%" />
                <Skeleton variant="text" width="75%" />
                <Skeleton variant="text" width="50%" />
              </Stack>
            </Box>
          ) : fileInfo && fileInfo.file_type === 'pdf' ? (
            // PDF viewer - like on Documents page, with highlighting support
            // Используем quote из chunk для поиска в PDF (координаты char_start/char_end не работают для PDF)
            <Box sx={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              <Box sx={{ flex: 1, overflow: 'hidden' }}>
                <PDFViewer
                  fileId={fileInfo.id}
                  caseId={caseId}
                  filename={fileInfo.filename}
                  fileApiBase={filesApiBase}
                  initialPage={source.page != null ? source.page + 1 : 1} // source_page is 0-based; PDFViewer is 1-based
                  highlightText={source.quote?.replace(/\.{3}$/, '').substring(0, 150)} // Убираем "..." и берём первые 150 символов
                  showTabs={false}
                  showAbout={false}
                />
              </Box>
            </Box>
          ) : fileInfo && documentHtml && fileInfo.file_type === 'docx' ? (
            // DOCX - отображаем HTML с подсветкой цитаты через <mark>
            <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
              <Box
                ref={docxContainerRef}
                component="div"
                dangerouslySetInnerHTML={{
                  __html: source.quote ? insertMarkInHtml(documentHtml, source.quote) : documentHtml
                }}
                sx={{ fontSize: '0.875rem', fontFamily: 'inherit' }}
              />
            </Box>
          ) : fileInfo && documentText && ['txt', 'html', 'md', 'json', 'xml', 'csv'].includes(fileInfo.file_type.toLowerCase()) ? (
            // Текстовые документы - отображаем с подсветкой по координатам или по найденной цитате
            <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
              {highlights.length > 0 ? (
                <DocumentHighlighter
                  text={documentText}
                  highlights={highlights}
                  className="whitespace-pre-wrap text-sm"
                />
              ) : source.quote ? (
                // Fallback: подсветка по тексту цитаты через TextHighlighter
                <TextHighlighter
                  text={documentText}
                  highlightText={source.quote}
                  className="whitespace-pre-wrap text-sm font-mono"
                />
              ) : (
                <Box
                  component="pre"
                  sx={{
                    whiteSpace: 'pre-wrap',
                    fontSize: '0.875rem',
                    fontFamily: 'monospace',
                    m: 0,
                  }}
                >
                  {documentText}
                </Box>
              )}
            </Box>
          ) : fileInfo && fileInfo.file_type === 'docx' ? (
            // DOCX HTML still loading or conversion failed — never fall through to raw binary
            <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', p: 3 }}>
              <Typography variant="body2" color="text.secondary" textAlign="center">
                {loading ? 'Загрузка документа…' : 'Не удалось отобразить документ.\nСкачайте файл для просмотра.'}
              </Typography>
            </Box>
          ) : fileInfo && fileUrl ? (
            // For non-PDF files, use object tag instead of iframe to avoid CSP issues
            <Box sx={{ flex: 1, overflow: 'hidden' }}>
              <object
                data={fileUrl}
                type={fileInfo.file_type === 'docx' ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' : 'text/plain'}
                style={{
                  width: '100%',
                  height: '100%',
                  border: 'none',
                  flex: 1
                }}
              >
                <Box sx={{ p: 2, textAlign: 'center' }}>
                  <Typography variant="body2" color="text.secondary">
                    Браузер не поддерживает отображение этого типа файла.
                    <br />
                    <a 
                      href={`${apiBase}/files/${fileInfo.id}/download`}
                      download
                      style={{ color: 'primary.main', textDecoration: 'underline' }}
                    >
                      Скачать файл
                    </a>
                  </Typography>
                </Box>
              </object>
            </Box>
          ) : fileInfo ? (
            // Loading file
            <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Typography variant="body2" color="text.secondary">
                Загрузка документа...
              </Typography>
            </Box>
          ) : (
            <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Typography variant="body2" color="text.secondary">
                Загрузка информации о документе...
              </Typography>
            </Box>
          )}
        </Box>
      </Box>
    </Drawer>
  )
}

export default DocumentPreviewSheet

