import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
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
import {
  filePreviewFromCitation,
  shouldOpenOriginalByCitationId,
} from '@/lib/caseCitationViewer'
import { buildChunkLabViewerCellData } from '@/utils/chunkLabViewerCellData'
import { TabularDocumentViewer } from '@/components/TabularReview/TabularDocumentViewer'
import { DocumentHighlighter } from '@/components/Documents/DocumentHighlighter'
import { TextHighlighter } from '@/components/TabularReview/TextHighlighter'

const FILE_LIST_TTL_MS = 5 * 60 * 1000
type CachedFileList = { ts: number; documents: any[] }
const fileListCache = new Map<string, CachedFileList>()
const textContentCache = new Map<string, string>()
const htmlContentCache = new Map<string, string>()
const binaryContentCache = new Map<string, Blob>()

const authHeaders = () => ({
  'X-Access-Token': localStorage.getItem('access_token') || ''
})

const extToType = (name?: string): string => {
  const file = (name || '').toLowerCase()
  if (file.endsWith('.pdf')) return 'pdf'
  if (file.endsWith('.docx')) return 'docx'
  if (file.endsWith('.txt')) return 'txt'
  if (file.endsWith('.html')) return 'html'
  if (file.endsWith('.md')) return 'md'
  if (file.endsWith('.json')) return 'json'
  if (file.endsWith('.xml')) return 'xml'
  if (file.endsWith('.csv')) return 'csv'
  return 'txt'
}

const normalizeCitationPageForViewer = (page?: number | null): number | undefined => {
  if (page == null || Number.isNaN(page)) return undefined
  // Contract v1: citation page is 1-based (same as PDF viewer).
  // Keep a tiny legacy fallback: if backend ever sends 0-based, convert 0 → 1.
  return page <= 0 ? 1 : page
}

const getFileListCached = async (apiBase: string, force = false): Promise<any[]> => {
  const cached = fileListCache.get(apiBase)
  const fresh = cached && (Date.now() - cached.ts) < FILE_LIST_TTL_MS
  if (!force && fresh) {
    return cached.documents
  }
  const filesResponse = await fetch(`${apiBase}/files`, {
    headers: authHeaders()
  })
  if (!filesResponse.ok) {
    throw new Error('Ошибка загрузки списка документов')
  }
  const filesData = await filesResponse.json()
  const docs = filesData.documents || []
  fileListCache.set(apiBase, { ts: Date.now(), documents: docs })
  return docs
}

const prefetchSourceContent = async (apiBase: string, fileId: string, fileType: string): Promise<void> => {
  const cacheKey = `${apiBase}:${fileId}`
  const fileTypeLower = fileType.toLowerCase()
  const isTextFile = ['txt', 'html', 'md', 'json', 'xml', 'csv'].includes(fileTypeLower)
  const isDocx = fileTypeLower === 'docx'

  if (isDocx) {
    if (htmlContentCache.has(cacheKey)) return
    const htmlRes = await fetch(`${apiBase}/files/${fileId}/html`, { headers: authHeaders() })
    if (htmlRes.ok) {
      const htmlData = await htmlRes.json()
      htmlContentCache.set(cacheKey, htmlData.html || '')
    }
    return
  }

  if (isTextFile) {
    if (textContentCache.has(cacheKey)) return
    // Use extracted original_text for reliable citation offsets/highlights
    const textRes = await fetch(`${apiBase}/files/${fileId}/text`, { headers: authHeaders() })
    if (textRes.ok) {
      textContentCache.set(cacheKey, await textRes.text())
    }
    return
  }

  if (!binaryContentCache.has(cacheKey)) {
    const response = await fetch(`${apiBase}/files/${fileId}/content`, { headers: authHeaders() })
    if (response.ok) {
      binaryContentCache.set(cacheKey, await response.blob())
    }
  }
}

export const prefetchGlobalCitationSource = async (source: SourceInfo): Promise<void> => {
  if (source.source_type === 'court_practice') {
    const chunkId = source.chunk_id || source.source_id
    if (!chunkId) return
    const cacheKey = `court-practice:${chunkId}`
    if (textContentCache.has(cacheKey)) return
    try {
      const res = await fetch(
        `/api/v2/court-practice-preview?chunk_id=${encodeURIComponent(chunkId)}`,
        { headers: authHeaders() },
      )
      if (res.ok) {
        const data = (await res.json()) as { content?: string }
        textContentCache.set(cacheKey, data.content || '')
      }
    } catch {
      /* best effort */
    }
    return
  }
  const apiBase = source.source_type === 'legal_corpus'
    ? '/api/v2/legal-corpus-preview'
    : '/api/v2/assistant'
  const sourceId = (source as any).source_id as string | undefined
  const filename = source.file || source.title || ''
  if (!sourceId) return
  try {
    // Warm file list cache for instant id -> metadata resolution.
    await getFileListCached(apiBase)
  } catch {
    // best effort
  }
  try {
    await prefetchSourceContent(apiBase, sourceId, extToType(filename))
  } catch {
    // best effort
  }
}


interface DocumentPreviewSheetProps {
  isOpen: boolean
  onClose: () => void
  source: SourceInfo | null
  caseId: string
  allSources?: SourceInfo[]
  onNavigate?: (source: SourceInfo) => void
  /** Override the API base used for file loading. Defaults to /api/cases/{caseId}. */
  filesApiBase?: string
  /**
   * @deprecated Case/assistant citations open by source_id automatically.
   * Kept for backward compatibility with GlobalAssistantPage.
   */
  instantOpen?: boolean
}

const DocumentPreviewSheet = ({
  isOpen,
  onClose,
  source,
  caseId,
  allSources = [],
  onNavigate,
  filesApiBase,
  instantOpen: _instantOpen = false,
}: DocumentPreviewSheetProps) => {
  // Compute API base: custom override or default case-based path
  const apiBase = filesApiBase ?? `/api/cases/${caseId}`
  const [copied, setCopied] = useState(false)
  const [documentContent, setDocumentContent] = useState<string | null>(null)
  const [documentText, setDocumentText] = useState<string | null>(null) // Текстовый контент для подсветки
  const [documentHtml, setDocumentHtml] = useState<string | null>(null) // HTML контент для DOCX
  const [loading, setLoading] = useState(false)
  const [fileInfo, setFileInfo] = useState<{ id: string; file_type: string; filename: string; legacy_fallback?: boolean } | null>(null)
  const [fileUrl, setFileUrl] = useState<string | null>(null)
  const delayedHighlightTimerRef = useRef<number | null>(null)

  const currentIndex = source
    ? allSources.findIndex((s) => {
        // Строгое сопоставление: никаких fallback по page/filename.
        // Иначе клики могут "прыгать" на другой смысловой блок того же документа.
        const sid = (s as any).source_id as string | undefined
        if (!source.source_id || !sid || source.source_id !== sid) return false

        const srcChunk = source.chunk_id
        const sChunk = (s as any).chunk_id as string | undefined
        if (srcChunk && sChunk) return srcChunk === sChunk

        const srcStart = source.char_start
        const srcEnd = source.char_end
        const sStart = (s as any).char_start as number | undefined
        const sEnd = (s as any).char_end as number | undefined
        if (
          typeof srcStart === 'number' &&
          typeof srcEnd === 'number' &&
          typeof sStart === 'number' &&
          typeof sEnd === 'number'
        ) {
          return srcStart === sStart && srcEnd === sEnd
        }

        return false
      })
    : -1
  const hasPrev = currentIndex > 0
  const hasNext = currentIndex < allSources.length - 1
  
  // Состояние для найденных позиций цитаты в документе
  const [foundHighlights, setFoundHighlights] = useState<Array<{char_start: number; char_end: number}>>([])
  const chunkLabCitationCellData = useMemo(() => {
    if (!source) return null
    return buildChunkLabViewerCellData({
      quote_anchor: source.quote_anchor,
      quote: source.quote,
      text_preview: source.text_preview,
      page: source.page ?? null,
      bbox: source.bbox,
      bbox_regions: source.bbox_regions,
      page_bbox: source.page_bbox,
    })
  }, [source])

  const anchorText = chunkLabCitationCellData?.verbatimExtract
    ? String(chunkLabCitationCellData.verbatimExtract)
    : ''

  const startHighlightLoad = (fileId: string, fileType: string, src: SourceInfo, delayMs = 0) => {
    if (delayedHighlightTimerRef.current !== null) {
      window.clearTimeout(delayedHighlightTimerRef.current)
      delayedHighlightTimerRef.current = null
    }
    if (delayMs > 0) {
      delayedHighlightTimerRef.current = window.setTimeout(() => {
        delayedHighlightTimerRef.current = null
        void loadDocumentContentForHighlight(fileId, fileType, src)
      }, delayMs)
      return
    }
    void loadDocumentContentForHighlight(fileId, fileType, src)
  }
  
  /**
   * Подсветка: приоритет char_start/char_end в чанке, иначе поиск quote в documentText.
   * PDF: тот же TabularDocumentViewer + cellData, что ChunkLabPage (verbatim, sourcePageBasis one, bbox).
   */
  useEffect(() => {
    // Раньше требовали span > 10 символов — короткие чанки (например, номер статьи)
    // никогда не подсвечивались, хотя страница и координаты верны.
    const hasExactCoordinates =
      source?.char_start !== undefined &&
      source?.char_end !== undefined &&
      source.char_start >= 0 &&
      source.char_end > source.char_start

    if (hasExactCoordinates) {
      const chunkStart = source!.char_start!
      const chunkEnd = source!.char_end!
      const chunkLen = chunkEnd - chunkStart

      if (chunkLen > 150 && anchorText && documentText && anchorText.trim().length >= 10) {
        const quoteLower = anchorText.trim().toLowerCase().replace(/\.{3}$/, '')
        const chunkText = documentText.toLowerCase().substring(chunkStart, chunkEnd)
        let qIdx = chunkText.indexOf(quoteLower)
        if (qIdx === -1 && quoteLower.length > 60) {
          qIdx = chunkText.indexOf(quoteLower.substring(0, 60))
        }
        if (qIdx !== -1) {
          const ql = qIdx === -1 ? 0 : Math.min(quoteLower.length, 120)
          setFoundHighlights([{ char_start: chunkStart + qIdx, char_end: chunkStart + qIdx + ql }])
          return
        }
      }

      const cappedEnd = chunkLen > 200 ? chunkStart + 200 : chunkEnd
      setFoundHighlights([{ char_start: chunkStart, char_end: cappedEnd }])
      return
    }

    if (!documentText || !anchorText) {
      setFoundHighlights([])
      return
    }

    const quoteToFind = anchorText.trim()
    const textLower = documentText.toLowerCase()
    const quoteLower = quoteToFind.toLowerCase().replace(/\.{3}$/, '')

    if (quoteToFind.length < 10) {
      setFoundHighlights([])
      return
    }

    let startIdx = -1
    let matchLength = quoteLower.length

    startIdx = textLower.indexOf(quoteLower)
    if (startIdx === -1 && quoteLower.length > 100) {
      const shortQuote = quoteLower.substring(0, 100)
      startIdx = textLower.indexOf(shortQuote)
      if (startIdx !== -1) matchLength = 100
    }
    if (startIdx === -1 && quoteLower.length > 50) {
      const shortQuote = quoteLower.substring(0, 50)
      startIdx = textLower.indexOf(shortQuote)
      if (startIdx !== -1) matchLength = 50
    }

    if (startIdx !== -1) {
      setFoundHighlights([{ char_start: startIdx, char_end: startIdx + matchLength }])
    } else {
      setFoundHighlights([])
    }
  }, [documentText, anchorText, source?.char_start, source?.char_end, source?.chunk_id])
  
  // Используем найденные позиции
  const highlights = foundHighlights

  useEffect(() => {
    if (source && isOpen) {
      if (delayedHighlightTimerRef.current !== null) {
        window.clearTimeout(delayedHighlightTimerRef.current)
        delayedHighlightTimerRef.current = null
      }
      console.log('[DocumentPreview] Opening source (Harvey/Lexis+ style):', {
        file: source.file,
        page: source.page,
        chunk_id: source.chunk_id,  // Уникальный ID chunk'а
        char_start: source.char_start,  // ТОЧНЫЕ координаты
        char_end: source.char_end,      // ТОЧНЫЕ координаты
        quote_preview: anchorText.substring(0, 80),
        source_id: source.source_id
      })
      loadDocumentInfo()
    }
    return () => {
      if (delayedHighlightTimerRef.current !== null) {
        window.clearTimeout(delayedHighlightTimerRef.current)
        delayedHighlightTimerRef.current = null
      }
    }
  }, [source, isOpen])

  const enrichCitationFileFromCatalog = useCallback(
    async (
      base: string,
      src: SourceInfo,
      target: { id: string; file_type: string; filename: string },
    ) => {
      try {
        const documents = await getFileListCached(base)
        const row = documents.find((f: { id: string }) => f.id === target.id)
        if (!row) return
        const resolvedType = row.file_type || extToType(row.filename) || target.file_type
        setFileInfo({
          id: row.id,
          file_type: resolvedType,
          filename: row.filename,
          legacy_fallback: Boolean(row.legacy_fallback),
        })
        if (resolvedType !== 'pdf' && resolvedType !== target.file_type) {
          startHighlightLoad(row.id, resolvedType, src)
        }
      } catch {
        /* catalog is best-effort; viewer uses citation source_id + /content */
      }
    },
    [],
  )

  const loadDocumentInfo = async () => {
    if (!source) return

    if (source.source_type === 'court_practice') {
      const chunkId = source.chunk_id || source.source_id
      if (!chunkId) {
        setDocumentContent(source.text_preview || 'Фрагмент не найден')
        setLoading(false)
        return
      }
      setLoading(true)
      setFileInfo(null)
      setDocumentContent(null)
      setDocumentText(null)
      setDocumentHtml(null)
      try {
        const cacheKey = `court-practice:${chunkId}`
        const cached = textContentCache.get(cacheKey)
        let content = cached
        if (content === undefined) {
          const res = await fetch(
            `/api/v2/court-practice-preview?chunk_id=${encodeURIComponent(chunkId)}`,
            { headers: authHeaders() },
          )
          if (!res.ok) throw new Error('preview failed')
          const data = (await res.json()) as { content?: string; metadata?: Record<string, unknown> }
          content = data.content || ''
          textContentCache.set(cacheKey, content)
        }
        setDocumentText(content)
        setFileInfo({
          id: chunkId,
          file_type: 'txt',
          filename: source.file || source.title || 'Судебный акт',
        })
      } catch {
        setDocumentContent(source.text_preview || source.quote || 'Не удалось загрузить фрагмент')
      } finally {
        setLoading(false)
      }
      return
    }

    // External sources (pravo.gov.ru, etc.) — don't try to load from case files
    if (source.url && source.url.startsWith('http')) {
      setDocumentContent(null)
      setFileInfo(null)
      setLoading(false)
      return
    }

    const citationTarget = shouldOpenOriginalByCitationId(source, apiBase)
      ? filePreviewFromCitation(source, extToType)
      : null

    setDocumentContent(null)
    setDocumentText(null)
    setDocumentHtml(null)

    if (citationTarget) {
      setFileInfo(citationTarget)
      setLoading(false)
      if (citationTarget.file_type !== 'pdf') {
        startHighlightLoad(citationTarget.id, citationTarget.file_type, source)
      }
      void enrichCitationFileFromCatalog(apiBase, source, citationTarget)
      return
    }

    setLoading(true)
    setFileInfo(null)

    try {
      const documents = await getFileListCached(apiBase)
      let file = null
      if (source.file) {
        file = documents.find(
          (f: any) => f.filename === source.file || f.id === source.file,
        )
      }

      if (file) {
        const resolvedType = file.file_type || extToType(file.filename)
        setFileInfo({
          id: file.id,
          file_type: resolvedType,
          filename: file.filename,
          legacy_fallback: Boolean(file.legacy_fallback),
        })
        if (resolvedType !== 'pdf') {
          startHighlightLoad(file.id, resolvedType, source)
        }
      } else {
        setDocumentContent(
          source.text_preview ||
            'Документ не найден. У цитаты должен быть id файла в деле — обновите ответ ассистента.',
        )
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
    const hasQuote = !!anchorText && anchorText.length > 10
    
    console.log('[DocumentPreview] Loading highlight data:', {
      fileType,
      hasCoordinates,
      hasQuote,
      char_start: source.char_start,
      char_end: source.char_end,
      quote: anchorText.substring(0, 50)
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
      
      const auth = authHeaders()
      const cacheKey = `${apiBase}:${fileId}`

      // Для DOCX - загружаем HTML версию
      if (isDocx) {
        const cachedHtml = htmlContentCache.get(cacheKey)
        if (cachedHtml !== undefined) {
          setDocumentHtml(cachedHtml)
          return
        }
        try {
          console.log('[DocumentPreview] Loading DOCX as HTML for highlighting')
          const htmlRes = await fetch(`${apiBase}/files/${fileId}/html`, { headers: auth })
          if (htmlRes.ok) {
            const htmlData = await htmlRes.json()
            setDocumentHtml(htmlData.html)
            htmlContentCache.set(cacheKey, htmlData.html || '')
            console.log('[DocumentPreview] DOCX HTML loaded, length:', htmlData.html?.length)
          }
        } catch (error) {
          console.warn('Failed to load HTML content for DOCX highlighting:', error)
        }
        return
      }

      // Для текстовых файлов - загружаем текст
      if (isTextFile) {
        const cachedText = textContentCache.get(cacheKey)
        if (cachedText !== undefined) {
          setDocumentText(cachedText)
          return
        }
        try {
          console.log('[DocumentPreview] Loading text file for highlighting')
          const textRes = await fetch(`${apiBase}/files/${fileId}/text`, { headers: auth })
          if (textRes.ok) {
            const text = await textRes.text()
            setDocumentText(text)
            textContentCache.set(cacheKey, text)
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
        const textRes = await fetch(`${apiBase}/files/${fileId}/text`, { headers: auth })
        if (textRes.ok) {
          const text = await textRes.text()
          if (text && text.length > 0 && !text.includes('\x00')) {
            setDocumentText(text)
            textContentCache.set(cacheKey, text)
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
    // PDF → TabularDocumentViewer (как chunk-lab), DOCX → HTML via getFileHtml. Остальные — blob URL + <object>.
    if (isOpen && fileInfo && fileInfo.file_type !== 'pdf' && fileInfo.file_type !== 'docx' && fileInfo.id && (caseId || filesApiBase)) {
      const loadFile = async () => {
        try {
          const cacheKey = `${apiBase}:${fileInfo.id}`
          const cachedBlob = binaryContentCache.get(cacheKey)
          if (cachedBlob) {
            const cachedBlobUrl = window.URL.createObjectURL(cachedBlob)
            setFileUrl(cachedBlobUrl)
            return
          }

          const response = await fetch(`${apiBase}/files/${fileInfo.id}/content`, {
            headers: authHeaders()
          })
          
          if (response.ok) {
            const blob = await response.blob()
            binaryContentCache.set(cacheKey, blob)
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

  if (!isOpen) return null

  const displayFileName = source?.file || source?.title || 'Документ'
  const navTotal = allSources.length > 0 ? allSources.length : 1
  const navIndex = currentIndex >= 0 ? currentIndex + 1 : 1

  return (
    <Drawer
      anchor="right"
      // Important: temporary Drawer uses Modal that can intercept clicks outside the panel
      // even when backdrop is hidden. Persistent drawer allows interacting with the chat
      // while keeping the preview open.
      variant="persistent"
      open={isOpen}
      onClose={onClose}
      // Важно: Drawer по умолчанию модальный и рисует backdrop поверх всего экрана.
      // Из-за этого после открытия документа клики по другим [N] "не проходят".
      // Делаем панель немодальной, чтобы можно было продолжать кликать по ссылкам в чате.
      ModalProps={{
        hideBackdrop: true,
        disableEnforceFocus: true,
        disableAutoFocus: true,
        disableRestoreFocus: true,
        keepMounted: true,
      }}
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
        {/* Header — sticky, крестик всегда виден */}
        <Box
          sx={{
            position: 'sticky',
            top: 0,
            zIndex: 10,
            flexShrink: 0,
            borderBottom: '1px solid',
            borderColor: 'divider',
            bgcolor: 'background.paper',
          }}
        >
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              px: 2,
              pt: 1.5,
              pb: 1,
            }}
          >
            <DescriptionIcon color="primary" sx={{ flexShrink: 0 }} />
            <Typography
              variant="subtitle1"
              sx={{
                flex: 1,
                minWidth: 0,
                fontWeight: 600,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {displayFileName}
            </Typography>
            <Tooltip title="Закрыть">
              <IconButton
                size="small"
                onClick={onClose}
                aria-label="Закрыть документ"
                sx={{ flexShrink: 0, ml: 0.5 }}
              >
                <CloseIcon />
              </IconButton>
            </Tooltip>
          </Box>

          {source && (
            <>
              <Box sx={{ px: 2, pb: 1 }}>
                <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
                  {source.page != null && (
                    <Chip
                      label={`Стр. ${normalizeCitationPageForViewer(source.page) ?? 1}`}
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

              <Divider />

              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  px: 2,
                  py: 1,
                  bgcolor: 'action.hover',
                }}
              >
                {allSources.length > 1 ? (
                  <Stack direction="row" spacing={0.5} alignItems="center">
                    <IconButton
                      size="small"
                      onClick={handlePrev}
                      disabled={!hasPrev}
                      aria-label="Предыдущий источник"
                    >
                      <ChevronLeftIcon />
                    </IconButton>
                    <Typography variant="caption" color="text.secondary" sx={{ px: 1 }}>
                      {navIndex} / {navTotal}
                    </Typography>
                    <IconButton
                      size="small"
                      onClick={handleNext}
                      disabled={!hasNext}
                      aria-label="Следующий источник"
                    >
                      <ChevronRightIcon />
                    </IconButton>
                  </Stack>
                ) : (
                  <Box />
                )}

                <Stack direction="row" spacing={0.5}>
                  <Tooltip title="Копировать">
                    <IconButton size="small" onClick={handleCopy} aria-label="Копировать">
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
                      aria-label="Скачать"
                    >
                      <DownloadIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  {!filesApiBase && (
                    <Tooltip title="Открыть в полном окне">
                      <IconButton
                        size="small"
                        component="a"
                        href={`/cases/${caseId}/chat?file=${encodeURIComponent(displayFileName)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label="Открыть в полном окне"
                      >
                        <MaximizeIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  )}
                </Stack>
              </Box>
            </>
          )}
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
          {fileInfo?.legacy_fallback && (
            <Box sx={{ px: 2, py: 1, bgcolor: 'warning.light', borderBottom: '1px solid', borderColor: 'warning.main' }}>
              <Typography variant="caption" color="warning.dark">
                Оригинал на диске не сохранён — показан только извлечённый текст. Перезагрузите документ в дело,
                чтобы открывать PDF/DOCX по цитатам.
              </Typography>
            </Box>
          )}
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
          ) : fileInfo && fileInfo.file_type === 'pdf' ? (
            // Как ChunkLabPage: TabularDocumentViewer + тот же cellData (verbatim, page basis one, bbox).
            <Box sx={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              <Box sx={{ flex: 1, overflow: 'hidden', minHeight: 0 }}>
                <TabularDocumentViewer
                  key={`preview-pdf:${fileInfo.id}:${source?.source_id ?? ''}:${source?.chunk_id ?? ''}:${String(source?.page ?? '')}`}
                  fileId={fileInfo.id}
                  caseId={caseId}
                  fileType="pdf"
                  fileName={fileInfo.filename}
                  cellData={chunkLabCitationCellData ?? undefined}
                  fileApiBase={filesApiBase}
                  citationPreview
                />
              </Box>
            </Box>
          ) : loading ? (
            <Box sx={{ p: 2 }}>
              <Stack spacing={1}>
                <Skeleton variant="text" width="100%" />
                <Skeleton variant="text" width="75%" />
                <Skeleton variant="text" width="50%" />
              </Stack>
            </Box>
          ) : fileInfo && documentHtml && fileInfo.file_type === 'docx' ? (
            // DOCX - отображаем HTML с подсветкой цитаты через <mark>
            <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
              <Box
                ref={docxContainerRef}
                component="div"
                dangerouslySetInnerHTML={{
                  __html: anchorText ? insertMarkInHtml(documentHtml, anchorText) : documentHtml
                }}
                sx={{ fontSize: '0.875rem', fontFamily: 'inherit' }}
              />
            </Box>
          ) : fileInfo && documentText && (source?.source_type === 'court_practice' || ['txt', 'html', 'md', 'json', 'xml', 'csv'].includes(fileInfo.file_type.toLowerCase())) ? (
            // Текстовые документы - отображаем с подсветкой по координатам или по найденной цитате
            <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
              {highlights.length > 0 ? (
                <DocumentHighlighter
                  text={documentText}
                  highlights={highlights}
                  className="whitespace-pre-wrap text-sm"
                />
              ) : anchorText ? (
                // Fallback: подсветка по тексту цитаты через TextHighlighter
                <TextHighlighter
                  text={documentText}
                  highlightText={anchorText}
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

