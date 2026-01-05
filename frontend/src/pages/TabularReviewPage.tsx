import React, { useState, useEffect, useRef } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { MessageSquare, FileText, Table } from "lucide-react"
import UnifiedSidebar from "../components/Layout/UnifiedSidebar"
import { TabularReviewTable } from "../components/TabularReview/TabularReviewTable"
import { TabularReviewToolbar } from "../components/TabularReview/TabularReviewToolbar"
import { ColumnBuilder } from "../components/TabularReview/ColumnBuilder"
import { DocumentSelector } from "../components/TabularReview/DocumentSelector"
import { TabularDocumentViewer } from "../components/TabularReview/TabularDocumentViewer"
import { TabularReviewContextChat } from "../components/TabularReview/TabularReviewContextChat"
import { TemplatesModal } from "../components/TabularReview/TemplatesModal"
import { FeaturedTemplatesCarousel } from "../components/TabularReview/FeaturedTemplatesCarousel"
import { CellDetailPanel } from "../components/TabularReview/CellDetailPanel"
import { tabularReviewApi, TableData } from "../services/tabularReviewApi"
import { Card } from "../components/UI/Card"
import Spinner from "../components/UI/Spinner"
import { toast } from "sonner"
import { ArrowLeft, Edit2, X } from "lucide-react"

const TabularReviewPage: React.FC = () => {
  const { reviewId, caseId } = useParams<{ reviewId?: string; caseId: string }>()
  const navigate = useNavigate()
  
  const [tableData, setTableData] = useState<TableData | null>(null)
  const [loading, setLoading] = useState(false) // Start with false, will be set to true when actually loading
  const [processing, setProcessing] = useState(false)
  const [showColumnBuilder, setShowColumnBuilder] = useState(false)
  const [showDocumentSelector, setShowDocumentSelector] = useState(false)
  const [showTemplatesModal, setShowTemplatesModal] = useState(false)
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([])
  const [selectedDocument, setSelectedDocument] = useState<{
    fileId: string
    fileType?: string
    fileName?: string
    cellData: {
      verbatimExtract?: string | null
      sourcePage?: number | null
      sourceSection?: string | null
      columnType?: string
      highlightMode?: 'verbatim' | 'page' | 'none'
      sourceReferences?: Array<{ page?: number | null; section?: string | null; text: string }>
    }
  } | null>(null)
  const [selectedCell, setSelectedCell] = useState<{
    fileId: string
    columnId: string
    fileName: string
    columnLabel: string
  } | null>(null)
  const [cellDetails, setCellDetails] = useState<any>(null)
  const [_loadingCellDetails, setLoadingCellDetails] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const loadingRef = useRef(false)
  
  // State for review selector (when no reviewId)
  const [existingReviews, setExistingReviews] = useState<Array<{
    id: string
    name: string
    description?: string
    status: string
    created_at?: string
    updated_at?: string
  }>>([])
  const [loadingReviews, setLoadingReviews] = useState(false)
  const [showReviewSelector, setShowReviewSelector] = useState(true)

  // Load existing reviews when caseId is available but no reviewId
  useEffect(() => {
    const loadReviews = async () => {
      if (!caseId || reviewId) return // Only load if we have caseId but no reviewId
      try {
        setLoadingReviews(true)
        const data = await tabularReviewApi.listReviews(caseId)
        setExistingReviews(data.reviews)
      } catch (err: any) {
        console.error("Error loading reviews:", err)
        toast.error("Не удалось загрузить список таблиц")
      } finally {
        setLoadingReviews(false)
      }
    }
    loadReviews()
  }, [caseId, reviewId])

  useEffect(() => {
    if (reviewId && !loadingRef.current) {
      loadReviewData()
    } else if (caseId && !reviewId && !loadingRef.current) {
      // If no reviewId, show document selector to create new review
      setLoading(false) // No loading needed for new review creation
      createNewReview()
    } else if (!caseId) {
      // No caseId, can't do anything
      setLoading(false)
      setError("Case ID не найден")
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
    if (!reviewId || loadingRef.current) return
    
    try {
      loadingRef.current = true
      setLoading(true)
      setError(null)
      const data = await tabularReviewApi.getTableData(reviewId)
      setTableData(data)
      // Load selected file IDs from review
      if (data.review.selected_file_ids) {
        setSelectedFileIds(data.review.selected_file_ids)
      }
    } catch (err: any) {
      console.error("Error loading review data:", err)
      setError(err.message || "Ошибка при загрузке данных")
      toast.error("Не удалось загрузить данные: " + (err.message || "Неизвестная ошибка"))
      setTableData(null) // Clear table data on error
    } finally {
      setLoading(false)
      loadingRef.current = false
    }
  }

  const handleAddColumn = async (column: {
    column_label: string
    column_type: string
    prompt: string
    column_config?: {
      options?: Array<{ label: string; color: string }>
      allow_custom?: boolean
    }
  }) => {
    if (!reviewId) return
    
    try {
      await tabularReviewApi.addColumn(
        reviewId,
        column.column_label,
        column.column_type,
        column.prompt,
        column.column_config
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
    navigate(`/cases/${caseId}/chat`)
  }

  const navItems = caseId ? [
    { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
    { id: 'documents', label: 'Документы', icon: FileText, path: `/cases/${caseId}/documents` },
    { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
  ] : []

  if (loading && !tableData) {
    return (
      <div className="h-screen bg-gradient-to-br from-[#F8F9FA] via-white to-[#F0F4F8] flex">
        {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
        <div className="flex-1 flex items-center justify-center">
          <Spinner size="lg" />
        </div>
      </div>
    )
  }

  if (error && !tableData) {
    return (
      <div className="h-screen bg-gradient-to-br from-[#F8F9FA] via-white to-[#F0F4F8] flex">
        {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
        <div className="flex-1 flex items-center justify-center p-6 content-background">
          <Card className="p-6 hoverable">
            <div className="text-center">
              <h2 className="font-display text-h2 text-[#1F2937] mb-2">Ошибка</h2>
              <p className="text-body text-[#6B7280] mb-4">{error}</p>
              <button
                onClick={() => navigate(`/cases/${caseId}/chat`)}
                className="px-6 py-3 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300"
              >
                Вернуться к делу
              </button>
            </div>
          </Card>
        </div>
      </div>
    )
  }

  // If no reviewId, show interface to create new review or select existing
  if (!reviewId && caseId) {
    const handleSelectReview = (selectedReviewId: string) => {
      navigate(`/cases/${caseId}/tabular-review/${selectedReviewId}`, { replace: true })
    }

    const handleCreateNew = () => {
      setShowReviewSelector(false)
      setShowDocumentSelector(true)
    }

    return (
      <div className="h-screen bg-gradient-to-br from-[#F8F9FA] via-white to-[#F0F4F8] flex">
        {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
        <div className="flex-1 flex flex-col content-background">
          <div className="border-b border-[#E5E7EB] bg-white/80 backdrop-blur-sm p-6">
            <div className="flex items-center gap-4">
              <button
                onClick={() => navigate(`/cases/${caseId}/chat`)}
                className="p-2 rounded-lg hover:bg-[#F3F4F6] transition-colors duration-200 text-[#6B7280] hover:text-[#1F2937] flex items-center gap-2"
              >
                <ArrowLeft className="w-4 h-4" />
                Назад к делу
              </button>
              <h1 className="font-display text-h1 text-[#1F2937]">Tabular Review</h1>
            </div>
          </div>
          <div className="flex-1 overflow-auto p-8 fade-in-up">
            {showReviewSelector ? (
              <div className="max-w-4xl mx-auto">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h2 className="font-display text-h1 text-[#1F2937] mb-2">Выберите или создайте таблицу</h2>
                    <p className="text-body text-[#6B7280]">
                      Выберите существующую таблицу или создайте новую для этого дела
                    </p>
                  </div>
                  <button
                    onClick={handleCreateNew}
                    className="px-6 py-3 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300"
                  >
                    Создать новую таблицу
                  </button>
                </div>

                {loadingReviews ? (
                  <div className="flex items-center justify-center py-12">
                    <Spinner size="lg" />
                  </div>
                ) : existingReviews.length === 0 ? (
                  <Card className="p-8 hoverable">
                    <div className="text-center">
                      <h3 className="font-display text-h2 text-[#1F2937] mb-2">
                        Нет созданных таблиц
                      </h3>
                      <p className="text-body text-[#6B7280] mb-6">
                        Создайте первую таблицу для этого дела
                      </p>
                      <button
                        onClick={handleCreateNew}
                        className="px-6 py-3 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300"
                      >
                        Создать таблицу
                      </button>
                    </div>
                  </Card>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {existingReviews.map((review, index) => (
                      <Card
                        key={review.id}
                        className="p-6 cursor-pointer hoverable transition-all duration-300"
                        style={{ animationDelay: `${index * 0.05}s` }}
                        onClick={() => handleSelectReview(review.id)}
                      >
                        <div className="flex items-start justify-between mb-3">
                          <h3 className="font-display text-h3 text-[#1F2937]">{review.name}</h3>
                          <span className={`text-xs px-3 py-1 rounded-full font-medium ${
                            review.status === 'completed' ? 'bg-gradient-to-r from-[#10B981]/20 to-[#059669]/20 text-[#10B981] border border-[#10B981]/30' :
                            review.status === 'processing' ? 'bg-gradient-to-r from-[#F59E0B]/20 to-[#D97706]/20 text-[#F59E0B] border border-[#F59E0B]/30' :
                            'bg-gradient-to-r from-[#6B7280]/20 to-[#4B5563]/20 text-[#6B7280] border border-[#6B7280]/30'
                          }`}>
                            {review.status}
                          </span>
                        </div>
                        {review.description && (
                          <p className="text-sm text-[#6B7280] mb-3 line-clamp-2">
                            {review.description}
                          </p>
                        )}
                        {review.updated_at && (
                          <p className="text-xs text-[#6B7280]">
                            Обновлено: {new Date(review.updated_at).toLocaleDateString('ru-RU')}
                          </p>
                        )}
                      </Card>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="max-w-md mx-auto">
                <Card className="p-6 hoverable">
                  <div className="text-center">
                    <h3 className="font-display text-h2 text-[#1F2937] mb-2">
                      Выберите документы для таблицы
                    </h3>
                    <p className="text-body text-[#6B7280] mb-6">
                      Выберите документы из дела, которые будут включены в Tabular Review
                    </p>
                    <div className="flex gap-3 justify-center">
                      <button
                        onClick={() => setShowReviewSelector(true)}
                        className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] font-medium rounded-lg hover:bg-[#F3F4F6] transition-all duration-300"
                      >
                        Назад
                      </button>
                      <button
                        onClick={() => setShowDocumentSelector(true)}
                        className="px-4 py-2 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300"
                      >
                        Выбрать документы
                      </button>
                    </div>
                  </div>
                </Card>
              </div>
            )}
          </div>
          {caseId && (
            <DocumentSelector
              isOpen={showDocumentSelector}
              onClose={() => {
                setShowDocumentSelector(false)
                setShowReviewSelector(true)
              }}
              onConfirm={handleDocumentSelectorConfirm}
              reviewId=""
              initialSelectedIds={[]}
              caseId={caseId}
            />
          )}
        </div>
      </div>
    )
  }

  // If we have reviewId but no tableData yet
  if (!tableData || !reviewId) {
    // Show loading only if we're actually loading
    if (loading) {
      return (
        <div className="h-screen bg-gradient-to-br from-[#F8F9FA] via-white to-[#F0F4F8] flex">
          {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
          <div className="flex-1 flex items-center justify-center">
            <Spinner size="lg" />
          </div>
        </div>
      )
    }
    // If not loading but no data, show error or empty state
    if (error) {
      return (
        <div className="h-screen bg-gradient-to-br from-[#F8F9FA] via-white to-[#F0F4F8] flex">
          {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
          <div className="flex-1 flex items-center justify-center p-6 content-background">
            <Card className="p-6 hoverable">
              <div className="text-center">
                <h2 className="font-display text-h2 text-[#1F2937] mb-2">Ошибка</h2>
                <p className="text-body text-[#6B7280] mb-4">{error}</p>
                <div className="flex gap-3 justify-center">
                  <button
                    onClick={() => loadReviewData()}
                    className="px-4 py-2 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300"
                  >
                    Попробовать снова
                  </button>
                  <button
                    onClick={() => navigate(`/cases/${caseId}/chat`)}
                    className="px-4 py-2 bg-white border border-[#E5E7EB] text-[#6B7280] font-medium rounded-lg hover:bg-[#F3F4F6] transition-all duration-300"
                  >
                    Вернуться к делу
                  </button>
                </div>
              </div>
            </Card>
          </div>
        </div>
      )
    }
    // If no error but no data, show empty state
    return (
      <div className="h-screen bg-gradient-to-br from-[#F8F9FA] via-white to-[#F0F4F8] flex">
        {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
        <div className="flex-1 flex items-center justify-center p-6 content-background">
          <Card className="p-6 hoverable">
            <div className="text-center">
              <p className="text-body text-[#6B7280] mb-4">Нет данных для отображения</p>
              <button
                onClick={() => navigate(`/cases/${caseId}/chat`)}
                className="px-6 py-3 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300"
              >
                Вернуться к делу
              </button>
            </div>
          </Card>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen bg-gradient-to-br from-[#F8F9FA] via-white to-[#F0F4F8] flex">
      {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
      <div className="flex flex-col h-full flex-1 content-background">
        {/* Header */}
        <div className="border-b border-[#E5E7EB] bg-white/80 backdrop-blur-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-4">
              <button
                onClick={() => navigate(`/cases/${caseId}/chat`)}
                className="p-2 rounded-lg hover:bg-[#F3F4F6] transition-colors duration-200 text-[#6B7280] hover:text-[#1F2937] flex items-center gap-2"
              >
                <ArrowLeft className="w-4 h-4" />
                Назад к делу
              </button>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="font-display text-h1 text-[#1F2937]">{tableData.review.name}</h1>
                  <button 
                    onClick={() => toast.info("Редактирование названия будет реализовано позже")}
                    className="p-2 rounded-lg hover:bg-[#F3F4F6] transition-colors duration-200 text-[#6B7280] hover:text-[#1F2937]"
                    title="Редактировать название"
                  >
                    <Edit2 className="w-4 h-4" />
                  </button>
                </div>
                {tableData.review.description && (
                  <p className="text-sm text-[#6B7280] mt-1">
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
          onTemplates={reviewId ? () => setShowTemplatesModal(true) : undefined}
          onRunAll={handleRunAll}
          onDownload={handleDownload}
          onShare={handleShare}
          processing={processing}
        />

        {/* Featured Templates Carousel */}
        {reviewId && tableData.columns.length === 0 && (
          <div className="px-6 py-4 bg-white/50">
            <FeaturedTemplatesCarousel
              reviewId={reviewId}
              onTemplateApplied={loadReviewData}
              onViewAll={() => setShowTemplatesModal(true)}
            />
          </div>
        )}

        {/* Main Content Area */}
        <div className="flex-1 overflow-hidden flex">
          {/* Chat (Left Panel) */}
          {reviewId && tableData && (
            <div className="w-80 border-r border-[#E5E7EB] shrink-0 bg-white flex flex-col">
              <TabularReviewContextChat
                reviewId={reviewId}
                reviewName={tableData.review.name}
                tableData={tableData}
                onExtractKeyPoints={async () => {
                  // Extract key points logic
                  toast.info("Извлечение ключевых моментов...")
                }}
                onRefineColumns={() => {
                  setShowColumnBuilder(true)
                }}
                onAddDocuments={() => {
                  setShowDocumentSelector(true)
                }}
              />
            </div>
          )}

          {/* Table, Cell Detail, and Document Split View */}
          <div className="flex-1 overflow-hidden flex">
            {/* Table */}
            <div className={`overflow-auto p-6 transition-all bg-white ${selectedCell ? 'w-2/5' : selectedDocument ? 'w-1/2' : 'flex-1'}`}>
              {tableData.columns.length === 0 ? (
                <Card className="p-6 hoverable">
                  <div className="text-center">
                    <h3 className="font-display text-h2 text-[#1F2937] mb-2">
                      Нет колонок
                    </h3>
                    <p className="text-body text-[#6B7280] mb-6">
                      Добавьте колонки для начала работы с Tabular Review
                    </p>
                    <button
                      onClick={() => setShowColumnBuilder(true)}
                      className="px-6 py-3 bg-gradient-to-r from-[#00D4FF] to-[#7C3AED] text-white font-medium rounded-lg hover:shadow-lg hover:shadow-[#00D4FF]/30 transition-all duration-300"
                    >
                      Добавить колонку
                    </button>
                  </div>
                </Card>
              ) : (
                <TabularReviewTable
                  reviewId={reviewId}
                  tableData={tableData}
                  onTableDataUpdate={(updater) => {
                    if (tableData) {
                      setTableData(updater(tableData))
                    }
                  }}
                  onCellClick={async (fileId, cellData) => {
                    // Find file type and name from table data
                    const row = tableData.rows.find(r => r.file_id === fileId)
                    const column = tableData.columns.find(() => {
                      // Try to find column by matching cell data or use first column
                      return true
                    })
                    
                    if (column) {
                      setSelectedCell({
                        fileId,
                        columnId: column.id,
                        fileName: row?.file_name || "Document",
                        columnLabel: column.column_label,
                      })
                      
                      // Load cell details
                      if (reviewId) {
                        setLoadingCellDetails(true)
                        try {
                          const details = await tabularReviewApi.getCellDetails(
                            reviewId,
                            fileId,
                            column.id
                          )
                          setCellDetails(details)
                        } catch (err) {
                          console.error("Error loading cell details:", err)
                        } finally {
                          setLoadingCellDetails(false)
                        }
                      }
                    }
                    
                    setSelectedDocument({ 
                      fileId, 
                      fileType: row?.file_type,
                      fileName: row?.file_name,
                      cellData: {
                        ...cellData,
                        sourceReferences: cellDetails?.source_references,
                      }
                    })
                  }}
                  onRemoveDocument={async (fileId) => {
                    if (!reviewId) return
                    try {
                      // Remove file from selected files
                      const currentFileIds = selectedFileIds.filter(id => id !== fileId)
                      await tabularReviewApi.updateSelectedFiles(reviewId, currentFileIds)
                      setSelectedFileIds(currentFileIds)
                      toast.success("Документ удален из таблицы")
                      await loadReviewData()
                    } catch (err: any) {
                      toast.error("Не удалось удалить документ: " + (err.message || ""))
                    }
                  }}
                  onRunColumn={async (_columnId) => {
                    if (!reviewId) return
                    try {
                      // For now, run extraction for all (you might want to add column-specific extraction)
                      setProcessing(true)
                      const result = await tabularReviewApi.runExtraction(reviewId)
                      toast.success(
                        `Обработка завершена: ${result.saved_count} ячеек сохранено`
                      )
                      await loadReviewData()
                    } catch (err: any) {
                      toast.error("Ошибка при обработке: " + (err.message || ""))
                    } finally {
                      setProcessing(false)
                    }
                  }}
                />
              )}
            </div>

            {/* Cell Detail Panel */}
            {selectedCell && (
              <CellDetailPanel
                fileName={selectedCell.fileName}
                columnLabel={selectedCell.columnLabel}
                cellDetails={cellDetails}
                onClose={() => {
                  setSelectedCell(null)
                  setCellDetails(null)
                }}
                onEdit={() => {
                  toast.info("Редактирование ячейки будет реализовано позже")
                }}
                onRefresh={async () => {
                  if (reviewId && selectedCell) {
                    setLoadingCellDetails(true)
                    try {
                      const details = await tabularReviewApi.getCellDetails(
                        reviewId,
                        selectedCell.fileId,
                        selectedCell.columnId
                      )
                      setCellDetails(details)
                      toast.success("Данные обновлены")
                    } catch (err) {
                      toast.error("Ошибка при обновлении данных")
                    } finally {
                      setLoadingCellDetails(false)
                    }
                  }
                }}
                onJumpToSource={(ref) => {
                  // Update selected document with source reference
                  const row = tableData.rows.find(r => r.file_id === selectedCell.fileId)
                  setSelectedDocument({
                    fileId: selectedCell.fileId,
                    fileType: row?.file_type,
                    fileName: selectedCell.fileName,
                    cellData: {
                      sourcePage: ref.page || undefined,
                      sourceSection: ref.section || undefined,
                      highlightMode: 'page' as const,
                      sourceReferences: [ref],
                    }
                  })
                }}
              />
            )}

            {/* Document Viewer */}
            {selectedDocument && (
              <div className={`border-l border-[#E5E7EB] bg-white flex flex-col shrink-0 ${selectedCell ? 'w-2/5' : 'w-1/3'}`}>
                <div className="border-b border-[#E5E7EB] p-3 flex items-center justify-between bg-white/80 backdrop-blur-sm">
                  <span className="text-sm font-medium text-[#1F2937]">Документ</span>
                  <button
                    onClick={() => setSelectedDocument(null)}
                    className="p-2 rounded-lg hover:bg-[#F3F4F6] transition-colors duration-200 text-[#6B7280] hover:text-[#1F2937]"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <div className="flex-1 overflow-hidden">
                  <TabularDocumentViewer
                    fileId={selectedDocument.fileId}
                    caseId={caseId || ""}
                    fileType={selectedDocument.fileType}
                    fileName={selectedDocument.fileName}
                    cellData={selectedDocument.cellData}
                    onClose={() => setSelectedDocument(null)}
                  />
                </div>
              </div>
            )}
          </div>
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

        {/* Templates Modal */}
        {reviewId && (
          <TemplatesModal
            isOpen={showTemplatesModal}
            onClose={() => setShowTemplatesModal(false)}
            reviewId={reviewId}
            onTemplateApplied={loadReviewData}
          />
        )}
      </div>
    </div>
  )
}

export default TabularReviewPage

