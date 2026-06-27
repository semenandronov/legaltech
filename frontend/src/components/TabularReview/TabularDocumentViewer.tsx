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
import {
  CITATION_HIGHLIGHT_MARK_ID,
  highlightQuoteInHtml,
} from "@/utils/citationHighlight"
import type { ChunkLabViewerCellData } from "@/utils/chunkLabViewerCellData"

interface CellData extends Omit<ChunkLabViewerCellData, 'highlightMode' | 'verbatimExtract' | 'sourcePage'> {
  verbatimExtract?: string | null
  sourcePage?: number | null
  cellValue?: string | null
  sourceSection?: string | null
  columnType?: string
  highlightMode?: 'verbatim' | 'page' | 'none'
  sourceReferences?: SourceReference[]
  docId?: string | null
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
  /** Префикс API файлов без `/files`: как у PDFViewer `/api/v2/assistant` или `/api/cases/{id}` */
  fileApiBase?: string
  /** Превью цитаты в чате: компактная панель PDF без поиска и печати. */
  citationPreview?: boolean
  /** Смена цитаты без смены fileId — пересчёт подсветки. */
  highlightRevision?: string
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
  fileApiBase,
  citationPreview = false,
  highlightRevision,
}) => {
  const [documentText, setDocumentText] = useState<string>("")
  const [rawDocumentHtml, setRawDocumentHtml] = useState<string | null>(null)
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
    if (!initialFileId || (!caseId && !fileApiBase)) return

    const activeDoc = documentTabs[activeTab]
    if (!activeDoc?.fileId) return
    
    // Load if fileId changed
    if (activeDoc.fileId !== currentFileId) {
      setCurrentFileId(activeDoc.fileId)
      setCurrentFileName(activeDoc.fileName)
      loadDocumentInfo(activeDoc.fileId, propFileType || activeDoc.fileType || "pdf")
      onDocumentChange?.(activeDoc.fileId)
    }
  }, [initialFileId, caseId, fileApiBase, activeTab])

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
      setRawDocumentHtml(null)
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
            setRawDocumentHtml(htmlResponse.html)
            return
          }
        } catch (htmlErr) {
          console.warn("[TabularDocumentViewer] DOCX→HTML failed, falling back to text:", htmlErr)
        }
      }

      // For other non-PDF files (txt, csv, etc.) — load raw text content
      const filesRoot = fileApiBase ?? `/api/cases/${caseId}`
      const baseUrl = import.meta.env.VITE_API_URL || ""
      const url = baseUrl ? `${baseUrl}${filesRoot}/files/${fileIdToLoad}/content` : `${filesRoot}/files/${fileIdToLoad}/content`
      const textResponse = await fetch(url, {
        headers: {
          'X-Access-Token': localStorage.getItem("access_token") || '',
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

  const highlightQuote = cellData?.verbatimExtract ?? null

  const documentHtml = React.useMemo(() => {
    if (!rawDocumentHtml) return null
    if (!highlightQuote) return rawDocumentHtml
    return highlightQuoteInHtml(rawDocumentHtml, highlightQuote)
  }, [rawDocumentHtml, highlightQuote, highlightRevision])

  // Auto-scroll to highlighted mark in DOCX after render
  useEffect(() => {
    if (!docxContainerRef.current || !documentHtml) return
    const timer = setTimeout(() => {
      const mark = docxContainerRef.current?.querySelector(`#${CITATION_HIGHLIGHT_MARK_ID}`)
      if (mark) {
        mark.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    }, 100)
    return () => clearTimeout(timer)
  }, [documentHtml, highlightRevision])

  const handleDownload = async () => {
    if (!currentFileId) return
    try {
      const filesRoot = fileApiBase ?? `/api/cases/${caseId}`
      const baseUrl = import.meta.env.VITE_API_URL || ""
      const url = baseUrl ? `${baseUrl}${filesRoot}/files/${currentFileId}/download` : `${filesRoot}/files/${currentFileId}/download`
      const response = await fetch(url, {
        headers: {
          'X-Access-Token': localStorage.getItem("access_token") || '',
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

  const pageBasis = cellData?.sourcePageBasis ?? "zero"
  const viewerPdfPageFromSourcePage =
    cellData?.sourcePage == null || Number.isNaN(Number(cellData.sourcePage))
      ? undefined
      : pageBasis === "one"
        ? Math.max(1, Number(cellData.sourcePage))
        : Number(cellData.sourcePage) + 1
  /** sourceReferences унаследованы от табличного backend: basis задаётся sourcePageBasis */
  const viewerPdfPageFromRef =
    cellData?.sourceReferences?.[0]?.page == null ||
    Number.isNaN(Number(cellData.sourceReferences[0].page))
      ? undefined
      : pageBasis === "one"
        ? Math.max(1, Number(cellData.sourceReferences[0].page))
        : Number(cellData.sourceReferences[0].page) + 1

  const pdfInitialAndHighlightPage =
    viewerPdfPageFromSourcePage ?? viewerPdfPageFromRef ?? undefined

  const activeHighlightText = cellData?.verbatimExtract?.trim() || null
  const highlightTexts = activeHighlightText ? [activeHighlightText] : []

  const showHighlight =
    highlightTexts.length > 0 ||
    (highlightMode !== "none" && Boolean(activeHighlightText || cellData?.sourcePage != null))

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
              fileApiBase={fileApiBase}
              initialPage={pdfInitialAndHighlightPage}
              highlightPage={pdfInitialAndHighlightPage}
              highlightFocusKey={highlightRevision}
              highlightText={activeHighlightText || undefined}
              highlightTextCandidates={cellData?.verbatimAlternates ?? undefined}
              highlightBBox={cellData?.highlightBBox}
              highlightBBoxRegions={cellData?.highlightBBoxRegions}
              highlightPageBBox={cellData?.highlightPageBBox}
              expandHighlightSearchAllPages={Boolean(
                activeHighlightText ||
                  cellData?.verbatimAlternates?.some((x) => String(x).trim().length >= 2),
              )}
              showDocumentSearch={!citationPreview}
              showPrint={!citationPreview}
              onError={(err) => {
                setError(err.message || "Ошибка при загрузке PDF")
              }}
            />
            )}
          </Box>
        ) : fileType === "docx" && documentHtml ? (
          <Box sx={{ p: 2 }}>
            <Box
              ref={docxContainerRef}
              dangerouslySetInnerHTML={{ __html: documentHtml }}
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

