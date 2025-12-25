import React, { useState, useEffect } from "react"
import { useParams, useNavigate } from "react-router-dom"
import MainLayout from "../components/Layout/MainLayout"
import { TabularReviewTable } from "../components/TabularReview/TabularReviewTable"
import { TabularReviewToolbar } from "../components/TabularReview/TabularReviewToolbar"
import { ColumnBuilder } from "../components/TabularReview/ColumnBuilder"
import { DocumentSelector } from "../components/TabularReview/DocumentSelector"
import { TabularDocumentViewer } from "../components/TabularReview/TabularDocumentViewer"
import { TabularChat } from "../components/TabularReview/TabularChat"
import { tabularReviewApi, TableData } from "../services/tabularReviewApi"
import { Card } from "../components/UI/Card"
import { Button } from "../components/UI/Button"
import Spinner from "../components/UI/Spinner"
import { toast } from "sonner"
import { ArrowLeft, Edit2, X } from "lucide-react"

const TabularReviewPage: React.FC = () => {
  const { reviewId, caseId } = useParams<{ reviewId?: string; caseId: string }>()
  const navigate = useNavigate()
  
  const [tableData, setTableData] = useState<TableData | null>(null)
  const [loading, setLoading] = useState(true)
  const [processing, setProcessing] = useState(false)
  const [showColumnBuilder, setShowColumnBuilder] = useState(false)
  const [showDocumentSelector, setShowDocumentSelector] = useState(false)
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([])
  const [selectedDocument, setSelectedDocument] = useState<{
    fileId: string
    fileType?: string
    cellData: {
      verbatimExtract?: string | null
      sourcePage?: number | null
      sourceSection?: string | null
      columnType?: string
      highlightMode?: 'verbatim' | 'page' | 'none'
    }
  } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (reviewId) {
      loadReviewData()
    } else if (caseId) {
      // If no reviewId, create a new review
      createNewReview()
    }
  }, [reviewId, caseId]) // eslint-disable-line react-hooks/exhaustive-deps

  const createNewReview = async () => {
    if (!caseId) return
    
    // Show document selector first
    setShowDocumentSelector(true)
  }

  const handleDocumentSelectorConfirm = async (fileIds: string[]) => {
    if (!caseId) return
    
    setShowDocumentSelector(false)
    setSelectedFileIds(fileIds)
    
    try {
      setLoading(true)
      const review = await tabularReviewApi.createReview(
        caseId,
        "Tabular Review",
        "Automatic tabular review",
        fileIds
      )
      navigate(`/cases/${caseId}/tabular-review/${review.id}`, { replace: true })
    } catch (err: any) {
      setError(err.message || "Ошибка при создании review")
      toast.error("Не удалось создать Tabular Review")
    } finally {
      setLoading(false)
    }
  }

  const handleUpdateDocuments = async (fileIds: string[]) => {
    if (!reviewId) return
    
    try {
      await tabularReviewApi.updateSelectedFiles(reviewId, fileIds)
      setSelectedFileIds(fileIds)
      toast.success("Документы обновлены")
      await loadReviewData()
    } catch (err: any) {
      toast.error("Не удалось обновить документы: " + (err.message || ""))
    }
  }

  const loadReviewData = async () => {
    if (!reviewId) return
    
    try {
      setLoading(true)
      const data = await tabularReviewApi.getTableData(reviewId)
      setTableData(data)
      // Load selected file IDs from review
      if (data.review.selected_file_ids) {
        setSelectedFileIds(data.review.selected_file_ids)
      }
      setError(null)
    } catch (err: any) {
      setError(err.message || "Ошибка при загрузке данных")
      toast.error("Не удалось загрузить данные")
    } finally {
      setLoading(false)
    }
  }

  const handleAddColumn = async (column: {
    column_label: string
    column_type: string
    prompt: string
  }) => {
    if (!reviewId) return
    
    try {
      await tabularReviewApi.addColumn(
        reviewId,
        column.column_label,
        column.column_type,
        column.prompt
      )
      toast.success("Колонка добавлена")
      await loadReviewData()
    } catch (err: any) {
      toast.error("Не удалось добавить колонку: " + (err.message || ""))
      throw err
    }
  }

  const handleRunAll = async () => {
    if (!reviewId) return
    
    try {
      setProcessing(true)
      const result = await tabularReviewApi.runExtraction(reviewId)
      toast.success(
        `Обработка завершена: ${result.saved_count} ячеек сохранено, ${result.error_count} ошибок`
      )
      await loadReviewData()
    } catch (err: any) {
      toast.error("Ошибка при обработке: " + (err.message || ""))
    } finally {
      setProcessing(false)
    }
  }

  const handleDownload = async (format: "csv" | "excel") => {
    if (!reviewId) return
    
    try {
      let blob: Blob
      let filename: string
      
      if (format === "csv") {
        blob = await tabularReviewApi.exportToCSV(reviewId)
        filename = `tabular_review_${reviewId}.csv`
      } else {
        blob = await tabularReviewApi.exportToExcel(reviewId)
        filename = `tabular_review_${reviewId}.xlsx`
      }
      
      // Create download link
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
      
      toast.success(`Экспорт в ${format.toUpperCase()} завершен`)
    } catch (err: any) {
      toast.error("Ошибка при экспорте: " + (err.message || ""))
    }
  }

  const handleShare = () => {
    if (!reviewId) return
    // TODO: Implement share functionality
    toast.info("Функция Share будет реализована позже")
  }

  const handleAddDocuments = () => {
    if (!caseId) return
    navigate(`/cases/${caseId}/workspace`)
  }

  if (loading && !tableData) {
    return (
      <MainLayout>
        <div className="flex items-center justify-center h-full">
          <Spinner size="lg" />
        </div>
      </MainLayout>
    )
  }

  if (error && !tableData) {
    return (
      <MainLayout>
        <Card className="p-6">
          <div className="text-center">
            <h2 className="text-xl font-semibold mb-2">Ошибка</h2>
            <p className="text-muted-foreground mb-4">{error}</p>
            <Button onClick={() => navigate(`/cases/${caseId}`)}>
              Вернуться к делу
            </Button>
          </div>
        </Card>
      </MainLayout>
    )
  }

  if (!tableData || !reviewId) {
    return (
      <MainLayout>
        <div className="flex items-center justify-center h-full">
          <Spinner size="lg" />
        </div>
      </MainLayout>
    )
  }

  return (
    <MainLayout>
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="border-b bg-background p-4">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-4">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => navigate(`/cases/${caseId}`)}
              >
                <ArrowLeft className="w-4 h-4 mr-2" />
                Назад к делу
              </Button>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-2xl font-bold">{tableData.review.name}</h1>
                  <Button variant="ghost" size="sm">
                    <Edit2 className="w-4 h-4" />
                  </Button>
                </div>
                {tableData.review.description && (
                  <p className="text-sm text-muted-foreground mt-1">
                    {tableData.review.description}
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Toolbar */}
        <TabularReviewToolbar
          onAddDocuments={handleAddDocuments}
          onUpdateDocuments={reviewId ? () => setShowDocumentSelector(true) : undefined}
          onAddColumns={() => setShowColumnBuilder(true)}
          onRunAll={handleRunAll}
          onDownload={handleDownload}
          onShare={handleShare}
          processing={processing}
        />

        {/* Chat, Table and Document Split View */}
        <div className="flex-1 overflow-hidden flex">
          {/* Chat (Left Panel) */}
          {reviewId && tableData && (
            <div className="w-80 border-r shrink-0">
              <TabularChat
                reviewId={reviewId}
                caseId={caseId || ""}
                tableData={tableData}
                onDocumentClick={(fileId) => {
                  // Find row and open document
                  const row = tableData.rows.find(r => r.file_id === fileId)
                  if (row) {
                    // Open first cell or just the document
                    const firstColumn = tableData.columns[0]
                    if (firstColumn) {
                      const cell = row.cells[firstColumn.id]
                      let highlightMode: 'verbatim' | 'page' | 'none' = 'none'
                      if (cell?.verbatim_extract) {
                        highlightMode = 'verbatim'
                      } else if (cell?.source_page || cell?.source_section) {
                        highlightMode = 'page'
                      }
                      setSelectedDocument({
                        fileId,
                        fileType: row.file_type,
                        cellData: {
                          verbatimExtract: cell?.verbatim_extract,
                          sourcePage: cell?.source_page,
                          sourceSection: cell?.source_section,
                          columnType: firstColumn.column_type,
                          highlightMode,
                        }
                      })
                    } else {
                      setSelectedDocument({
                        fileId,
                        fileType: row.file_type,
                        cellData: { highlightMode: 'none' }
                      })
                    }
                  }
                }}
              />
            </div>
          )}

          {/* Table */}
          <div className={`overflow-auto p-4 transition-all flex-1 ${selectedDocument ? 'w-1/2' : ''}`}>
            {tableData.columns.length === 0 ? (
              <Card className="p-6">
                <div className="text-center">
                  <h3 className="text-lg font-semibold mb-2">
                    Нет колонок
                  </h3>
                  <p className="text-muted-foreground mb-4">
                    Добавьте колонки для начала работы с Tabular Review
                  </p>
                  <Button onClick={() => setShowColumnBuilder(true)}>
                    Добавить колонку
                  </Button>
                </div>
              </Card>
            ) : (
              <TabularReviewTable
                reviewId={reviewId}
                tableData={tableData}
                onCellClick={(fileId, cellData) => {
                  // Find file type from table data
                  const row = tableData.rows.find(r => r.file_id === fileId)
                  setSelectedDocument({ 
                    fileId, 
                    fileType: row?.file_type,
                    cellData 
                  })
                }}
              />
            )}
          </div>

          {/* Document Viewer */}
          {selectedDocument && (
            <div className="w-1/3 border-l bg-background flex flex-col shrink-0">
              <div className="border-b p-2 flex items-center justify-between">
                <span className="text-sm font-medium">Документ</span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setSelectedDocument(null)}
                >
                  <X className="w-4 h-4" />
                </Button>
              </div>
              <div className="flex-1 overflow-hidden">
                <TabularDocumentViewer
                  fileId={selectedDocument.fileId}
                  caseId={caseId || ""}
                  fileType={selectedDocument.fileType}
                  cellData={selectedDocument.cellData}
                  onClose={() => setSelectedDocument(null)}
                />
              </div>
            </div>
          )}
        </div>

        {/* Column Builder Modal */}
        <ColumnBuilder
          isOpen={showColumnBuilder}
          onClose={() => setShowColumnBuilder(false)}
          onSave={handleAddColumn}
        />

        {/* Document Selector Modal */}
        {caseId && (
          <DocumentSelector
            isOpen={showDocumentSelector}
            onClose={() => setShowDocumentSelector(false)}
            onConfirm={reviewId ? handleUpdateDocuments : handleDocumentSelectorConfirm}
            reviewId={reviewId || ""}
            initialSelectedIds={selectedFileIds}
            caseId={caseId}
          />
        )}
      </div>
    </MainLayout>
  )
}

export default TabularReviewPage

