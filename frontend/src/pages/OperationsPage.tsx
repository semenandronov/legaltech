import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import UnifiedSidebar from '@/components/Layout/UnifiedSidebar'
import { OperationsHeader } from '@/components/Operations/OperationsHeader'
import { OperationsTable } from '@/components/Operations/OperationsTable'
import { OperationsContextChat } from '@/components/Operations/OperationsContextChat'
import { OperationsSidePanel } from '@/components/Operations/OperationsSidePanel'
import { CaseOperationsHubModal } from '@/components/Operations/CaseOperationsHubModal'
import { OperationsExportDialog } from '@/components/Operations/OperationsExportDialog'
import { OperationsHelpPanel } from '@/components/Operations/OperationsHelpPanel'
import { FilterPopover } from '@/components/TabularReview/FilterPopover'
import type { ColumnValueFilterCondition } from '@/components/TabularReview/AdvancedFiltersPanel'
import {
  operationsApi,
  formatOperationsError,
  type OperationTransaction,
  type OperationsAvailableFile,
  type OperationsSessionSummary,
  type OperationsSummary,
} from '@/services/operationsApi'
import { getCase } from '@/services/api'
import { buildMainNavItems } from '@/lib/mainNavItems'
import {
  buildOperationsTabularColumns,
  buildOperationsTabularRows,
  filterOperationsBySearch,
  filterOperationsRows,
} from '@/utils/operationsTableModel'
import { Card } from '@/components/UI/Card'
import Spinner from '@/components/UI/Spinner'
import { toast } from 'sonner'

function parseFileIdFromSearch(searchParams: URLSearchParams): string | null {
  const direct = searchParams.get('file')?.trim()
  if (direct) return direct

  const legacy = searchParams.get('files')?.trim()
  if (!legacy) return null
  const first = legacy.split(',')[0]?.trim()
  return first || null
}

const OperationsPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const [caseName, setCaseName] = useState('')
  const [availableFiles, setAvailableFiles] = useState<OperationsAvailableFile[]>([])
  const [loadingFiles, setLoadingFiles] = useState(true)
  const [loadingTransactions, setLoadingTransactions] = useState(false)
  const [transactions, setTransactions] = useState<OperationTransaction[]>([])
  const [summary, setSummary] = useState<OperationsSummary | null>(null)
  const [columnHeaders, setColumnHeaders] = useState<string[]>([])
  const [selectedFileId, setSelectedFileId] = useState<string | null>(() =>
    parseFileIdFromSearch(searchParams),
  )
  const [showHub, setShowHub] = useState(false)
  const [hubInitialStep, setHubInitialStep] = useState<'list' | 'pick'>('list')
  const [sessions, setSessions] = useState<OperationsSessionSummary[]>([])
  const [loadingSessions, setLoadingSessions] = useState(true)
  const [rowSearch, setRowSearch] = useState('')
  const [valueFilters, setValueFilters] = useState<ColumnValueFilterCondition[]>([])
  const [filterPopoverOpen, setFilterPopoverOpen] = useState(false)
  const [filterAnchorEl, setFilterAnchorEl] = useState<HTMLElement | null>(null)
  const [showChat, setShowChat] = useState(true)
  const [showExport, setShowExport] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const [selectedTransaction, setSelectedTransaction] = useState<OperationTransaction | null>(null)
  const sessionReadyRef = useRef(false)

  const navItems = buildMainNavItems()

  const selectedFile = useMemo(
    () => availableFiles.find((f) => f.file_id === selectedFileId) ?? null,
    [availableFiles, selectedFileId],
  )

  const statementName =
    selectedFile?.filename || transactions[0]?.source_filename || 'Выписка'

  const columns = useMemo(
    () => buildOperationsTabularColumns(columnHeaders),
    [columnHeaders],
  )

  const tabularRows = useMemo(
    () => buildOperationsTabularRows(transactions, columns, columnHeaders),
    [transactions, columns, columnHeaders],
  )

  const filteredRows = useMemo(() => {
    let rows = tabularRows
    rows = filterOperationsRows(rows, valueFilters, columns)
    rows = filterOperationsBySearch(rows, rowSearch)
    return rows
  }, [tabularRows, valueFilters, rowSearch, columns])

  const syncUrl = useCallback(
    (fileId: string | null) => {
      if (!caseId) return
      if (!fileId) {
        setSearchParams({}, { replace: true })
        return
      }
      setSearchParams({ file: fileId }, { replace: true })
    },
    [caseId, setSearchParams],
  )

  const loadSessions = useCallback(async () => {
    if (!caseId) return
    setLoadingSessions(true)
    try {
      const list = await operationsApi.listSessions(caseId)
      setSessions(list)
    } catch {
      setSessions([])
    } finally {
      setLoadingSessions(false)
    }
  }, [caseId])

  const openHub = useCallback(
    (step: 'list' | 'pick' = 'list') => {
      setHubInitialStep(step)
      setShowHub(true)
      void loadSessions()
    },
    [loadSessions],
  )

  const loadAvailableFiles = useCallback(async () => {
    if (!caseId) return
    setLoadingFiles(true)
    try {
      const files = await operationsApi.listAvailableFiles(caseId)
      setAvailableFiles(files)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Не удалось загрузить выписки'
      toast.error(message)
      setAvailableFiles([])
    } finally {
      setLoadingFiles(false)
    }
  }, [caseId])

  const loadTransactions = useCallback(async () => {
    if (!caseId || !selectedFileId) {
      setTransactions([])
      setSummary(null)
      setColumnHeaders([])
      sessionReadyRef.current = false
      return
    }
    setLoadingTransactions(true)
    sessionReadyRef.current = false
    try {
      const [data, session] = await Promise.all([
        operationsApi.listTransactions(caseId, { fileId: selectedFileId }),
        operationsApi.getSession(caseId, selectedFileId).catch(() => ({
          valueFilters: [] as ColumnValueFilterCondition[],
          rowSearch: '',
        })),
      ])
      setTransactions(data.transactions)
      setSummary(data.summary)
      setColumnHeaders(data.column_headers)
      setValueFilters(session.valueFilters)
      setRowSearch(session.rowSearch)
      const name =
        availableFiles.find((f) => f.file_id === selectedFileId)?.filename ??
        data.transactions[0]?.source_filename
      void operationsApi.touchSession(caseId, selectedFileId, name ?? undefined)
    } catch (err: unknown) {
      const message = formatOperationsError(err)
      toast.error(message)
      setTransactions([])
      setSummary(null)
    } finally {
      setLoadingTransactions(false)
      sessionReadyRef.current = true
    }
  }, [caseId, selectedFileId, availableFiles])

  useEffect(() => {
    if (!caseId) return
    getCase(caseId)
      .then((c) => setCaseName(c.title || ''))
      .catch(() => {})
    loadAvailableFiles()
    loadSessions()
  }, [caseId, loadAvailableFiles, loadSessions])

  useEffect(() => {
    const fromUrl = parseFileIdFromSearch(searchParams)
    if (fromUrl !== selectedFileId) {
      setSelectedFileId(fromUrl)
    }
  }, [searchParams]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (loadingFiles) return
    if (!selectedFileId) {
      setHubInitialStep('list')
      setShowHub(true)
      return
    }
    setShowHub(false)
    const exists = availableFiles.some((f) => f.file_id === selectedFileId)
    if (!exists && availableFiles.length > 0) {
      toast.error('Выписка не найдена или ещё не оцифрована')
      setSelectedFileId(null)
      syncUrl(null)
      setHubInitialStep('list')
      setShowHub(true)
      return
    }
    void loadTransactions()
  }, [selectedFileId, loadingFiles, availableFiles, loadTransactions, syncUrl])

  useEffect(() => {
    if (!caseId || !selectedFileId || !sessionReadyRef.current) return
    const timer = window.setTimeout(() => {
      const name =
        availableFiles.find((f) => f.file_id === selectedFileId)?.filename ?? statementName
      void operationsApi.saveSession(
        caseId,
        selectedFileId,
        { valueFilters, rowSearch },
        name,
      )
    }, 400)
    return () => window.clearTimeout(timer)
  }, [caseId, selectedFileId, valueFilters, rowSearch, availableFiles, statementName])

  const handleOpenFile = (fileId: string) => {
    setSelectedFileId(fileId)
    syncUrl(fileId)
    setShowHub(false)
    setSelectedTransaction(null)
    if (caseId) {
      const name = availableFiles.find((f) => f.file_id === fileId)?.filename
      void operationsApi.touchSession(caseId, fileId, name)
    }
  }

  const mainGridColumns = useMemo(() => {
    const parts = ['minmax(0, 1fr)']
    if (selectedTransaction) {
      parts.push('minmax(300px, min(42%, 900px))')
    } else if (showChat) {
      parts.push('380px')
    }
    return parts.join(' ')
  }, [showChat, selectedTransaction])

  if (!caseId) {
    return (
      <div className="ws-shell h-screen flex items-center justify-center">
        <Card className="p-6">Case ID не найден</Card>
      </div>
    )
  }

  if (loadingFiles && availableFiles.length === 0 && !selectedFileId) {
    return (
      <div className="ws-shell ws-tabular-shell flex h-screen">
        <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} variant="tabular" />
        <div className="flex-1 flex items-center justify-center">
          <Spinner />
        </div>
      </div>
    )
  }

  const hasRegistry = Boolean(selectedFileId)

  return (
    <div className="ws-shell ws-tabular-shell flex h-screen overflow-hidden">
      <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton={false} variant="tabular" />
      <div className="ws-tabular-page flex min-h-0 flex-1 flex-col overflow-hidden">
        {hasRegistry && (
          <>
            <OperationsHeader
              caseName={caseName}
              statementName={statementName}
              operationCount={summary?.total ?? transactions.length}
              showChat={showChat && !selectedTransaction}
              rowSearch={rowSearch}
              activeFilterCount={valueFilters.length}
              onRowSearchChange={setRowSearch}
              onNavigateCases={() => navigate('/cases')}
              onNavigateCase={() => navigate(`/cases/${caseId}`)}
              onToggleChat={() => {
                setShowChat((v) => !v)
                setSelectedTransaction(null)
              }}
              onExport={() => setShowExport(true)}
              onOpenHelp={() => setShowHelp(true)}
              onOpenFilter={(el) => {
                setFilterAnchorEl(el)
                setFilterPopoverOpen(true)
              }}
            />

            {summary && (
              <div className="px-4 py-2 border-b border-gray-100 text-xs text-gray-600 flex flex-wrap gap-x-4 gap-y-1 shrink-0">
                <span>Операций: {summary.total}</span>
                {summary.date_min && summary.date_max ? (
                  <span>
                    Период: {summary.date_min} — {summary.date_max}
                  </span>
                ) : null}
              </div>
            )}
          </>
        )}

        <div className="ws-tabular-body flex-1 min-h-0" style={{ display: 'grid', gridTemplateColumns: mainGridColumns }}>
          <div className="ws-tabular-surface min-h-0 flex flex-col overflow-hidden">
            {hasRegistry ? (
              <OperationsTable
                columns={columns}
                rows={filteredRows}
                loading={loadingTransactions}
                selectedRowId={selectedTransaction?.id ?? null}
                onRowClick={(tx) => {
                  setSelectedTransaction(tx)
                  setShowChat(false)
                }}
                emptyMessage={
                  loadingTransactions
                    ? 'Загрузка…'
                    : 'Нет операций. Проверьте фильтры.'
                }
              />
            ) : (
              <div className="flex-1 flex items-center justify-center p-8">
                <Card className="p-8 max-w-md text-center space-y-4">
                  <h2 className="text-lg font-semibold">Реестр операций</h2>
                  <p className="text-sm text-gray-600">
                    Выберите одну банковскую выписку — операции отобразятся в таблице с колонками как в PDF.
                  </p>
                  <button
                    type="button"
                    onClick={() => openHub('list')}
                    className="px-4 py-2 rounded-lg bg-gray-900 text-white text-sm"
                  >
                    Выбрать выписку
                  </button>
                </Card>
              </div>
            )}
          </div>

          {selectedTransaction ? (
            <OperationsSidePanel
              caseId={caseId}
              transaction={selectedTransaction}
              fileName={statementName}
              onClose={() => setSelectedTransaction(null)}
            />
          ) : showChat && hasRegistry && selectedFileId ? (
            <aside className="ws-tabular-aside">
              <OperationsContextChat
                caseId={caseId}
                fileId={selectedFileId}
                reviewName={statementName}
                uiState={{ valueFilters, rowSearch }}
                onClose={() => setShowChat(false)}
              />
            </aside>
          ) : null}
        </div>
      </div>

      <CaseOperationsHubModal
        open={showHub}
        onClose={() => {
          if (!selectedFileId) {
            navigate(`/cases/${caseId}`)
            return
          }
          setShowHub(false)
        }}
        sessions={sessions}
        loadingSessions={loadingSessions}
        files={availableFiles}
        loadingFiles={loadingFiles}
        initialStep={hubInitialStep}
        onOpenFile={handleOpenFile}
      />

      <FilterPopover
        open={filterPopoverOpen}
        anchorEl={filterAnchorEl}
        onClose={() => setFilterPopoverOpen(false)}
        columns={columns}
        rows={tabularRows}
        valueFilters={valueFilters}
        onApply={setValueFilters}
      />

      <OperationsExportDialog
        open={showExport}
        onClose={() => setShowExport(false)}
        caseId={caseId}
        caseTitle={statementName || caseName || 'operations'}
        fileId={selectedFileId || ''}
        transactionIds={filteredRows.map((row) => {
          const tx = (row as { _transaction?: { id?: string } })._transaction
          return String(tx?.id || row.file_id || '')
        }).filter(Boolean)}
        totalInStatement={transactions.length}
      />

      <OperationsHelpPanel open={showHelp} onClose={() => setShowHelp(false)} />
    </div>
  )
}

export default OperationsPage
