import React, { useState, useEffect } from "react"
import PDFViewer from "../Documents/PDFViewer"
import { TextHighlighter } from "./TextHighlighter"
import { Card } from "../UI/Card"
import { Badge } from "../UI/Badge"
import { FileText, AlertCircle, Download, Printer, Info, Search, X } from "lucide-react"
import Spinner from "../UI/Spinner"
import {
  Box,
  Tabs,
  Tab,
  IconButton,
  Button,
  TextField,
  InputAdornment,
  Menu,
  MenuItem,
  Tooltip,
  Stack,
  Typography,
} from "@mui/material"
import { SourceReference } from "@/services/tabularReviewApi"

interface CellData {
  verbatimExtract?: string | null
  sourcePage?: number | null
  sourceSection?: string | null
  columnType?: string
  highlightMode?: 'verbatim' | 'page' | 'none'
  sourceReferences?: SourceReference[]
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fileType, setFileType] = useState<string>(propFileType || "pdf")
  const [currentFileId, setCurrentFileId] = useState<string | undefined>(initialFileId)
  const [currentFileName, setCurrentFileName] = useState<string | undefined>(initialFileName)
  const [activeTab, setActiveTab] = useState(0)
  const [searchQuery, setSearchQuery] = useState("")
  const [showAbout, setShowAbout] = useState(false)
  const [aboutAnchorEl, setAboutAnchorEl] = useState<null | HTMLElement>(null)
  
  // Use documents array if provided, otherwise use single file
  const documentTabs: DocumentTab[] = documents || (initialFileId ? [{
    fileId: initialFileId,
    fileName: initialFileName || "Document",
    fileType: propFileType || "pdf"
  }] : [])

  useEffect(() => {
    const activeDoc = documentTabs[activeTab]
    if (activeDoc?.fileId && caseId) {
      setCurrentFileId(activeDoc.fileId)
      setCurrentFileName(activeDoc.fileName)
      loadDocumentInfo(activeDoc.fileId, activeDoc.fileType || "pdf")
      onDocumentChange?.(activeDoc.fileId)
    }
  }, [activeTab, caseId, documentTabs])

  useEffect(() => {
    if (initialFileId && initialFileId !== currentFileId) {
      const tabIndex = documentTabs.findIndex(doc => doc.fileId === initialFileId)
      if (tabIndex >= 0) {
        setActiveTab(tabIndex)
      }
    }
  }, [initialFileId])

  const loadDocumentInfo = async (fileIdToLoad: string, fileTypeToLoad: string) => {
    try {
      setLoading(true)
      setError(null)
      setFileType(fileTypeToLoad)

      // For non-PDF files, load text content
      if (fileTypeToLoad !== "pdf") {
        const baseUrl = import.meta.env.VITE_API_URL || ""
        const url = baseUrl ? `${baseUrl}/api/cases/${caseId}/files/${fileIdToLoad}/content` : `/api/cases/${caseId}/files/${fileIdToLoad}/content`
        const textResponse = await fetch(
          url,
          {
            headers: {
              Authorization: `Bearer ${localStorage.getItem("access_token")}`,
            },
          }
        )

        if (textResponse.ok) {
          const text = await textResponse.text()
          setDocumentText(text)
        } else {
          throw new Error("Failed to load document content")
        }
      }
    } catch (err: any) {
      setError(err.message || "Ошибка при загрузке документа")
    } finally {
      setLoading(false)
    }
  }

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
  const showHighlight = highlightMode === "verbatim" && cellData?.verbatimExtract
  const activeDoc = documentTabs[activeTab]

  // Highlight source references in text
  const highlightTexts = cellData?.sourceReferences?.map(ref => ref.text) || []
  if (cellData?.verbatimExtract && !highlightTexts.includes(cellData.verbatimExtract)) {
    highlightTexts.push(cellData.verbatimExtract)
  }

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Header with tabs and actions */}
      <Box sx={{ borderBottom: 1, borderColor: "divider", bgcolor: "background.paper" }}>
        {/* Tabs for multiple documents */}
        {documentTabs.length > 1 && (
          <Tabs
            value={activeTab}
            onChange={(_, newValue) => setActiveTab(newValue)}
            variant="scrollable"
            scrollButtons="auto"
            sx={{ borderBottom: 1, borderColor: "divider" }}
          >
            {documentTabs.map((doc, idx) => (
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
      </Box>

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
                  highlightMode === "page" && cellData?.sourcePage
                    ? cellData.sourcePage
                    : highlightMode === "verbatim" && cellData?.sourcePage
                    ? cellData.sourcePage
                    : cellData?.sourceReferences?.[0]?.page || undefined
                }
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
        ) : (
          <Box sx={{ p: 2 }}>
            {showHighlight || highlightTexts.length > 0 ? (
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
            )}
          </Box>
        )}
      </Box>
    </Box>
  )
}

