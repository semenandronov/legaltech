import React, { useState, useEffect, useRef } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { MessageSquare, Table, FileEdit, BookOpen, Workflow, FolderOpen } from "lucide-react"
import UnifiedSidebar from "../components/Layout/UnifiedSidebar"
import { TabularReviewTable } from "../components/TabularReview/TabularReviewTable"
import { TabularReviewToolbar } from "../components/TabularReview/TabularReviewToolbar"
import { ColumnBuilder } from "../components/TabularReview/ColumnBuilder"
import { BulkColumnBuilder } from "../components/TabularReview/BulkColumnBuilder"
import { InlineCellEditor } from "../components/TabularReview/InlineCellEditor"
import { DocumentSelector } from "../components/TabularReview/DocumentSelector"
import { TabularDocumentViewer } from "../components/TabularReview/TabularDocumentViewer"
import { TemplatesModal } from "../components/TabularReview/TemplatesModal"
import { CreateTableModeDialog } from "../components/TabularReview/CreateTableModeDialog"
import { AutomaticTableCreationDialog } from "../components/TabularReview/AutomaticTableCreationDialog"
import { ExportTableDialog } from "../components/TabularReview/ExportTableDialog"
import { tabularReviewApi, TableData } from "../services/tabularReviewApi"
import { getCase } from "../services/api"
import { Card } from "../components/UI/Card"
import Spinner from "../components/UI/Spinner"
import { toast } from "sonner"
import { ArrowLeft, Edit2, X, Trash2 } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "../components/UI/dialog"
import Input from "../components/UI/Input"
import { Button } from "../components/UI/Button"
import { Drawer } from "@mui/material"

const TabularReviewPage: React.FC = () => {
  const { reviewId, caseId } = useParams<{ reviewId?: string; caseId: string }>()
  const navigate = useNavigate()
  
  const [caseName, setCaseName] = useState<string>("")
  const [tableData, setTableData] = useState<TableData | null>(null)
  const [loading, setLoading] = useState(false) // Start with false, will be set to true when actually loading
  const [processing, setProcessing] = useState(false)
  const [runningColumnIds, setRunningColumnIds] = useState<Set<string>>(new Set())
  const [showColumnBuilder, setShowColumnBuilder] = useState(false)
  const [showTableAddColumn, setShowTableAddColumn] = useState(false)
  const [bulkBuilderInitialPrompt, setBulkBuilderInitialPrompt] = useState<string | undefined>(undefined)
  const [filterPopoverOpen, setFilterPopoverOpen] = useState(false)
  const [filterAnchorEl, setFilterAnchorEl] = useState<HTMLElement | null>(null)
  const [editColumnAnchorEl, setEditColumnAnchorEl] = useState<HTMLElement | null>(null)
  const [editingColumn, setEditingColumn] = useState<{ id: string; label: string; type: string; prompt: string; column_config?: any } | null>(null)
  const [showDocumentSelector, setShowDocumentSelector] = useState(false)
  const [showTemplatesModal, setShowTemplatesModal] = useState(false)
  const [showExportDialog, setShowExportDialog] = useState(false)
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
      // Phase 4: Deep link fields
      docId?: string | null
      charStart?: number | null
      charEnd?: number | null
    }
  } | null>(null)
  const [_loadingCellDetails, setLoadingCellDetails] = useState(false)
  const [editingCell, setEditingCell] = useState<{
    fileId: string
    columnId: string
    cell: any
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const loadingRef = useRef(false)
  const [workMode, setWorkMode] = useState<"manual" | "agent">("manual")
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [isEditingName, setIsEditingName] = useState(false)
  const [editNameValue, setEditNameValue] = useState("")
  
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
  const [showNameDialog, setShowNameDialog] = useState(false)
  const [reviewName, setReviewName] = useState("")
  const [pendingFileIds, setPendingFileIds] = useState<string[]>([])
  const [showCreateModeDialog, setShowCreateModeDialog] = useState(false)
  const [showAutomaticCreationDialog, setShowAutomaticCreationDialog] = useState(false)

  // Fetch case name for breadcrumb
  useEffect(() => {
    if (!caseId) return
    getCase(caseId).then(c => setCaseName(c.title || "")).catch(() => {})
  }, [caseId])

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

  // Предупреждение при закрытии с несохранёнными изменениями
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (hasUnsavedChanges) {
        e.preventDefault()
        e.returnValue = 'У вас есть несохранённые изменения. Вы уверены, что хотите покинуть страницу?'
      }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [hasUnsavedChanges])

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
    
    // Show mode selection dialog instead of directly opening document selector
    // This is called from useEffect when no reviewId, but we want to show selector first
    // So we do nothing here - handleCreateNew will be called from button click
  }

  const handleDeleteReview = async (reviewIdToDelete: string, event: React.MouseEvent) => {
    event.stopPropagation() // Prevent card click
    
    if (!confirm(`Вы уверены, что хотите удалить таблицу "${existingReviews.find(r => r.id === reviewIdToDelete)?.name}"? Это действие нельзя отменить.`)) {
      return
    }
    
    try {
      await tabularReviewApi.deleteReview(reviewIdToDelete)
      toast.success("Таблица удалена")
      // Reload reviews list
      const data = await tabularReviewApi.listReviews(caseId)
      setExistingReviews(data.reviews)
    } catch (err: any) {
      toast.error("Не удалось удалить таблицу: " + (err.message || ""))
    }
  }

  const handleDocumentSelectorConfirm = async (fileIds: string[]) => {
    if (!caseId) return
    
    console.log('handleDocumentSelectorConfirm called with fileIds:', fileIds)
    setShowDocumentSelector(false)
    setPendingFileIds(fileIds)
    setReviewName("")
    setShowNameDialog(true)
    console.log('showNameDialog set to true')
  }

  const handleCreateReviewWithName = async () => {
    console.log('handleCreateReviewWithName called', { caseId, reviewName, pendingFileIds })
    if (!caseId || !reviewName.trim()) {
      toast.error("Введите название таблицы")
      return
    }
    
    try {
      setShowNameDialog(false)
      setLoading(true)
      console.log('Calling tabularReviewApi.createReview...')
      const review = await tabularReviewApi.createReview(
        caseId,
        reviewName.trim(),
        undefined,
        pendingFileIds
      )
      console.log('Review created:', review)
      setSelectedFileIds(pendingFileIds)
      setPendingFileIds([])
      navigate(`/cases/${caseId}/tabular-review/${review.id}`, { replace: true })
    } catch (err: any) {
      console.error('Error creating review:', err)
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
      console.log("Loaded table data:", { 
        reviewId, 
        columnsCount: data.columns.length, 
        columnLabels: data.columns.map(c => c.column_label) 
      })
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

  const handleCellEditSave = async (fileId: string, columnId: string, value: string) => {
    if (!reviewId) return
    
    try {
      await tabularReviewApi.updateCell(reviewId, fileId, columnId, value)
      toast.success("Ячейка обновлена")
      setEditingCell(null)
      setHasUnsavedChanges(false)  // Изменения сохранены
      await loadReviewData()
    } catch (err: any) {
      toast.error("Не удалось обновить ячейку: " + (err.message || ""))
      throw err
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

  const handleStartRename = () => {
    if (tableData) {
      setEditNameValue(tableData.review.name)
      setIsEditingName(true)
    }
  }

  const handleSaveRename = async () => {
    if (!reviewId || !editNameValue.trim()) {
      setIsEditingName(false)
      return
    }
    const trimmed = editNameValue.trim()
    try {
      await tabularReviewApi.updateReview(reviewId, { name: trimmed })
      setTableData(prev => prev ? { ...prev, review: { ...prev.review, name: trimmed } } : prev)
      toast.success("Название обновлено")
    } catch {
      toast.error("Не удалось обновить название")
    } finally {
      setIsEditingName(false)
    }
  }

  const handleColumnEdit = (columnId: string, anchorEl?: HTMLElement) => {
    if (!tableData) return
    const column = tableData.columns.find(c => c.id === columnId)
    if (!column) return
    setEditColumnAnchorEl(anchorEl ?? null)
    setEditingColumn({
      id: column.id,
      label: column.column_label,
      type: column.column_type,
      prompt: column.prompt || "",
      column_config: column.column_config,
    })
  }

  const handleColumnDelete = async (columnId: string) => {
    if (!reviewId) return
    
    const column = tableData?.columns.find(c => c.id === columnId)
    if (!column) return
    
    if (!confirm(`Вы уверены, что хотите удалить колонку "${column.column_label}"? Это действие нельзя отменить.`)) {
      return
    }
    
    try {
      await tabularReviewApi.deleteColumn(reviewId, columnId)
      toast.success("Колонка удалена")
      await loadReviewData()
    } catch (err: any) {
      toast.error("Не удалось удалить колонку: " + (err.message || ""))
    }
  }

  const handleUpdateColumn = async (column: {
    column_label: string
    column_type: string
    prompt: string
    column_config?: {
      options?: Array<{ label: string; color: string }>
      allow_custom?: boolean
    }
  }) => {
    if (!reviewId || !editingColumn) return
    
    try {
      await tabularReviewApi.updateColumn(
        reviewId,
        editingColumn.id,
        {
          column_label: column.column_label,
          prompt: column.prompt,
          column_config: column.column_config,
        }
      )
      toast.success("Колонка обновлена")
      setEditingColumn(null)
      setShowColumnBuilder(false)
      await loadReviewData()
    } catch (err: any) {
      toast.error("Не удалось обновить колонку: " + (err.message || ""))
      throw err
    }
  }

  const navItems = [
    { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
    { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: caseId ? `/cases/${caseId}/chat` : '/cases' },
    { id: 'editor', label: 'Редактор', icon: FileEdit, path: caseId ? `/cases/${caseId}/editor` : '/cases' },
    { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: caseId ? `/cases/${caseId}/tabular-review` : '/cases' },
    { id: 'playbooks', label: 'Playbooks', icon: BookOpen, path: caseId ? `/cases/${caseId}/playbooks` : '/cases' },
    { id: 'workflows', label: 'Workflows', icon: Workflow, path: caseId ? `/cases/${caseId}/workflows` : '/cases' },
  ]

  if (loading && !tableData) {
    return (
      <div className="h-screen bg-bg-primary flex">
        <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} />
        <div className="flex-1 flex items-center justify-center">
          <Spinner size="lg" />
        </div>
      </div>
    )
  }

  if (error && !tableData) {
    return (
      <div className="h-screen bg-bg-primary flex">
        <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} />
        <div className="flex-1 flex items-center justify-center p-6 bg-bg-primary">
          <Card className="p-6 hoverable">
            <div className="text-center">
              <h2 className="font-display text-h2 text-text-primary mb-2">Ошибка</h2>
              <p className="text-body text-text-secondary mb-4">{error}</p>
              <button
                onClick={() => navigate(`/cases/${caseId}/chat`)}
                className="px-6 py-3 bg-accent text-bg-primary font-medium rounded-lg hover:bg-accent-hover transition-all duration-300"
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
      setShowCreateModeDialog(true)
    }

    const handleSelectManualMode = () => {
      setShowReviewSelector(false)
      setShowDocumentSelector(true)
    }

    const handleSelectAutomaticMode = () => {
      setShowAutomaticCreationDialog(true)
    }

    const handleAutomaticTableCreated = (newReviewId: string) => {
      navigate(`/cases/${caseId}/tabular-review/${newReviewId}`, { replace: true })
    }

    return (
      <div className="h-screen bg-bg-primary flex">
        <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} />
        <div className="flex-1 flex flex-col bg-bg-primary">
          <div className="border-b border-border bg-bg-elevated/80 backdrop-blur-sm p-6">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-4">
                <button
                  onClick={() => navigate(`/cases/${caseId}/chat`)}
                  className="p-2 rounded-lg hover:bg-bg-hover transition-colors duration-200 text-text-secondary hover:text-text-primary flex items-center gap-2"
                >
                  <ArrowLeft className="w-4 h-4" />
                  Назад к делу
                </button>
                <h1 className="font-display text-h1 text-text-primary">Tabular Review</h1>
              </div>
              {reviewId && (
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-text-secondary">Режим работы:</span>
                  <div className="flex border border-border rounded-md overflow-hidden">
                    <button
                      onClick={() => setWorkMode("manual")}
                      className={`px-4 py-2 transition-colors ${
                        workMode === "manual"
                          ? "bg-accent text-bg-primary font-medium"
                          : "bg-bg-elevated text-text-secondary hover:bg-bg-hover"
                      }`}
                    >
                      Ручной
                    </button>
                    <button
                      onClick={() => setWorkMode("agent")}
                      className={`px-4 py-2 transition-colors border-l border-border ${
                        workMode === "agent"
                          ? "bg-accent text-bg-primary font-medium"
                          : "bg-bg-elevated text-text-secondary hover:bg-bg-hover"
                      }`}
                    >
                      Через агента
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
          <div className="flex-1 overflow-auto p-8 fade-in-up">
            {showReviewSelector ? (
              <div className="max-w-4xl mx-auto">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h2 className="font-display text-h1 text-text-primary mb-2">Выберите или создайте таблицу</h2>
                    <p className="text-body text-text-secondary">
                      Выберите существующую таблицу или создайте новую для этого дела
                    </p>
                  </div>
                  <button
                    onClick={handleCreateNew}
                    className="px-6 py-3 bg-accent text-bg-primary font-medium rounded-lg hover:bg-accent-hover transition-all duration-300"
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
                      <h3 className="font-display text-h2 text-text-primary mb-2">
                        Нет созданных таблиц
                      </h3>
                      <p className="text-body text-text-secondary mb-6">
                        Создайте первую таблицу для этого дела
                      </p>
                      <button
                        onClick={handleCreateNew}
                        className="px-6 py-3 bg-accent text-bg-primary font-medium rounded-lg hover:bg-accent-hover transition-all duration-300"
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
                        className="p-6 cursor-pointer hoverable transition-all duration-300 relative"
                        style={{ animationDelay: `${index * 0.05}s` }}
                        onClick={() => handleSelectReview(review.id)}
                      >
                        <button
                          onClick={(e) => handleDeleteReview(review.id, e)}
                          className="absolute top-4 right-4 p-2 rounded-lg hover:bg-error-bg text-error hover:text-error transition-all duration-150 z-10"
                          title="Удалить таблицу"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                        <div className="flex items-start justify-between mb-3 pr-8">
                          <h3 className="font-display text-h3 text-text-primary">{review.name}</h3>
                          <span className={`text-xs px-3 py-1 rounded-full font-medium ${
                            review.status === 'completed' ? 'bg-success-bg text-success border border-success/30' :
                            review.status === 'processing' ? 'bg-warning-bg text-warning border border-warning/30' :
                            'bg-bg-secondary text-text-secondary border border-border'
                          }`}>
                            {review.status}
                          </span>
                        </div>
                        {review.description && (
                          <p className="text-sm text-text-secondary mb-3 line-clamp-2">
                            {review.description}
                          </p>
                        )}
                        {review.updated_at && (
                          <p className="text-xs text-text-secondary">
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
                    <h3 className="font-display text-h2 text-text-primary mb-2">
                      Выберите документы для таблицы
                    </h3>
                    <p className="text-body text-text-secondary mb-6">
                      Выберите документы из дела, которые будут включены в Tabular Review
                    </p>
                    <div className="flex gap-3 justify-center">
                      <button
                        onClick={() => setShowReviewSelector(true)}
                        className="px-4 py-2 bg-bg-elevated border border-border text-text-secondary font-medium rounded-lg hover:bg-bg-hover transition-all duration-300"
                      >
                        Назад
                      </button>
                      <button
                        onClick={() => setShowDocumentSelector(true)}
                        className="px-4 py-2 bg-accent text-bg-primary font-medium rounded-lg hover:bg-accent-hover transition-all duration-300"
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

          {/* Create Mode Selection Dialog */}
          {caseId && (
            <CreateTableModeDialog
              isOpen={showCreateModeDialog}
              onClose={() => setShowCreateModeDialog(false)}
              onSelectManual={handleSelectManualMode}
              onSelectAutomatic={handleSelectAutomaticMode}
            />
          )}

          {/* Automatic Table Creation Dialog */}
          {caseId && (
            <AutomaticTableCreationDialog
              isOpen={showAutomaticCreationDialog}
              onClose={() => setShowAutomaticCreationDialog(false)}
              caseId={caseId}
              onTableCreated={handleAutomaticTableCreated}
            />
          )}

          {/* Name Dialog for creating new review */}
          <Dialog open={showNameDialog} onOpenChange={setShowNameDialog}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Введите название таблицы</DialogTitle>
              </DialogHeader>
              <div className="py-4">
                <Input
                  label="Название таблицы"
                  value={reviewName}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => setReviewName(e.target.value)}
                  placeholder="Например: Анализ договоров"
                  onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => {
                    if (e.key === 'Enter' && reviewName.trim()) {
                      handleCreateReviewWithName()
                    }
                  }}
                  autoFocus
                />
              </div>
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowNameDialog(false)
                    setPendingFileIds([])
                    setReviewName("")
                  }}
                >
                  Отмена
                </Button>
                <Button
                  onClick={handleCreateReviewWithName}
                  disabled={!reviewName.trim()}
                >
                  Создать
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>
    )
  }

  // If we have reviewId but no tableData yet
  if (!tableData || !reviewId) {
    // Show loading only if we're actually loading
    if (loading) {
      return (
        <div className="h-screen bg-bg-primary flex">
          <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} />
          <div className="flex-1 flex items-center justify-center">
            <Spinner size="lg" />
          </div>
        </div>
      )
    }
    // If not loading but no data, show error or empty state
    if (error) {
      return (
        <div className="h-screen bg-bg-primary flex">
          <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} />
          <div className="flex-1 flex items-center justify-center p-6 bg-bg-primary">
            <Card className="p-6 hoverable">
              <div className="text-center">
                <h2 className="font-display text-h2 text-text-primary mb-2">Ошибка</h2>
                <p className="text-body text-text-secondary mb-4">{error}</p>
                <div className="flex gap-3 justify-center">
                  <button
                    onClick={() => loadReviewData()}
                    className="px-4 py-2 bg-accent text-bg-primary font-medium rounded-lg hover:bg-accent-hover transition-all duration-300"
                  >
                    Попробовать снова
                  </button>
                  <button
                    onClick={() => navigate(`/cases/${caseId}/chat`)}
                    className="px-4 py-2 bg-bg-elevated border border-border text-text-secondary font-medium rounded-lg hover:bg-bg-hover transition-all duration-300"
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
      <div className="h-screen bg-bg-primary flex">
        <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} />
        <div className="flex-1 flex items-center justify-center p-6 bg-bg-primary">
          <Card className="p-6 hoverable">
            <div className="text-center">
              <p className="text-body text-text-secondary mb-4">Нет данных для отображения</p>
              <button
                onClick={() => navigate(`/cases/${caseId}/chat`)}
                className="px-6 py-3 bg-accent text-bg-primary font-medium rounded-lg hover:bg-accent-hover transition-all duration-300"
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
    <div className="h-screen bg-bg-primary flex">
      <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} />
      <div className="flex flex-col h-full flex-1 bg-bg-primary">
        {/* Header */}
        <div className="border-b border-border px-6 pt-5 pb-5" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
          {/* Breadcrumb */}
          <div className="flex items-center gap-1 text-xs mb-3" style={{ color: 'var(--color-text-muted)' }}>
            <button
              onClick={() => navigate('/cases')}
              className="hover:underline transition-colors"
              style={{ color: 'var(--color-text-muted)' }}
            >
              Дела
            </button>
            <span>/</span>
            <button
              onClick={() => navigate(`/cases/${caseId}`)}
              className="hover:underline transition-colors"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {caseName || "..."}
            </button>
            <span>/</span>
            <span>{tableData.review.name}</span>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                {isEditingName ? (
                  <input
                    autoFocus
                    value={editNameValue}
                    onChange={(e) => setEditNameValue(e.target.value)}
                    onBlur={handleSaveRename}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') { e.preventDefault(); handleSaveRename() }
                      if (e.key === 'Escape') setIsEditingName(false)
                    }}
                    className="text-2xl font-semibold tracking-tight bg-transparent border-b-2 outline-none"
                    style={{ color: 'var(--color-text-primary)', borderColor: 'var(--color-accent)', minWidth: 200 }}
                  />
                ) : (
                  <>
                    <h1 className="text-2xl font-semibold tracking-tight" style={{ color: 'var(--color-text-primary)' }}>
                      {tableData.review.name}
                    </h1>
                    <button
                      onClick={handleStartRename}
                      className="p-1 rounded transition-colors hover:bg-[var(--color-bg-hover)]"
                      style={{ color: 'var(--color-text-muted)' }}
                      title="Редактировать название"
                    >
                      <Edit2 className="w-3.5 h-3.5" />
                    </button>
                  </>
                )}
              </div>
              <p className="text-sm mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                {tableData.rows.length} документов
              </p>
            </div>
          </div>
        </div>

        {/* Toolbar */}
        <TabularReviewToolbar
          onOpenFilter={(el) => {
            setFilterAnchorEl(el)
            setFilterPopoverOpen(true)
          }}
          onUpdateDocuments={reviewId ? () => setShowDocumentSelector(true) : undefined}
          onAddColumns={() => setShowColumnBuilder(true)}
          onExport={reviewId ? () => setShowExportDialog(true) : undefined}
          processing={processing}
        />

        {/* Main Content Area */}
        <div className="flex-1 overflow-hidden flex">
          {/* Table, Cell Detail, and Document Split View */}
          <div className="flex-1 overflow-hidden flex">
            {/* Table */}
            <div className="overflow-hidden p-6 flex-1 bg-bg-primary min-h-0 flex flex-col">
              <TabularReviewTable
                  reviewId={reviewId}
                  tableData={tableData}
                  filterPopoverOpen={filterPopoverOpen}
                  filterAnchorEl={filterAnchorEl}
                  onCloseFilterPopover={() => {
                    setFilterPopoverOpen(false)
                    setFilterAnchorEl(null)
                  }}
                  onAddColumnClick={() => setShowTableAddColumn(true)}
                  showAddColumnPopover={showTableAddColumn}
                  onCloseAddColumnPopover={() => setShowTableAddColumn(false)}
                  onSaveNewColumn={handleAddColumn}
                  onInlinePromptSubmit={(prompt) => {
                    setShowTableAddColumn(false)
                    setBulkBuilderInitialPrompt(prompt)
                    setShowColumnBuilder(true)
                  }}
                  onTableDataUpdate={(updater) => {
                    if (tableData) {
                      setTableData(updater(tableData))
                    }
                  }}
                  onCellEdit={(fileId: string, columnId: string, cell: any) => {
                    setEditingCell({ fileId, columnId, cell })
                    setHasUnsavedChanges(true)  // Начали редактирование
                  }}
                  onColumnEdit={handleColumnEdit}
                  onColumnDelete={handleColumnDelete}
                  onCellClick={async (fileId, columnId, cellData) => {
                    // Find file type and name from table data
                    const row = tableData.rows.find(r => r.file_id === fileId)
                    
                    // Find the column by columnId (now passed directly from table)
                    const clickedColumn = tableData.columns.find(col => col.id === columnId)
                    
                    // If column not found, use first column as fallback
                    if (!clickedColumn && tableData.columns.length > 0) {
                      console.warn(`Column ${columnId} not found, using first column as fallback`)
                    }
                    
                    // Load cell details first to get all source information for highlighting
                    let details = null
                    if (reviewId && clickedColumn) {
                      setLoadingCellDetails(true)
                      try {
                        details = await tabularReviewApi.getCellDetails(
                          reviewId,
                          fileId,
                          clickedColumn.id
                        )
                      } catch (err) {
                        console.error("Error loading cell details:", err)
                      } finally {
                        setLoadingCellDetails(false)
                      }
                    }
                    
                    // Open document with full highlighting data (no detail panel)
                    // Use details from API if available (more complete), otherwise use cellData from table
                    const finalCellData = details ? {
                      verbatimExtract: details.verbatim_extract,
                      sourcePage: details.source_page,
                      sourceSection: details.source_section,
                      columnType: details.column_type,
                      highlightMode: details.highlight_mode || cellData.highlightMode || (details.verbatim_extract ? 'verbatim' : (details.source_page ? 'page' : 'none')),
                      sourceReferences: details.source_references || cellData.sourceReferences || [],
                      // Phase 4: Deep link fields
                      docId: details.primary_source_doc_id || fileId,  // Use doc_id if available, fallback to fileId
                      charStart: details.primary_source_char_start || undefined,
                      charEnd: details.primary_source_char_end || undefined,
                    } : {
                      ...cellData,
                      // Ensure highlightMode is set correctly
                      highlightMode: cellData.highlightMode || (cellData.verbatimExtract ? 'verbatim' : (cellData.sourcePage ? 'page' : 'none')),
                      sourceReferences: cellData.sourceReferences || [],
                      // Phase 4: Deep link fields from cellData
                      docId: cellData.docId || fileId,
                      charStart: cellData.charStart,
                      charEnd: cellData.charEnd,
                    }
                    
                    setSelectedDocument({ 
                      fileId, 
                      fileType: row?.file_type || undefined,
                      fileName: row?.file_name || undefined,
                      cellData: finalCellData,
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
                  onRunColumn={async (columnId) => {
                    if (!reviewId) return
                    setProcessing(true)
                    setRunningColumnIds((prev) => new Set([...prev, columnId]))
                    try {
                      const result = await tabularReviewApi.runColumnExtraction(reviewId, columnId)
                      toast.success(`Колонка заполнена: ${result.saved_count} ячеек сохранено`)
                      await loadReviewData()
                    } catch (err: any) {
                      toast.error("Ошибка при заполнении колонки: " + (err.message || ""))
                    } finally {
                      setRunningColumnIds((prev) => { const s = new Set(prev); s.delete(columnId); return s })
                      setProcessing(false)
                    }
                  }}
                  runningColumnIds={runningColumnIds}
                />
            </div>


          </div>
        </div>

        {/* Document viewer — slides in from the right, overlays the page */}
        <Drawer
          anchor="right"
          open={!!selectedDocument}
          onClose={() => setSelectedDocument(null)}
          slotProps={{ paper: { sx: { width: 680, display: 'flex', flexDirection: 'column' } } }}
        >
          {selectedDocument && (
            <>
              <div
                className="flex items-center justify-between px-4 py-3 border-b shrink-0"
                style={{ borderBottomColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-elevated)' }}
              >
                <span className="font-medium text-sm truncate max-w-xs" style={{ color: 'var(--color-text-primary)' }}>
                  {selectedDocument.fileName || 'Документ'}
                </span>
                <button
                  onClick={() => setSelectedDocument(null)}
                  className="p-1.5 rounded-lg transition-colors ml-3 shrink-0 hover:bg-[var(--color-bg-hover)]"
                  style={{ color: 'var(--color-text-muted)' }}
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
            </>
          )}
        </Drawer>

        {/* Edit column: single-column wizard */}
        {editingColumn != null && (
          <ColumnBuilder
            isOpen={true}
            onClose={() => {
              setEditingColumn(null)
              setEditColumnAnchorEl(null)
            }}
            onSave={handleUpdateColumn}
            editingColumn={editingColumn}
            anchorEl={editColumnAnchorEl}
          />
        )}
        {/* Column builder: bulk generate from questions (toolbar button or empty table) */}
        {showColumnBuilder && reviewId && (
          <BulkColumnBuilder
            isOpen={true}
            onClose={() => {
              setShowColumnBuilder(false)
              setBulkBuilderInitialPrompt(undefined)
            }}
            reviewId={reviewId}
            onColumnsAdded={async (columns) => {
              await loadReviewData()
              // Only auto-extract columns that actually use AI (skip manual_input)
              const aiColumns = columns.filter((c) => c.column_type !== 'manual_input')
              if (aiColumns.length === 0) return
              // Mark all AI columns as running immediately so skeletons show
              setRunningColumnIds(new Set(aiColumns.map((c) => c.id)))
              // Run extractions in parallel
              await Promise.allSettled(
                aiColumns.map(async (col) => {
                  try {
                    await tabularReviewApi.runColumnExtraction(reviewId, col.id)
                  } finally {
                    setRunningColumnIds((prev) => { const s = new Set(prev); s.delete(col.id); return s })
                  }
                })
              )
              await loadReviewData()
            }}
            initialQuestionsText={bulkBuilderInitialPrompt}
          />
        )}

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

        {/* Export Dialog */}
        {reviewId && (
          <ExportTableDialog
            open={showExportDialog}
            onClose={() => setShowExportDialog(false)}
            reviewId={reviewId}
            reviewName={tableData?.review.name ?? 'export'}
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

        {/* Cell Editor Modal */}
        {editingCell && tableData && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setEditingCell(null)}>
            <div className="bg-bg-elevated rounded-lg p-6 max-w-2xl w-full mx-4" onClick={(e) => e.stopPropagation()}>
              <h3 className="text-lg font-semibold mb-4">Редактировать ячейку</h3>
              <InlineCellEditor
                cell={editingCell.cell}
                column={tableData.columns.find(c => c.id === editingCell.columnId)!}
                onSave={async (value) => {
                  await handleCellEditSave(editingCell.fileId, editingCell.columnId, value)
                }}
                onCancel={() => setEditingCell(null)}
              />
            </div>
          </div>
        )}

      </div>
    </div>
  )
}

export default TabularReviewPage

