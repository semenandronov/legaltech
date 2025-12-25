import React, { useState, useEffect } from "react"
import PDFViewer from "../Documents/PDFViewer"
import { TextHighlighter } from "./TextHighlighter"
import { Card } from "../UI/Card"
import { Badge } from "../UI/Badge"
import { FileText, AlertCircle } from "lucide-react"
import Spinner from "../UI/Spinner"

interface CellData {
  verbatimExtract?: string | null
  sourcePage?: number | null
  sourceSection?: string | null
  columnType?: string
  highlightMode?: 'verbatim' | 'page' | 'none'
}

interface TabularDocumentViewerProps {
  fileId: string
  caseId: string
  fileType?: string
  cellData?: CellData | null
  onClose?: () => void
}

export const TabularDocumentViewer: React.FC<TabularDocumentViewerProps> = ({
  fileId,
  caseId,
  fileType: propFileType,
  cellData,
  onClose,
}) => {
  const [documentText, setDocumentText] = useState<string>("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fileType, setFileType] = useState<string>(propFileType || "pdf")

  useEffect(() => {
    if (fileId && caseId) {
      loadDocumentInfo()
    }
  }, [fileId, caseId, propFileType])

  const loadDocumentInfo = async () => {
    try {
      setLoading(true)
      setError(null)

      // Use provided file type or default to pdf
      const detectedFileType = propFileType || "pdf"
      setFileType(detectedFileType)

      // For non-PDF files, load text content
      if (detectedFileType !== "pdf") {
        const baseUrl = import.meta.env.VITE_API_URL || ""
        const url = baseUrl ? `${baseUrl}/api/cases/${caseId}/files/${fileId}/content` : `/api/cases/${caseId}/files/${fileId}/content`
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

  if (!fileId) {
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

  return (
    <div className="flex flex-col h-full">
      {/* Header with info */}
      {cellData && (
        <div className="border-b p-3 bg-muted/30">
          <div className="flex items-center gap-2 flex-wrap">
            {cellData.columnType && (
              <Badge variant="secondary">Тип: {cellData.columnType}</Badge>
            )}
            {highlightMode === "verbatim" && (
              <Badge variant="default">Подсветка цитаты</Badge>
            )}
            {highlightMode === "page" && cellData.sourcePage && (
              <Badge variant="outline">Страница: {cellData.sourcePage}</Badge>
            )}
            {highlightMode === "page" && cellData.sourceSection && (
              <Badge variant="outline">Раздел: {cellData.sourceSection}</Badge>
            )}
            {highlightMode === "none" && (
              <Badge variant="secondary">Без подсветки</Badge>
            )}
          </div>
        </div>
      )}

      {/* Document content */}
      <div className="flex-1 overflow-auto">
        {fileType === "pdf" ? (
          <div className="relative">
            <PDFViewer
              fileId={fileId}
              caseId={caseId}
              filename=""
              initialPage={
                highlightMode === "page" && cellData?.sourcePage
                  ? cellData.sourcePage
                  : highlightMode === "verbatim" && cellData?.sourcePage
                  ? cellData.sourcePage
                  : undefined
              }
              onError={(err) => {
                setError(err.message || "Ошибка при загрузке PDF")
              }}
            />
            {cellData?.sourcePage && highlightMode === "page" && (
              <div className="absolute top-2 right-2 bg-primary/90 text-primary-foreground px-3 py-1 rounded-md text-xs z-10">
                Страница {cellData.sourcePage}
              </div>
            )}
          </div>
        ) : (
          <div className="p-4">
            {showHighlight ? (
              <TextHighlighter
                text={documentText}
                highlightText={cellData.verbatimExtract || undefined}
                className="whitespace-pre-wrap text-sm"
              />
            ) : (
              <div className="whitespace-pre-wrap text-sm">{documentText}</div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

