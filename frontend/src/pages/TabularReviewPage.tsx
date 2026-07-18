import React, { useState, useEffect, useRef, useCallback, useMemo } from "react"
import { useParams, useNavigate, useSearchParams } from "react-router-dom"
import UnifiedSidebar from "../components/Layout/UnifiedSidebar"
import { TabularReviewTable } from "../components/TabularReview/TabularReviewTable"
import { TabularReviewToolbar } from "../components/TabularReview/TabularReviewToolbar"
import { TabularReviewHeader } from "../components/TabularReview/TabularReviewHeader"
import type { TabularColumnSavePayload } from "../components/TabularReview/TabularEditColumnMenu.types"
import { MikeAddColumnModal } from "../components/TabularReview/mike/MikeAddColumnModal"
import type { MikeColumnSavePayload } from "../components/TabularReview/mike/MikeAddColumnModal"
import { BulkColumnBuilder } from "../components/TabularReview/BulkColumnBuilder"
import { MikeAddDocumentsModal } from "../components/TabularReview/mike/MikeAddDocumentsModal"
import { TemplatesModal } from "../components/TabularReview/TemplatesModal"
import { CaseTabularHubModal } from "../components/TabularReview/CaseTabularHubModal"
import { TabularReviewHelpPanel } from "../components/TabularReview/TabularReviewHelpPanel"
import { TabularReviewContextChat } from "../components/TabularReview/TabularReviewContextChat"
import { TabularSidePanel } from "../components/TabularReview/TabularSidePanel"
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
import { buildMainNavItems } from "@/lib/mainNavItems"
import { caseHomePath } from "@/lib/productFeatures"
import { Card } from "../components/UI/Card"
import Spinner from "../components/UI/Spinner"
import { toast } from "sonner"

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
        navigate(caseHomePath(caseId!))
      }
    } else {
      navigate(caseHomePath(caseId!))
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
  const [editingColumnId, setEditingColumnId] = useState<string | null>(null)
  const [bulkBuilderInitialPrompt, setBulkBuilderInitialPrompt] = useState<string | undefined>(undefined)
  const [filterPopoverOpen, setFilterPopoverOpen] = useState(false)
  const [filterAnchorEl, setFilterAnchorEl] = useState<HTMLElement | null>(null)
  const [showDocumentSelector, setShowDocumentSelector] = useState(false)
  const [showTemplatesModal, setShowTemplatesModal] = useState(false)
  const [showExportDialog, setShowExportDialog] = useState(false)
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([])
  const [selectedDocument, setSelectedDocument] = useState<{
    fileId: string
    fileType?: string
    fileName?: string
    columnId?: string
    columnLabel?: string
    reasoning?: string | null
    confidence?: number | null
    sourceReferenceIndex?: number
    hideDetailPanel?: boolean
    cellData: ReturnType<typeof buildTabularViewerCellData>
  } | null>(null)
  const [_loadingCellDetails, setLoadingCellDetails] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const loadingRef = useRef(false)
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
  const [documentSearch, setDocumentSearch] = useState('')
  const [selectedTableDocIds, setSelectedTableDocIds] = useState<string[]>([])
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
    setTableData((prev) => (prev ? removeColumnFromTableData(prev, columnId) : prev))
    finishColumnExtractionUi(columnId)
  }, [finishColumnExtractionUi])

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

  const handleAddColumns = async (columns: MikeColumnSavePayload[]) => {
    for (const column of columns) {
      await handleAddColumn(column)
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

  const handleColumnSave = async (columnId: string, payload: TabularColumnSavePayload) => {
    if (!reviewId) return
    try {
      await tabularReviewApi.updateColumn(reviewId, columnId, payload)
      toast.success('Колонка обновлена')
      await loadReviewData()
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Не удалось обновить колонку'
      toast.error(message)
      throw err
    }
  }

  const handleColumnDelete = async (columnId: string): Promise<boolean> => {
    if (!reviewId || !tableData) return false

    const column = tableData.columns.find((c) => c.id === columnId)
    if (!column) return false

    if (runningColumnIds.has(columnId)) {
      toast.error("Дождитесь завершения заполнения колонки перед удалением")
      return false
    }

    if (
      !confirm(
        `Удалить колонку «${column.column_label}»? Ячейки и комментарии к ней будут удалены без возможности восстановления.`,
      )
    ) {
      return false
    }

    try {
      await tabularReviewApi.deleteColumn(reviewId, columnId)
      setTableData((prev) => (prev ? removeColumnFromTableData(prev, columnId) : prev))
      finishColumnExtractionUi(columnId)
      toast.success(`Колонка «${column.column_label}» удалена`)
      return true
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Не удалось удалить колонку"
      toast.error(message)
      return false
    }
  }

  const editingColumn = useMemo(
    () => tableData?.columns.find((column) => column.id === editingColumnId) ?? null,
    [tableData?.columns, editingColumnId],
  )

  const closeColumnModal = () => {
    setShowTableAddColumn(false)
    setEditingColumnId(null)
  }

  const navItems = useMemo(() => buildMainNavItems(), [])

  const columnIds = useMemo(
    () => tableData?.columns.map((col) => col.id) ?? [],
    [tableData?.columns],
  )

  const mainGridColumns = useMemo(() => {
    const cols = ['minmax(0, 1fr)']
    if (selectedDocument) cols.push('minmax(300px, min(42%, 900px))')
    else if (showTableChat && reviewId && tableData) cols.push('380px')
    return cols.join(' ')
  }, [selectedDocument, showTableChat, reviewId, tableData])

  const handleNavigateSidePanelColumn = useCallback(
    async (columnId: string) => {
      if (!selectedDocument || !reviewId || !tableData) return
      const row = tableData.rows.find((r) => r.file_id === selectedDocument.fileId)
      const column = tableData.columns.find((col) => col.id === columnId)
      if (!row || !column) return

      const cell = row.cells?.[columnId]
      let details = null
      try {
        details = await tabularReviewApi.getCellDetails(reviewId, selectedDocument.fileId, columnId)
      } catch (err) {
        console.error('Error loading cell details:', err)
      }

      const clickPayload: TabularCellClickPayload = {
        verbatimExtract: cell?.verbatim_extract ?? details?.verbatim_extract ?? null,
        sourcePage: cell?.source_page ?? details?.source_page ?? null,
        sourceSection: cell?.source_section ?? details?.source_section ?? null,
        columnType: column.column_type,
        sourceReferences: cell?.source_references,
      }

      setSelectedDocument({
        fileId: selectedDocument.fileId,
        fileType: row.file_type || undefined,
        fileName: row.file_name || undefined,
        columnId,
        columnLabel: column.column_label,
        reasoning: details?.reasoning ?? cell?.reasoning ?? null,
        confidence: details?.confidence_score ?? cell?.confidence_score ?? null,
        sourceReferenceIndex: 0,
        hideDetailPanel: selectedDocument.hideDetailPanel,
        cellData: buildTabularViewerCellData({
          details,
          click: clickPayload,
          fileId: selectedDocument.fileId,
        }),
      })
    },
    [reviewId, selectedDocument, tableData],
  )

  if (loading && !tableData) {
    return (
      <div className="ws-shell h-screen flex">
        <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} />
        <div className="flex-1 flex items-center justify-center">
          <Spinner size="lg" />
        </div>
      </div>
    )
  }

  if (error && !tableData) {
    return (
      <div className="ws-shell h-screen flex">
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
      <div className="ws-shell h-screen flex">
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
        <div className="ws-shell h-screen flex">
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
        <div className="ws-shell h-screen flex">
          <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} />
          <div className="ws-main flex items-center justify-center p-6">
            <Card className="p-6 ws-card">
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
      <div className="ws-shell h-screen flex">
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
    <div className="ws-shell ws-tabular-shell flex">
      <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} variant="tabular" />
      <div className="ws-tabular-page">
        <TabularReviewHeader
          caseName={caseName}
          reviewName={tableData.review.name}
          processing={processing}
          showTableChat={showTableChat}
          isEditingName={isEditingName}
          editNameValue={editNameValue}
          documentSearch={documentSearch}
          onDocumentSearchChange={setDocumentSearch}
          onNavigateCases={() => navigate('/cases')}
          onNavigateCase={() => navigate(`/cases/${caseId}`)}
          onStartRename={handleStartRename}
          onSaveRename={handleSaveRename}
          onCancelRename={() => setIsEditingName(false)}
          onEditNameChange={setEditNameValue}
          onToggleChat={() => setShowTableChat((v) => !v)}
          onExport={() => setShowExportDialog(true)}
          onOpenHelp={() => setShowHelpPanel(true)}
          onOpenFilter={(el) => {
            setFilterAnchorEl(el)
            setFilterPopoverOpen(true)
          }}
        />

        <TabularReviewToolbar
          onUpdateDocuments={reviewId ? () => setShowDocumentSelector(true) : undefined}
          onAddColumns={() => setShowTableAddColumn(true)}
          processing={processing}
          selectedCount={selectedTableDocIds.length}
          onDeleteSelected={
            reviewId && selectedTableDocIds.length > 0
              ? async () => {
                  try {
                    const remaining = (tableData?.rows ?? [])
                      .map((row) => row.file_id)
                      .filter((id) => !selectedTableDocIds.includes(id))
                    await tabularReviewApi.updateSelectedFiles(reviewId, remaining)
                    setSelectedFileIds((prev) => prev.filter((id) => !selectedTableDocIds.includes(id)))
                    setSelectedTableDocIds([])
                    toast.success('Документы удалены из таблицы')
                    await loadReviewData()
                  } catch (err: unknown) {
                    const message = err instanceof Error ? err.message : 'Неизвестная ошибка'
                    toast.error('Не удалось удалить документы: ' + message)
                  }
                }
              : undefined
          }
        />

        <TabularReviewHelpPanel
          open={showHelpPanel}
          onClose={() => setShowHelpPanel(false)}
        />

        <div
          className="ws-tabular-body"
          style={{ display: 'grid', gridTemplateColumns: mainGridColumns }}
        >
          <div className="ws-tabular-surface">
            <div className="ws-tabular-table-wrap min-h-0 overflow-hidden flex flex-col flex-1">
              <TabularReviewTable
                  reviewId={reviewId}
                  tableData={tableData}
                  documentSearch={documentSearch}
                  selectedDocIds={selectedTableDocIds}
                  onSelectionChange={setSelectedTableDocIds}
                  filterPopoverOpen={filterPopoverOpen}
                  filterAnchorEl={filterAnchorEl}
                  onCloseFilterPopover={() => {
                    setFilterPopoverOpen(false)
                    setFilterAnchorEl(null)
                  }}
                  onAddColumnClick={() => setShowTableAddColumn(true)}
                  onAddDocumentsClick={reviewId ? () => setShowDocumentSelector(true) : undefined}
                  onOpenTemplatesClick={() => setShowTemplatesModal(true)}
                  onTableDataUpdate={(updater) => {
                    if (tableData) {
                      setTableData(updater(tableData))
                    }
                  }}
                  onCellSave={async (fileId, columnId, value) => {
                    await handleCellEditSave(fileId, columnId, value)
                  }}
                  onOpenEditColumn={setEditingColumnId}
                  onColumnDelete={handleColumnDelete}
                  onCellClick={async (fileId, columnId, cellData: TabularCellClickPayload) => {
                    const row = tableData.rows.find(r => r.file_id === fileId)
                    const clickedColumn = tableData.columns.find(col => col.id === columnId)
                    const rowCell = row?.cells?.[columnId]

                    // Popover уже загрузил details; повторный fetch только если refs не переданы
                    let details = null
                    if (
                      reviewId &&
                      clickedColumn &&
                      !(
                        (cellData.sourceReferences && cellData.sourceReferences.length > 0) ||
                        (rowCell?.source_references && rowCell.source_references.length > 0)
                      )
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
                      details: details ?? (rowCell ? {
                        id: `${fileId}:${columnId}`,
                        cell_value: rowCell.cell_value,
                        normalized_value: rowCell.normalized_value,
                        verbatim_extract: rowCell.verbatim_extract,
                        reasoning: rowCell.reasoning,
                        source_references: rowCell.source_references,
                        confidence_score: rowCell.confidence_score,
                        source_page: rowCell.source_page,
                        source_section: rowCell.source_section,
                        status: rowCell.status,
                        column_type: clickedColumn?.column_type,
                        primary_source_doc_id: rowCell.primary_source_doc_id,
                        primary_source_char_start: rowCell.primary_source_char_start,
                        primary_source_char_end: rowCell.primary_source_char_end,
                        verified_flag: rowCell.verified_flag,
                      } : null),
                      click: cellData,
                      fileId,
                    })

                    setSelectedDocument({
                      fileId,
                      fileType: row?.file_type || undefined,
                      fileName: row?.file_name || undefined,
                      columnId,
                      columnLabel: clickedColumn?.column_label,
                      reasoning: details?.reasoning ?? rowCell?.reasoning ?? null,
                      confidence: details?.confidence_score ?? rowCell?.confidence_score ?? null,
                      sourceReferenceIndex: cellData.sourceReferenceIndex ?? 0,
                      hideDetailPanel: cellData.hideDetailPanel ?? false,
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

          {showTableChat && reviewId && tableData && !selectedDocument && (
            <aside className="ws-tabular-aside">
              <TabularReviewContextChat
                reviewId={reviewId}
                reviewName={tableData.review.name}
                onClose={() => setShowTableChat(false)}
              />
            </aside>
          )}

          {selectedDocument && caseId && (
            <TabularSidePanel
              embedded
              selection={selectedDocument}
              caseId={caseId}
              columnIds={columnIds}
              onClose={() => setSelectedDocument(null)}
              onNavigateColumn={handleNavigateSidePanelColumn}
            />
          )}
        </div>

        {reviewId && (showTableAddColumn || editingColumnId) && (
          <MikeAddColumnModal
            open
            onClose={closeColumnModal}
            editingColumn={editingColumn}
            onAdd={handleAddColumns}
            onSave={handleColumnSave}
            onDelete={handleColumnDelete}
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
          <MikeAddDocumentsModal
            open={showDocumentSelector}
            onClose={() => setShowDocumentSelector(false)}
            onConfirm={handleUpdateDocuments}
            reviewId={reviewId || ""}
            caseId={caseId}
            initialSelectedIds={selectedFileIds}
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

      </div>
    </div>
  )
}

export default TabularReviewPage

