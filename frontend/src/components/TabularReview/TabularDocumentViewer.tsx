import React, { useState, useEffect, useRef } from "react"
import PDFViewer from "../Documents/PDFViewer"
import { TextHighlighter } from "./TextHighlighter"
import { Card } from "../UI/Card"
import { FileText, AlertCircle, Download, Printer, Info, Search, X } from "lucide-react"
import Spinner from "../UI/Spinner"
import {
  Box,
  Tabs,
  Tab,
  IconButton,
  TextField,
  InputAdornment,
  Menu,
  MenuItem,
  Tooltip,
  Stack,
  Typography,
} from "@mui/material"
import { SourceReference } from "@/services/tabularReviewApi"
import { getFileHtml } from "@/services/fileHtmlApi"

interface CellData {
  verbatimExtract?: string | null
  cellValue?: string | null
  sourcePage?: number | null
  sourceSection?: string | null
  columnType?: string
  highlightMode?: 'verbatim' | 'page' | 'none'
  sourceReferences?: SourceReference[]
  // Phase 4: Deep link fields
  docId?: string | null
  charStart?: number | null
  charEnd?: number | null
}

interface DocumentTab {
  fileId: string
  fileName: string
  fileType?: string
}

interface TabularDocumentViewerProps {
  fileId?: string
  caseId: string
  fileType?: string
  fileName?: string
  cellData?: CellData | null
  documents?: DocumentTab[] // Multiple documents for tabs
  onClose?: () => void
  onDocumentChange?: (fileId: string) => void
}

export const TabularDocumentViewer: React.FC<TabularDocumentViewerProps> = ({
  fileId: initialFileId,
  caseId,
  fileType: propFileType,
  fileName: initialFileName,
  cellData,
  documents,
  onClose: _onClose,
  onDocumentChange,
}) => {
  const [documentText, setDocumentText] = useState<string>("")
  const [documentHtml, setDocumentHtml] = useState<string | null>(null) // DOCX → HTML
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fileType, setFileType] = useState<string>(propFileType || "pdf")
  const [currentFileId, setCurrentFileId] = useState<string | undefined>(undefined)
  const [currentFileName, setCurrentFileName] = useState<string | undefined>(undefined)
  const [activeTab, setActiveTab] = useState(0)
  const [searchQuery, setSearchQuery] = useState("")
  const [showAbout, setShowAbout] = useState(false)
  const [aboutAnchorEl, setAboutAnchorEl] = useState<null | HTMLElement>(null)
  const docxContainerRef = useRef<HTMLDivElement>(null)
  
  // Use documents array if provided, otherwise use single file
  const documentTabs: DocumentTab[] = React.useMemo(() => {
    return documents || (initialFileId ? [{
      fileId: initialFileId,
      fileName: initialFileName || "Document",
      fileType: propFileType || "pdf"
    }] : [])
  }, [documents, initialFileId, initialFileName, propFileType])

  // Load document when initialFileId or caseId changes
  useEffect(() => {
    if (!initialFileId || !caseId) return
    
    const activeDoc = documentTabs[activeTab]
    if (!activeDoc?.fileId) return
    
    // Load if fileId changed
    if (activeDoc.fileId !== currentFileId) {
      setCurrentFileId(activeDoc.fileId)
      setCurrentFileName(activeDoc.fileName)
      loadDocumentInfo(activeDoc.fileId, propFileType || activeDoc.fileType || "pdf")
      onDocumentChange?.(activeDoc.fileId)
    }
  }, [initialFileId, caseId, activeTab])

  // Update active tab when initialFileId changes
  useEffect(() => {
    if (initialFileId) {
      const tabIndex = documentTabs.findIndex(doc => doc.fileId === initialFileId)
      if (tabIndex >= 0 && tabIndex !== activeTab) {
        setActiveTab(tabIndex)
      }
    }
  }, [initialFileId])

  const loadDocumentInfo = async (fileIdToLoad: string, fileTypeToLoad: string) => {
    try {
      setLoading(true)
      setError(null)
      setDocumentHtml(null)
      setDocumentText("")
      setFileType(fileTypeToLoad || "pdf")

      if (fileTypeToLoad === "pdf") {
        // PDF is rendered by PDFViewer component directly
        return
      }

      // DOCX: convert to HTML server-side for proper rendering
      if (fileTypeToLoad === "docx") {
        try {
          const htmlResponse = await getFileHtml(caseId, fileIdToLoad, false)
          if (htmlResponse.html) {
            setDocumentHtml(htmlResponse.html)
            return
          }
        } catch (htmlErr) {
          console.warn("[TabularDocumentViewer] DOCX→HTML failed, falling back to text:", htmlErr)
        }
      }

      // For other non-PDF files (txt, csv, etc.) — load raw text content
      const baseUrl = import.meta.env.VITE_API_URL || ""
      const url = baseUrl ? `${baseUrl}/api/cases/${caseId}/files/${fileIdToLoad}/content` : `/api/cases/${caseId}/files/${fileIdToLoad}/content`
      const textResponse = await fetch(url, {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("access_token")}`,
        },
      })

      if (textResponse.ok) {
        const text = await textResponse.text()
        setDocumentText(text)
      } else {
        throw new Error("Failed to load document content")
      }
    } catch (err: any) {
      setError(err.message || "Ошибка при загрузке документа")
    } finally {
      setLoading(false)
    }
  }

  /**
   * Insert <mark> highlight into HTML string using DOM text-node traversal.
   * Finds the quote in the concatenated text of all leaf nodes and wraps matching segments.
   */
  const insertMarkInHtml = (html: string, quote: string): string => {
    if (!quote || quote.length < 10) return html
    const searchText = quote.replace(/\.{3}$/, '').trim()
    if (searchText.length < 10) return html
    try {
      const container = window.document.createElement('div')
      container.innerHTML = html

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

      let pos = -1
      let matchLength = 0
      for (const len of [searchText.length, 200, 100, 60, 30]) {
        if (len > searchText.length) continue
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

  // Auto-scroll to highlighted mark in DOCX after render
  useEffect(() => {
    if (!docxContainerRef.current || !documentHtml) return
    // Small delay to let the DOM update
    const timer = setTimeout(() => {
      const mark = docxContainerRef.current?.querySelector('#citation-highlight')
      if (mark) {
        mark.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    }, 100)
    return () => clearTimeout(timer)
  }, [documentHtml])

  const handleDownload = async () => {
    if (!currentFileId) return
    try {
      const baseUrl = import.meta.env.VITE_API_URL || ""
      const url = baseUrl ? `${baseUrl}/api/cases/${caseId}/files/${currentFileId}/download` : `/api/cases/${caseId}/files/${currentFileId}/download`
      const response = await fetch(url, {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("access_token")}`,
        },
      })
      if (response.ok) {
        const blob = await response.blob()
        const downloadUrl = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = downloadUrl
        a.download = currentFileName || "document"
        document.body.appendChild(a)
        a.click()
        window.URL.revokeObjectURL(downloadUrl)
        document.body.removeChild(a)
      }
    } catch (err) {
      console.error("Error downloading file:", err)
    }
  }

  const handlePrint = () => {
    window.print()
  }

  const handleAboutClick = (event: React.MouseEvent<HTMLElement>) => {
    setAboutAnchorEl(event.currentTarget)
    setShowAbout(true)
  }

  const handleAboutClose = () => {
    setAboutAnchorEl(null)
    setShowAbout(false)
  }

  if (!currentFileId && documentTabs.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        <div className="text-center">
          <FileText className="w-12 h-12 mx-auto mb-4 opacity-50" />
          <p>Выберите ячейку для просмотра документа</p>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Spinner size="lg" />
      </div>
    )
  }

  if (error) {
    return (
      <Card className="p-6 m-4">
        <div className="flex items-center gap-2 text-destructive">
          <AlertCircle className="w-5 h-5" />
          <span>{error}</span>
        </div>
      </Card>
    )
  }

  const highlightMode = cellData?.highlightMode || "none"
  const activeDoc = documentTabs[activeTab]

  // Collect all texts to highlight for non-PDF documents
  // Include verbatim extract and all source references
  const highlightTexts: string[] = []
  
  // Add verbatim extract if available (highest priority for highlighting)
  if (cellData?.verbatimExtract) {
    highlightTexts.push(cellData.verbatimExtract)
  }
  
  // Add all source reference texts
  if (cellData?.sourceReferences && cellData.sourceReferences.length > 0) {
    cellData.sourceReferences.forEach(ref => {
      if (ref.text && !highlightTexts.includes(ref.text)) {
        highlightTexts.push(ref.text)
      }
    })
  }
  
  // Determine if we should show highlighting for text documents
  // Show highlighting if we have verbatim extract OR source references with text
  const showHighlight = highlightTexts.length > 0 || (highlightMode !== "none" && (cellData?.verbatimExtract || cellData?.sourceReferences?.length))

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Header with tabs and actions — hidden for PDFs since PDFViewer has its own toolbar */}
      {fileType !== "pdf" && <Box sx={{ borderBottom: 1, borderColor: "divider", bgcolor: "background.paper" }}>
        {/* Tabs for multiple documents */}
        {documentTabs.length > 1 && (
          <Tabs
            value={activeTab}
            onChange={(_, newValue) => setActiveTab(newValue)}
            variant="scrollable"
            scrollButtons="auto"
            sx={{ borderBottom: 1, borderColor: "divider" }}
          >
            {documentTabs.map((doc) => (
              <Tab
                key={doc.fileId}
                label={doc.fileName}
                sx={{ textTransform: "none", minWidth: 120 }}
              />
            ))}
          </Tabs>
        )}

        {/* Toolbar */}
        <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", p: 1, gap: 1 }}>
          {/* Search */}
          <TextField
            size="small"
            placeholder="Search in document..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <Search fontSize="small" />
                </InputAdornment>
              ),
              endAdornment: searchQuery && (
                <InputAdornment position="end">
                  <IconButton size="small" onClick={() => setSearchQuery("")}>
                    <X fontSize="small" />
                  </IconButton>
                </InputAdornment>
              ),
            }}
            sx={{ flex: 1, maxWidth: 400 }}
          />

          {/* Actions */}
          <Stack direction="row" spacing={0.5}>
            <Tooltip title="About">
              <IconButton size="small" onClick={handleAboutClick}>
                <Info fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Download file">
              <IconButton size="small" onClick={handleDownload}>
                <Download fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Print">
              <IconButton size="small" onClick={handlePrint}>
                <Printer fontSize="small" />
              </IconButton>
            </Tooltip>
            {_onClose && (
              <Tooltip title="Close">
                <IconButton size="small" onClick={_onClose}>
                  <X fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
          </Stack>
        </Box>

        {/* About Menu */}
        <Menu
          anchorEl={aboutAnchorEl}
          open={showAbout}
          onClose={handleAboutClose}
        >
          <MenuItem disabled>
            <Box>
              <Typography variant="subtitle2">{activeDoc?.fileName}</Typography>
              <Typography variant="caption" color="text.secondary">
                Type: {activeDoc?.fileType || "pdf"}
              </Typography>
            </Box>
          </MenuItem>
        </Menu>
      </Box>}

      {/* Document content */}
      <Box sx={{ flex: 1, overflow: "auto", position: "relative" }}>
        {fileType === "pdf" ? (
          <Box sx={{ position: "relative", height: "100%" }}>
            {currentFileId && (
            <PDFViewer
                fileId={currentFileId}
              caseId={caseId}
                filename={activeDoc?.fileName || ""}
              initialPage={
                // Backend stores source_page as 0-indexed (PyMuPDF range()), PDFViewer expects 1-indexed
                highlightMode === "page" && cellData?.sourcePage != null
                  ? cellData.sourcePage + 1
                  : highlightMode === "verbatim" && cellData?.sourcePage != null
                  ? cellData.sourcePage + 1
                  : cellData?.sourceReferences?.[0]?.page != null
                  ? cellData.sourceReferences[0].page + 1
                  : undefined
              }
              highlightText={cellData?.verbatimExtract || cellData?.sourceReferences?.[0]?.text || cellData?.cellValue || undefined}
              onError={(err) => {
                setError(err.message || "Ошибка при загрузке PDF")
              }}
            />
            )}
            {/* Source references indicators */}
            {cellData?.sourceReferences && cellData.sourceReferences.length > 0 && (
              <Box
                sx={{
                  position: "absolute",
                  top: 8,
                  right: 8,
                  bgcolor: "primary.main",
                  color: "primary.contrastText",
                  px: 1.5,
                  py: 0.5,
                  borderRadius: 1,
                  fontSize: "0.75rem",
                  zIndex: 10,
                }}
              >
                {cellData.sourceReferences.map((ref, idx) => (
                  <Box key={idx} sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                    {ref.page && `Page ${ref.page}`}
                    {ref.section && ` • ${ref.section}`}
                  </Box>
                ))}
              </Box>
            )}
          </Box>
        ) : fileType === "docx" && documentHtml ? (
          // DOCX rendered as HTML with optional quote highlighting
          <Box sx={{ p: 2 }}>
            <Box
              ref={docxContainerRef}
              dangerouslySetInnerHTML={{
                __html: cellData?.verbatimExtract
                  ? insertMarkInHtml(documentHtml, cellData.verbatimExtract)
                  : documentHtml,
              }}
              sx={{ fontSize: "0.875rem", fontFamily: "inherit", lineHeight: 1.6 }}
            />
          </Box>
        ) : (
          <Box sx={{ p: 2 }}>
            {documentText ? (
              showHighlight || highlightTexts.length > 0 ? (
                <TextHighlighter
                  text={documentText}
                  highlightText={cellData?.verbatimExtract || highlightTexts[0] || undefined}
                  highlightTexts={highlightTexts}
                  searchQuery={searchQuery}
                  className="whitespace-pre-wrap text-sm"
                />
              ) : (
                <Box
                  component="pre"
                  sx={{
                    whiteSpace: "pre-wrap",
                    fontSize: "0.875rem",
                    fontFamily: "monospace",
                    m: 0,
                  }}
                >
                  {documentText}
                </Box>
              )
            ) : fileType === "docx" ? (
              // DOCX loading/failed state — never show raw binary
              <Box sx={{ display: "flex", alignItems: "center", justifyContent: "center", py: 6 }}>
                <Typography variant="body2" color="text.secondary" textAlign="center">
                  {loading ? 'Загрузка документа…' : 'Не удалось отобразить документ. Скачайте файл для просмотра.'}
                </Typography>
              </Box>
            ) : (
              <Box sx={{ display: "flex", alignItems: "center", justifyContent: "center", py: 6 }}>
                <Typography variant="body2" color="text.secondary">
                  Документ загружается…
                </Typography>
              </Box>
            )}
          </Box>
        )}
      </Box>
    </Box>
  )
}

