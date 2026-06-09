import React, { useState, useEffect, useRef, useCallback } from "react"
import { useParams, useNavigate, useSearchParams } from "react-router-dom"
import { MessageSquare, FileEdit, BookOpen, Workflow, FolderOpen } from "lucide-react"
import UnifiedSidebar from "../components/Layout/UnifiedSidebar"
import { TabularReviewTable } from "../components/TabularReview/TabularReviewTable"
import { TabularReviewToolbar } from "../components/TabularReview/TabularReviewToolbar"
import { ColumnBuilder } from "../components/TabularReview/ColumnBuilder"
import { BulkColumnBuilder } from "../components/TabularReview/BulkColumnBuilder"
import { InlineCellEditor } from "../components/TabularReview/InlineCellEditor"
import { DocumentSelector } from "../components/TabularReview/DocumentSelector"
import { TabularDocumentViewer } from "../components/TabularReview/TabularDocumentViewer"
import { TemplatesModal } from "../components/TabularReview/TemplatesModal"
import { CaseTabularHubModal } from "../components/TabularReview/CaseTabularHubModal"
import { TabularReviewHelpPanel } from "../components/TabularReview/TabularReviewHelpPanel"
import { TabularReviewContextChat } from "../components/TabularReview/TabularReviewContextChat"
import { ExportTableDialog } from "../components/TabularReview/ExportTableDialog"
import { tabularReviewApi, TableData, TabularColumn } from "../services/tabularReviewApi"
import { appendColumnsToTableData, applyColumnCellsToTableData, applySingleColumnCellToTableData, buildProcessingCellKeys, clearProcessingCellKey, clearProcessingCellKeysForColumn, removeColumnFromTableData } from "../utils/tabularTableState"
import {
  countResolvedColumnCells,
  startColumnExtractionPoll,
  type ColumnExtractionPollController,
} from "../utils/tabularColumnExtractionPoll"
import { buildTabularViewerCellData, type TabularCellClickPayload } from "../utils/tabularCellViewerData"
import { useTabularReviewWebSocket } from "../hooks/useTabularReviewWebSocket"
import { getCase, getDocuments } from "../services/api"
import { Card } from "../components/UI/Card"
import Spinner from "../components/UI/Spinner"
import { toast } from "sonner"
import { Edit2, X, Check, LayoutTemplate } from "lucide-react"
import { Drawer } from "@mui/material"

const TabularReviewPage: React.FC = () => {
  const { reviewId, caseId } = useParams<{ reviewId?: string; caseId: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const returnTo = searchParams.get("returnTo")

  const navigateBackToConversation = () => {
    if (returnTo) {
      try {
        navigate(decodeURIComponent(returnTo))
      } catch {
        navigate(`/cases/${caseId}/chat`)
      }
    } else {
      navigate(`/cases/${caseId}/chat`)
    }
  }
  
  const [caseName, setCaseName] = useState<string>("")
  const [tableData, setTableData] = useState<TableData | null>(null)
  const [loading, setLoading] = useState(false) // Start with false, will be set to true when actually loading
  const [processing, setProcessing] = useState(false)
  const [runningColumnIds, setRunningColumnIds] = useState<Set<string>>(new Set())
  const [processingCellKeys, setProcessingCellKeys] = useState<Set<string>>(new Set())
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
    sourceReferenceIndex?: number
    cellData: ReturnType<typeof buildTabularViewerCellData>
  } | null>(null)
  const [_loadingCellDetails, setLoadingCellDetails] = useState(false)
  const [editingCell, setEditingCell] = useState<{
    fileId: string
    columnId: string
    cell: any
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const loadingRef = useRef(false)
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
  const [showHelpPanel, setShowHelpPanel] = useState(false)
  const [showTableChat, setShowTableChat] = useState(true)
  const [caseFilesForHub, setCaseFilesForHub] = useState<Array<{ id: string; filename: string }>>([])
  const columnPollControllersRef = useRef<Map<string, ColumnExtractionPollController>>(new Map())
  const wsCompletedColumnRef = useRef<Set<string>>(new Set())

  const handleRealtimeCellUpdated = useCallback((update: Parameters<typeof applySingleColumnCellToTableData>[1]) => {
    setTableData((prev) => (prev ? applySingleColumnCellToTableData(prev, update) : prev))
    setProcessingCellKeys((prev) => clearProcessingCellKey(prev, update.column_id, update.file_id))
  }, [])

  const handleRealtimeExtractionCellFinished = useCallback(
    ({ column_id, file_id, success }: { column_id: string; file_id: string; success: boolean }) => {
      if (success) {
        return
      }
      setProcessingCellKeys((prev) => clearProcessingCellKey(prev, column_id, file_id))
    },
    [],
  )

  const beginColumnExtractionUi = useCallback((columnId: string, fileIds: string[]) => {
    setRunningColumnIds((prev) => new Set([...prev, columnId]))
    setProcessingCellKeys((prev) => {
      const next = new Set(prev)
      for (const key of buildProcessingCellKeys(columnId, fileIds)) {
        next.add(key)
      }
      return next
    })
  }, [])

  const finishColumnExtractionUi = useCallback((columnId: string) => {
    setRunningColumnIds((prev) => {
      const next = new Set(prev)
      next.delete(columnId)
      return next
    })
    setProcessingCellKeys((prev) => clearProcessingCellKeysForColumn(prev, columnId))
  }, [])

  const handleRealtimeColumnDeleted = useCallback((columnId: string) => {
    if (editingColumn?.id === columnId) {
      setEditingColumn(null)
      setEditColumnAnchorEl(null)
    }
    setTableData((prev) => (prev ? removeColumnFromTableData(prev, columnId) : prev))
    finishColumnExtractionUi(columnId)
  }, [editingColumn?.id, finishColumnExtractionUi])

  // Fetch case name for breadcrumb
  useEffect(() => {
    if (!caseId) return
    getCase(caseId).then(c => setCaseName(c.title || "")).catch(() => {})
  }, [caseId])

  const reloadReviews = useCallback(async () => {
    if (!caseId) return
    try {
      setLoadingReviews(true)
      const data = await tabularReviewApi.listReviews(caseId)
      setExistingReviews(data.reviews)
    } catch (err: unknown) {
      console.error("Error loading reviews:", err)
      toast.error("Не удалось загрузить список таблиц")
    } finally {
      setLoadingReviews(false)
    }
  }, [caseId])

  useEffect(() => {
    if (!caseId || reviewId) return
    reloadReviews()
  }, [caseId, reviewId, reloadReviews])

  useEffect(() => {
    if (!caseId || reviewId) return
    getDocuments(caseId)
      .then((res) => {
        setCaseFilesForHub(
          (res.documents || []).map((d) => ({ id: d.id, filename: d.filename })),
        )
      })
      .catch(() => setCaseFilesForHub([]))
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
      setLoading(false)
    } else if (!caseId) {
      // No caseId, can't do anything
      setLoading(false)
      setError("Case ID не найден")
    }
  }, [reviewId, caseId]) // eslint-disable-line react-hooks/exhaustive-deps

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

  const refreshTableDataQuiet = useCallback(async (): Promise<TableData | null> => {
    if (!reviewId) return null
    try {
      const data = await tabularReviewApi.getTableData(reviewId)
      setTableData(data)
      if (data.review.selected_file_ids) {
        setSelectedFileIds(data.review.selected_file_ids)
      }
      return data
    } catch (err) {
      console.error("Error refreshing table data:", err)
      return null
    }
  }, [reviewId])

  const stopColumnPoll = useCallback((columnId: string) => {
    columnPollControllersRef.current.get(columnId)?.stop()
    columnPollControllersRef.current.delete(columnId)
  }, [])

  const syncProcessingKeysFromTable = useCallback((columnId: string, data: TableData) => {
    setProcessingCellKeys((prev) => {
      let next = prev
      for (const row of data.rows) {
        const cell = row.cells[columnId]
        if (cell?.status && cell.status !== "pending") {
          next = clearProcessingCellKey(next, columnId, row.file_id)
        }
      }
      return next
    })
  }, [])

  const showColumnExtractionSuccessToast = useCallback((filled: number, saved: number) => {
    const empty = Math.max(0, saved - filled)
    if (empty > 0) {
      toast.success(
        `Готово: ${filled} из ${saved} ячеек с ответом. ${empty} — в документе нет ответа на вопрос (N/A).`,
      )
      return
    }
    toast.success(`Колонка заполнена: ${filled} ответов по документам`)
  }, [])

  const startColumnPoll = useCallback(
    (columnId: string, expectedTasks: number) => {
      stopColumnPoll(columnId)
      const controller = startColumnExtractionPoll({
        columnId,
        expectedTasks,
        fetchTableData: refreshTableDataQuiet,
        onTableData: (data) => syncProcessingKeysFromTable(columnId, data),
        onComplete: async () => {
          if (wsCompletedColumnRef.current.has(columnId)) {
            stopColumnPoll(columnId)
            return
          }
          const data = await refreshTableDataQuiet()
          stopColumnPoll(columnId)
          finishColumnExtractionUi(columnId)
          setProcessing(false)
          if (data) {
            const resolved = countResolvedColumnCells(data, columnId)
            showColumnExtractionSuccessToast(resolved, resolved)
          } else {
            toast.success("Колонка заполнена")
          }
        },
        onTimeout: () => {
          stopColumnPoll(columnId)
          finishColumnExtractionUi(columnId)
          setProcessing(false)
          toast.error("Превышено время ожидания заполнения колонки")
        },
      })
      columnPollControllersRef.current.set(columnId, controller)
    },
    [
      finishColumnExtractionUi,
      refreshTableDataQuiet,
      showColumnExtractionSuccessToast,
      stopColumnPoll,
      syncProcessingKeysFromTable,
    ],
  )

  const handleColumnExtractionCompleted = useCallback(
    async (data: {
      column_id: string
      status: string
      saved_count?: number
      filled_count?: number
      error_count?: number
      message?: string
    }) => {
      wsCompletedColumnRef.current.add(data.column_id)
      stopColumnPoll(data.column_id)
      await refreshTableDataQuiet()
      finishColumnExtractionUi(data.column_id)
      setProcessing(false)
      if (data.status === "completed") {
        const filled = data.filled_count ?? data.saved_count ?? 0
        const saved = data.saved_count ?? filled
        showColumnExtractionSuccessToast(filled, saved)
      } else if (data.status === "failed") {
        toast.error(data.message || "Ошибка при заполнении колонки")
      }
      window.setTimeout(() => {
        wsCompletedColumnRef.current.delete(data.column_id)
      }, 2000)
    },
    [
      finishColumnExtractionUi,
      refreshTableDataQuiet,
      showColumnExtractionSuccessToast,
      stopColumnPoll,
    ],
  )

  useTabularReviewWebSocket({
    reviewId: reviewId ?? null,
    enabled: Boolean(reviewId),
    onCellUpdated: handleRealtimeCellUpdated,
    onExtractionCellFinished: handleRealtimeExtractionCellFinished,
    onColumnExtractionCompleted: handleColumnExtractionCompleted,
    onColumnDeleted: handleRealtimeColumnDeleted,
  })

  useEffect(() => {
    return () => {
      columnPollControllersRef.current.forEach((controller) => controller.stop())
      columnPollControllersRef.current.clear()
    }
  }, [])

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
      const created = await tabularReviewApi.addColumn(
        reviewId,
        column.column_label,
        column.column_type,
        column.prompt,
        column.column_config
      )
      toast.success("Колонка добавлена")
      setTableData((prev) => {
        if (!prev) return prev
        const newCol: TabularColumn = {
          id: created.id,
          column_label: created.column_label,
          column_type: created.column_type,
          prompt: created.prompt,
          column_config: created.column_config,
          order_index: created.order_index ?? prev.columns.length,
        }
        return appendColumnsToTableData(prev, [newCol])
      })
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
    if (!reviewId || !tableData) return

    const column = tableData.columns.find((c) => c.id === columnId)
    if (!column) return

    if (runningColumnIds.has(columnId)) {
      toast.error("Дождитесь завершения заполнения колонки перед удалением")
      return
    }

    if (
      !confirm(
        `Удалить колонку «${column.column_label}»? Ячейки и комментарии к ней будут удалены без возможности восстановления.`,
      )
    ) {
      return
    }

    try {
      await tabularReviewApi.deleteColumn(reviewId, columnId)
      setTableData((prev) => (prev ? removeColumnFromTableData(prev, columnId) : prev))
      if (editingColumn?.id === columnId) {
        setEditingColumn(null)
        setEditColumnAnchorEl(null)
      }
      finishColumnExtractionUi(columnId)
      toast.success(`Колонка «${column.column_label}» удалена`)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Не удалось удалить колонку"
      toast.error(message)
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
          column_type: column.column_type,
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
                onClick={navigateBackToConversation}
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

  if (!reviewId && caseId) {
    return (
      <div className="h-screen bg-bg-primary flex">
        <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} />
        <div className="flex-1 flex items-center justify-center">
          {loadingReviews && <Spinner size="lg" />}
        </div>
        <CaseTabularHubModal
          open
          onClose={() => navigate(`/cases/${caseId}`)}
          caseId={caseId}
          files={caseFilesForHub}
          reviews={existingReviews}
          loadingReviews={loadingReviews}
          onReviewOpen={(id) =>
            navigate(`/cases/${caseId}/tabular-review/${id}`, { replace: true })
          }
          onReviewsChanged={reloadReviews}
        />
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
                    onClick={navigateBackToConversation}
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
                onClick={navigateBackToConversation}
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
      <div className="flex flex-col h-full flex-1 min-h-0 overflow-hidden bg-bg-primary">
        {/* Header */}
        <div className="border-b border-border px-6 pt-5 pb-5" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
          {/* Breadcrumb */}
          <div className="flex items-center gap-1.5 text-sm mb-3" style={{ color: 'var(--color-text-muted)' }}>
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
                  <>
                    <input
                      autoFocus
                      value={editNameValue}
                      onChange={(e) => setEditNameValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') { e.preventDefault(); handleSaveRename() }
                        if (e.key === 'Escape') setIsEditingName(false)
                      }}
                      className="text-2xl font-semibold tracking-tight bg-transparent border-b-2 outline-none"
                      style={{ color: 'var(--color-text-primary)', borderColor: 'var(--color-accent)', minWidth: 200 }}
                    />
                    <button
                      onMouseDown={(e) => { e.preventDefault(); handleSaveRename() }}
                      className="p-1.5 rounded-md transition-colors"
                      style={{ color: 'white', backgroundColor: 'var(--color-accent)' }}
                      title="Сохранить (Enter)"
                    >
                      <Check className="w-4 h-4" />
                    </button>
                    <button
                      onMouseDown={(e) => { e.preventDefault(); setIsEditingName(false) }}
                      className="p-1.5 rounded-md transition-colors hover:bg-[var(--color-bg-hover)]"
                      style={{ color: 'var(--color-text-muted)' }}
                      title="Отмена (Esc)"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </>
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
          onOpenHelp={() => setShowHelpPanel(true)}
          onToggleChat={() => setShowTableChat((v) => !v)}
          chatOpen={showTableChat}
          onOpenFilter={(el) => {
            setFilterAnchorEl(el)
            setFilterPopoverOpen(true)
          }}
          onUpdateDocuments={reviewId ? () => setShowDocumentSelector(true) : undefined}
          onAddColumns={() => setShowTableAddColumn(true)}
          onExport={reviewId ? () => setShowExportDialog(true) : undefined}
          processing={processing}
        />

        <TabularReviewHelpPanel
          open={showHelpPanel}
          onClose={() => setShowHelpPanel(false)}
        />

        {/* Main Content Area */}
        <div
          className="flex-1 min-h-0 overflow-hidden"
          style={{
            display: 'grid',
            gridTemplateColumns: showTableChat && reviewId && tableData ? 'minmax(0, 1fr) 380px' : 'minmax(0, 1fr)',
          }}
        >
          <div className="min-h-0 overflow-hidden flex flex-col">
            <div className="overflow-hidden p-6 flex-1 bg-bg-primary min-h-0 flex flex-col">
              {tableData.columns.length === 0 && (
                <div
                  className="mb-4 rounded-xl border p-5 shrink-0"
                  style={{
                    borderColor: 'var(--color-border)',
                    backgroundColor: 'var(--color-bg-elevated)',
                  }}
                >
                  <h3
                    className="text-sm font-semibold mb-1"
                    style={{ color: 'var(--color-text-primary)' }}
                  >
                    Добавьте первую колонку
                  </h3>
                  <p className="text-sm mb-4" style={{ color: 'var(--color-text-muted)' }}>
                    Колонка — один вопрос ко всем документам. После создания нажмите ▶ у заголовка,
                    чтобы ИИ заполнил ячейки. Или возьмите готовый шаблон для банкротства.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => setShowTableAddColumn(true)}
                      className="px-4 py-2 text-sm font-medium rounded-lg"
                      style={{
                        backgroundColor: 'var(--color-text-primary)',
                        color: 'var(--color-bg-primary)',
                      }}
                    >
                      Добавить колонку
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowTemplatesModal(true)}
                      className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg border"
                      style={{
                        borderColor: 'var(--color-border)',
                        color: 'var(--color-text-primary)',
                        backgroundColor: 'var(--color-bg-primary)',
                      }}
                    >
                      <LayoutTemplate className="w-4 h-4" />
                      Готовые шаблоны
                    </button>
                  </div>
                </div>
              )}
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
                  onCellClick={async (fileId, columnId, cellData: TabularCellClickPayload) => {
                    const row = tableData.rows.find(r => r.file_id === fileId)
                    const clickedColumn = tableData.columns.find(col => col.id === columnId)

                    // Popover уже загрузил details; повторный fetch только если refs не переданы
                    let details = null
                    if (
                      reviewId &&
                      clickedColumn &&
                      !(cellData.sourceReferences && cellData.sourceReferences.length > 0)
                    ) {
                      setLoadingCellDetails(true)
                      try {
                        details = await tabularReviewApi.getCellDetails(
                          reviewId,
                          fileId,
                          clickedColumn.id,
                        )
                      } catch (err) {
                        console.error("Error loading cell details:", err)
                      } finally {
                        setLoadingCellDetails(false)
                      }
                    }

                    const finalCellData = buildTabularViewerCellData({
                      details,
                      click: cellData,
                      fileId,
                    })

                    setSelectedDocument({
                      fileId,
                      fileType: row?.file_type || undefined,
                      fileName: row?.file_name || undefined,
                      sourceReferenceIndex: cellData.sourceReferenceIndex ?? 0,
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
                    const fileIds = tableData?.rows.map((r) => r.file_id) ?? []
                    setProcessing(true)
                    beginColumnExtractionUi(columnId, fileIds)
                    try {
                      const result = await tabularReviewApi.runColumnExtraction(reviewId, columnId)
                      if (result.status === "started") {
                        toast.info(
                          `Заполнение колонки: ${result.total_tasks} документов (до 5 параллельно)`,
                        )
                        startColumnPoll(columnId, result.total_tasks)
                        return
                      }
                      if (result.status === "skipped") {
                        finishColumnExtractionUi(columnId)
                        setProcessing(false)
                        return
                      }
                      const filled = result.filled_count ?? result.saved_count ?? 0
                      const saved = result.saved_count ?? filled
                      const pending = Math.max(0, saved - filled)
                      toast.success(
                        pending > 0
                          ? `Колонка заполнена: ${filled} ответов, ${pending} требуют проверки`
                          : `Колонка заполнена: ${filled} ответов`,
                      )
                      if (result.cells?.length) {
                        setTableData((prev) =>
                          prev ? applyColumnCellsToTableData(prev, columnId, result.cells!) : prev,
                        )
                      }
                      finishColumnExtractionUi(columnId)
                      setProcessing(false)
                    } catch (err: any) {
                      const msg = err.message || ""
                      if (msg.includes("409") || msg.toLowerCase().includes("already in progress")) {
                        toast.error("Колонка уже заполняется")
                      } else {
                        toast.error("Ошибка при заполнении колонки: " + msg)
                      }
                      finishColumnExtractionUi(columnId)
                      setProcessing(false)
                    }
                  }}
                  runningColumnIds={runningColumnIds}
                  processingCellKeys={processingCellKeys}
                />
            </div>
          </div>

          {showTableChat && reviewId && tableData && (
            <aside
              className="min-h-0 h-full border-l flex flex-col overflow-hidden shadow-sm"
              style={{
                borderColor: 'var(--color-border)',
                backgroundColor: 'var(--color-bg-elevated)',
              }}
            >
              <TabularReviewContextChat
                reviewId={reviewId}
                reviewName={tableData.review.name}
              />
            </aside>
          )}
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
                  key={`${selectedDocument.fileId}:${selectedDocument.sourceReferenceIndex ?? 0}:${selectedDocument.cellData.verbatimExtract?.slice(0, 40) ?? ''}`}
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

        {showTableAddColumn && reviewId && (
          <ColumnBuilder
            isOpen
            mode="modal"
            onClose={() => setShowTableAddColumn(false)}
            onSave={async (column) => {
              await handleAddColumn(column)
              setShowTableAddColumn(false)
            }}
          />
        )}

        {/* Edit column: single-column wizard (2-step, anchored to column header) */}
        {editingColumn != null && (
          <ColumnBuilder
            isOpen={true}
            onClose={() => {
              setEditingColumn(null)
              setEditColumnAnchorEl(null)
            }}
            onSave={async (column) => {
              await handleUpdateColumn(column)
              setEditColumnAnchorEl(null)
            }}
            editingColumn={editingColumn}
            anchorEl={editColumnAnchorEl}
            mode="popover"
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
              let fileIds: string[] = []
              setTableData((prev) => {
                if (!prev) {
                  return prev
                }
                const next = appendColumnsToTableData(prev, columns)
                fileIds = next.rows.map((r) => r.file_id)
                return next
              })
              const aiColumns = columns.filter((c) => c.column_type !== 'manual_input')
              if (aiColumns.length === 0) return
              for (const col of aiColumns) {
                beginColumnExtractionUi(col.id, fileIds)
              }
              await Promise.allSettled(
                aiColumns.map(async (col) => {
                  try {
                    const result = await tabularReviewApi.runColumnExtraction(reviewId, col.id)
                    if (result.status === "started") {
                      startColumnPoll(col.id, result.total_tasks)
                      return
                    }
                    if (result.cells?.length) {
                      setTableData((prev) =>
                        prev ? applyColumnCellsToTableData(prev, col.id, result.cells!) : prev,
                      )
                    }
                    finishColumnExtractionUi(col.id)
                  } catch {
                    finishColumnExtractionUi(col.id)
                  }
                }),
              )
            }}
            initialQuestionsText={bulkBuilderInitialPrompt}
          />
        )}

        {/* Document Selector Modal */}
        {caseId && (
          <DocumentSelector
            isOpen={showDocumentSelector}
            onClose={() => setShowDocumentSelector(false)}
            onConfirm={handleUpdateDocuments}
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

