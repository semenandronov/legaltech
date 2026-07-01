import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft,
  BookmarkPlus,
  CheckCircle2,
  Circle,
  Clock,
  FileText,
  FolderOpen,
  Loader2,
  Play,
  Plus,
  Sparkles,
  Square,
  Trash2,
  X,
  XCircle,
} from 'lucide-react'
import { toast } from 'sonner'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { buildMainNavItems } from '@/lib/mainNavItems'
import { agentRunsEnabled } from '../lib/agentRunsPolicy'
import ThinkingBlock from '../components/Chat/ThinkingBlock'
import MessageContent from '../components/Chat/MessageContent'
import { AgentInterruptCard } from '../components/AgentRuns/AgentInterruptCard'
import { WorkflowArtifacts } from '../components/AgentRuns/WorkflowArtifacts'
import {
  applyAgentRunEvent,
  artifactsFromStoredRecord,
  createEmptyAgentRunSlice,
  type AgentRunMessageSlice,
} from '../lib/agentRunStream'
import { WORKFLOW_CATEGORY_LABELS, WORKFLOW_PRESETS } from '../lib/workflowPresets'
import { getCase, getCaseFiles, extractErrorMessage, type UploadedFile } from '../services/api'
import {
  createCaseWorkflow,
  deleteCaseWorkflow,
  listCaseWorkflows,
  type CaseWorkflow,
} from '../services/caseWorkflowsApi'
import {
  cancelAgentRun,
  createAgentRun,
  getAgentRun,
  listAgentRuns,
  resumeAgentRun,
  streamAgentRun,
  type AgentRunListItem,
  type AgentRunStatus,
} from '../services/agentRunsApi'

type SidebarTab = 'scenarios' | 'history'

const TERMINAL: AgentRunStatus[] = ['completed', 'failed', 'cancelled']

function statusLabel(status: AgentRunStatus): string {
  const map: Record<AgentRunStatus, string> = {
    pending: 'В очереди',
    running: 'Выполняется',
    waiting_for_user: 'Ожидает вас',
    completed: 'Готово',
    failed: 'Ошибка',
    cancelled: 'Отменён',
  }
  return map[status] ?? status
}

function statusColor(status: AgentRunStatus): string {
  if (status === 'completed') return 'var(--color-success)'
  if (status === 'failed' || status === 'cancelled') return 'var(--color-danger, #dc2626)'
  if (status === 'waiting_for_user') return 'var(--color-warning, #d97706)'
  return 'var(--color-accent-muted)'
}

function formatWhen(iso?: string | null): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('ru-RU', {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return ''
  }
}

function truncate(text: string, max: number): string {
  const t = text.trim()
  if (t.length <= max) return t
  return `${t.slice(0, max)}…`
}

function runSliceFromDetail(detail: Awaited<ReturnType<typeof getAgentRun>>): AgentRunMessageSlice {
  const todos = (detail.todos ?? []).map((t) => ({
    content: String(t.content ?? ''),
    status: String(t.status ?? 'pending'),
  }))
  const isTerminal = TERMINAL.includes(detail.status)
  return {
    content: detail.result_summary ?? detail.error_message ?? '',
    toolCalls: [],
    agentTodos: todos,
    artifacts: artifactsFromStoredRecord(detail.artifacts),
    agentInterrupt:
      detail.status === 'waiting_for_user'
        ? detail.artifacts?.interrupt ?? {}
        : null,
    agentRunId: detail.id,
    agentRunStatus: isTerminal
      ? detail.status === 'completed'
        ? 'completed'
        : 'failed'
      : detail.status === 'waiting_for_user'
        ? 'waiting_for_user'
        : 'running',
    errorMessage: detail.error_message ?? undefined,
  }
}

const CaseWorkflowsPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const runFromUrl = searchParams.get('run')

  const [caseTitle, setCaseTitle] = useState('')
  const [caseFiles, setCaseFiles] = useState<UploadedFile[]>([])
  const [savedWorkflows, setSavedWorkflows] = useState<CaseWorkflow[]>([])
  const [history, setHistory] = useState<AgentRunListItem[]>([])
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('scenarios')
  const [loadingMeta, setLoadingMeta] = useState(true)

  const [userTask, setUserTask] = useState('')
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([])
  const [filesOpen, setFilesOpen] = useState(false)

  const [activeRunId, setActiveRunId] = useState<string | null>(runFromUrl)
  const [liveSlice, setLiveSlice] = useState<AgentRunMessageSlice | null>(null)
  const [activeRunMeta, setActiveRunMeta] = useState<AgentRunListItem | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [showComposer, setShowComposer] = useState(!runFromUrl)

  const [saveOpen, setSaveOpen] = useState(false)
  const [saveTitle, setSaveTitle] = useState('')
  const [saving, setSaving] = useState(false)

  const abortRef = useRef<AbortController | null>(null)

  const navItems = useMemo(() => buildMainNavItems(), [])

  const refreshMeta = useCallback(async () => {
    if (!caseId) return
    const [caseRes, filesRes, workflows, runs] = await Promise.all([
      getCase(caseId),
      getCaseFiles(caseId),
      listCaseWorkflows(caseId).catch(() => [] as CaseWorkflow[]),
      listAgentRuns(caseId).catch(() => [] as AgentRunListItem[]),
    ])
    setCaseTitle(caseRes.title || 'Дело')
    setCaseFiles(filesRes.files ?? [])
    setSavedWorkflows(workflows)
    setHistory(runs)
  }, [caseId])

  useEffect(() => {
    if (!caseId) return
    setLoadingMeta(true)
    refreshMeta()
      .catch((e) => toast.error(extractErrorMessage(e)))
      .finally(() => setLoadingMeta(false))
  }, [caseId, refreshMeta])

  const attachStream = useCallback(
    async (runId: string, mode: 'start' | 'resume', resumeBody?: { approved: boolean }) => {
      abortRef.current?.abort()
      abortRef.current = new AbortController()
      setIsStreaming(true)
      let slice = createEmptyAgentRunSlice(runId)

      const onEvent = (event: Parameters<typeof applyAgentRunEvent>[1]) => {
        slice = applyAgentRunEvent(slice, event)
        setLiveSlice({ ...slice })
        const terminal =
          event.type === 'run_completed' ||
          event.type === 'run_failed' ||
          event.type === 'run_cancelled' ||
          event.type === 'error'
        if (terminal) {
          setIsStreaming(false)
          void refreshMeta()
        }
        if (event.type === 'interrupt') {
          setIsStreaming(false)
        }
      }

      try {
        if (mode === 'resume' && resumeBody) {
          await resumeAgentRun(runId, resumeBody, {
            signal: abortRef.current.signal,
            onEvent,
          })
        } else {
          await streamAgentRun(runId, {
            signal: abortRef.current.signal,
            onEvent,
          })
        }
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'AbortError') {
          toast.error(extractErrorMessage(err))
        }
        setIsStreaming(false)
      }
    },
    [refreshMeta],
  )

  const openRun = useCallback(
    async (runId: string, opts?: { stream?: boolean }) => {
      if (!caseId) return
      setActiveRunId(runId)
      setShowComposer(false)
      setSearchParams({ run: runId })
      setSidebarTab('history')

      try {
        const detail = await getAgentRun(runId)
        setActiveRunMeta({
          id: detail.id,
          case_id: detail.case_id,
          status: detail.status,
          user_task: detail.user_task,
          result_summary: detail.result_summary,
          error_message: detail.error_message,
          total_tool_calls: detail.total_tool_calls,
          created_at: detail.created_at,
          completed_at: detail.completed_at,
        })
        const slice = runSliceFromDetail(detail)
        setLiveSlice(slice)

        const shouldStream =
          opts?.stream ??
          !TERMINAL.includes(detail.status)
        if (shouldStream) {
          await attachStream(runId, 'start')
        }
      } catch (e) {
        toast.error(extractErrorMessage(e))
      }
    },
    [attachStream, caseId, setSearchParams],
  )

  useEffect(() => {
    if (runFromUrl && runFromUrl !== activeRunId && !loadingMeta) {
      void openRun(runFromUrl)
    }
  }, [runFromUrl, activeRunId, loadingMeta, openRun])

  useEffect(() => () => abortRef.current?.abort(), [])

  const handleStart = async () => {
    if (!caseId || !userTask.trim() || isStreaming) return
    try {
      const run = await createAgentRun({
        caseId,
        userTask: userTask.trim(),
        fileIds: selectedFileIds.length ? selectedFileIds : undefined,
      })
      setUserTask('')
      setShowComposer(false)
      await openRun(run.id, { stream: true })
      void refreshMeta()
    } catch (e) {
      toast.error(extractErrorMessage(e))
    }
  }

  const handleCancel = async () => {
    if (!activeRunId) return
    try {
      await cancelAgentRun(activeRunId)
      toast.message('Отмена запрошена')
    } catch (e) {
      toast.error(extractErrorMessage(e))
    }
  }

  const handleResume = async (approved: boolean) => {
    if (!activeRunId) return
    setLiveSlice((prev) => (prev ? { ...prev, agentInterrupt: null } : prev))
    await attachStream(activeRunId, 'resume', { approved })
  }

  const applyPreset = (task: string, fileIds?: string[]) => {
    setUserTask(task)
    if (fileIds?.length) setSelectedFileIds(fileIds)
    setShowComposer(true)
    setActiveRunId(null)
    setLiveSlice(null)
    setSearchParams({})
  }

  const handleSaveScenario = async () => {
    if (!caseId || !saveTitle.trim() || userTask.trim().length < 10) return
    setSaving(true)
    try {
      await createCaseWorkflow(caseId, {
        title: saveTitle.trim(),
        user_task: userTask.trim(),
        default_file_ids: selectedFileIds.length ? selectedFileIds : undefined,
      })
      toast.success('Сценарий сохранён')
      setSaveOpen(false)
      setSaveTitle('')
      await refreshMeta()
    } catch (e) {
      toast.error(extractErrorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  const toggleFile = (id: string) => {
    setSelectedFileIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  if (!agentRunsEnabled()) {
    return <Navigate to={caseId ? `/cases/${caseId}` : '/cases'} replace />
  }

  if (!caseId) {
    return <Navigate to="/cases" replace />
  }

  const activeStatus = activeRunMeta?.status
  const canCancel = Boolean(
    activeRunId && activeStatus && !TERMINAL.includes(activeStatus),
  )

  const showLivePanel = activeRunId && liveSlice && !showComposer

  return (
    <div
      className="h-screen flex overflow-hidden"
      style={{ backgroundColor: 'var(--color-bg-primary)' }}
    >
      <UnifiedSidebar navItems={navItems} title="Legal AI" showBackButton />

      <div className="flex-1 flex min-w-0 overflow-hidden">
        {/* Left: library + history */}
        <aside
          className="w-[300px] flex-shrink-0 flex flex-col border-r overflow-hidden"
          style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-elevated)' }}
        >
          <div className="px-4 pt-5 pb-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
            <div className="flex items-center gap-2 mb-1">
              <Sparkles className="w-4 h-4" style={{ color: 'var(--color-accent)' }} />
              <h1 className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                Workflows
              </h1>
            </div>
            <p className="text-xs leading-snug" style={{ color: 'var(--color-text-muted)' }}>
              {truncate(caseTitle, 48)}
            </p>
          </div>

          <div className="flex border-b" style={{ borderColor: 'var(--color-border)' }}>
            {(['scenarios', 'history'] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setSidebarTab(tab)}
                className="flex-1 py-2.5 text-xs font-medium transition-colors"
                style={{
                  color: sidebarTab === tab ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
                  borderBottom: sidebarTab === tab ? '2px solid var(--color-text-primary)' : '2px solid transparent',
                }}
              >
                {tab === 'scenarios' ? 'Сценарии' : 'История'}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {sidebarTab === 'scenarios' && (
              <>
                <button
                  type="button"
                  onClick={() => {
                    setShowComposer(true)
                    setActiveRunId(null)
                    setLiveSlice(null)
                    setSearchParams({})
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg border border-dashed text-left text-sm transition-colors hover:bg-[var(--color-bg-hover)]"
                  style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                >
                  <Plus className="w-4 h-4 flex-shrink-0" />
                  Новая задача
                </button>

                <p className="text-[10px] font-medium uppercase tracking-wide px-1 pt-2" style={{ color: 'var(--color-text-disabled)' }}>
                  Готовые старты
                </p>
                {WORKFLOW_PRESETS.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => applyPreset(p.userTask)}
                    className="w-full text-left px-3 py-2.5 rounded-lg border transition-colors hover:bg-[var(--color-bg-hover)]"
                    style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-primary)' }}
                  >
                    <div className="flex items-center justify-between gap-2 mb-0.5">
                      <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                        {p.title}
                      </span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ backgroundColor: 'var(--color-bg-hover)', color: 'var(--color-text-muted)' }}>
                        {WORKFLOW_CATEGORY_LABELS[p.category]}
                      </span>
                    </div>
                    <p className="text-xs leading-snug" style={{ color: 'var(--color-text-muted)' }}>
                      {p.description}
                    </p>
                  </button>
                ))}

                {savedWorkflows.length > 0 && (
                  <>
                    <p className="text-[10px] font-medium uppercase tracking-wide px-1 pt-3" style={{ color: 'var(--color-text-disabled)' }}>
                      Мои сценарии
                    </p>
                    {savedWorkflows.map((w) => (
                      <div
                        key={w.id}
                        className="group rounded-lg border"
                        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-primary)' }}
                      >
                        <button
                          type="button"
                          onClick={() => applyPreset(w.user_task, w.default_file_ids)}
                          className="w-full text-left px-3 py-2.5"
                        >
                          <p className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                            {w.title}
                          </p>
                          {w.description && (
                            <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                              {truncate(w.description, 80)}
                            </p>
                          )}
                        </button>
                        <div className="flex justify-end px-2 pb-2 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            type="button"
                            onClick={async () => {
                              try {
                                await deleteCaseWorkflow(caseId, w.id)
                                await refreshMeta()
                              } catch (e) {
                                toast.error(extractErrorMessage(e))
                              }
                            }}
                            className="p-1 rounded hover:bg-red-50"
                            title="Удалить"
                          >
                            <Trash2 className="w-3.5 h-3.5 text-red-500" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </>
                )}
              </>
            )}

            {sidebarTab === 'history' && (
              <>
                {loadingMeta && (
                  <div className="flex justify-center py-8">
                    <Loader2 className="w-5 h-5 animate-spin" style={{ color: 'var(--color-text-muted)' }} />
                  </div>
                )}
                {!loadingMeta && history.length === 0 && (
                  <p className="text-xs text-center py-8" style={{ color: 'var(--color-text-muted)' }}>
                    Запусков пока нет
                  </p>
                )}
                {history.map((run) => (
                  <button
                    key={run.id}
                    type="button"
                    onClick={() => void openRun(run.id)}
                    className="w-full text-left px-3 py-2.5 rounded-lg border transition-colors hover:bg-[var(--color-bg-hover)]"
                    style={{
                      borderColor: activeRunId === run.id ? 'var(--color-text-secondary)' : 'var(--color-border)',
                      backgroundColor: activeRunId === run.id ? 'var(--color-bg-hover)' : 'var(--color-bg-primary)',
                    }}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      {run.status === 'completed' ? (
                        <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" style={{ color: statusColor(run.status) }} />
                      ) : run.status === 'failed' || run.status === 'cancelled' ? (
                        <XCircle className="w-3.5 h-3.5 flex-shrink-0" style={{ color: statusColor(run.status) }} />
                      ) : (
                        <Loader2 className="w-3.5 h-3.5 flex-shrink-0 animate-spin" style={{ color: statusColor(run.status) }} />
                      )}
                      <span className="text-[10px] font-medium" style={{ color: statusColor(run.status) }}>
                        {statusLabel(run.status)}
                      </span>
                      <span className="text-[10px] ml-auto" style={{ color: 'var(--color-text-disabled)' }}>
                        {formatWhen(run.created_at)}
                      </span>
                    </div>
                    <p className="text-xs leading-snug" style={{ color: 'var(--color-text-primary)' }}>
                      {truncate(run.user_task, 120)}
                    </p>
                  </button>
                ))}
              </>
            )}
          </div>
        </aside>

        {/* Main workspace */}
        <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <header
            className="flex items-center justify-between px-6 py-3 border-b flex-shrink-0"
            style={{ borderColor: 'var(--color-border)' }}
          >
            <div className="flex items-center gap-3 min-w-0">
              <Link
                to={`/cases/${caseId}`}
                className="flex items-center gap-1.5 text-sm hover:underline flex-shrink-0"
                style={{ color: 'var(--color-text-muted)' }}
              >
                <ArrowLeft className="w-4 h-4" />
                К делу
              </Link>
              <span style={{ color: 'var(--color-border)' }}>|</span>
              <p className="text-sm truncate" style={{ color: 'var(--color-text-muted)' }}>
                {showComposer ? 'Новая задача' : activeRunMeta ? truncate(activeRunMeta.user_task, 64) : 'Workflow'}
              </p>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              {canCancel && (
                <button
                  type="button"
                  onClick={() => void handleCancel()}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border"
                  style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
                >
                  <Square className="w-3.5 h-3.5" />
                  Отменить
                </button>
              )}
              {!showComposer && (
                <button
                  type="button"
                  onClick={() => {
                    setShowComposer(true)
                    setSearchParams({})
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white"
                  style={{ backgroundColor: 'var(--color-text-primary)' }}
                >
                  <Plus className="w-3.5 h-3.5" />
                  Новая задача
                </button>
              )}
            </div>
          </header>

          {showComposer ? (
            <div className="flex-1 overflow-y-auto px-6 py-6">
              <div className="max-w-2xl mx-auto">
                <h2 className="text-lg font-semibold mb-1" style={{ color: 'var(--color-text-primary)' }}>
                  Опишите задачу
                </h2>
                <p className="text-sm mb-5" style={{ color: 'var(--color-text-muted)' }}>
                  Агент сам спланирует шаги и выберет инструменты: поиск по делу, нормы права, таблицы, черновик документа.
                </p>

                <textarea
                  value={userTask}
                  onChange={(e) => setUserTask(e.target.value)}
                  rows={8}
                  placeholder="Например: Собери таблицу задолженности по контрагентам, найди нормы о субординации и подготовь черновик заявления в арбитражный суд."
                  className="w-full resize-none rounded-xl border px-4 py-3 text-sm outline-none focus:ring-2"
                  style={{
                    borderColor: 'var(--color-border)',
                    color: 'var(--color-text-primary)',
                    backgroundColor: 'var(--color-bg-elevated)',
                  }}
                />

                <div className="mt-4 relative">
                  <button
                    type="button"
                    onClick={() => setFilesOpen((o) => !o)}
                    className="flex items-center gap-2 px-3 py-2 rounded-lg border text-sm"
                    style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}
                  >
                    <FolderOpen className="w-4 h-4" />
                    Документы дела
                    {selectedFileIds.length > 0 && (
                      <span className="px-1.5 py-0.5 rounded-full text-xs" style={{ backgroundColor: 'var(--color-bg-hover)' }}>
                        {selectedFileIds.length}
                      </span>
                    )}
                  </button>
                  {filesOpen && (
                    <div
                      className="absolute z-10 mt-2 w-full max-h-48 overflow-y-auto rounded-xl border shadow-lg p-2"
                      style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-elevated)' }}
                    >
                      {caseFiles.length === 0 ? (
                        <p className="text-xs p-2" style={{ color: 'var(--color-text-muted)' }}>
                          В деле нет загруженных файлов — агент будет работать с доступным контекстом.
                        </p>
                      ) : (
                        caseFiles.map((f) => (
                          <label
                            key={f.id}
                            className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-[var(--color-bg-hover)] cursor-pointer text-sm"
                          >
                            <input
                              type="checkbox"
                              checked={selectedFileIds.includes(f.id)}
                              onChange={() => toggleFile(f.id)}
                            />
                            <FileText className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                            <span className="truncate" style={{ color: 'var(--color-text-primary)' }}>
                              {f.filename}
                            </span>
                          </label>
                        ))
                      )}
                    </div>
                  )}
                  {selectedFileIds.length > 0 && (
                    <div className="flex flex-wrap gap-2 mt-2">
                      {selectedFileIds.map((id) => {
                        const f = caseFiles.find((x) => x.id === id)
                        return (
                          <span
                            key={id}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs border"
                            style={{ borderColor: 'var(--color-border)' }}
                          >
                            {f?.filename ?? id}
                            <button type="button" onClick={() => toggleFile(id)}>
                              <X className="w-3 h-3" />
                            </button>
                          </span>
                        )
                      })}
                    </div>
                  )}
                </div>

                <div className="mt-6 flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={!userTask.trim() || isStreaming}
                    onClick={() => void handleStart()}
                    className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium text-white disabled:opacity-40"
                    style={{ backgroundColor: 'var(--color-text-primary)' }}
                  >
                    {isStreaming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                    Запустить
                  </button>
                  {userTask.trim().length >= 10 && (
                    <button
                      type="button"
                      onClick={() => {
                        setSaveTitle('')
                        setSaveOpen(true)
                      }}
                      className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm border"
                      style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
                    >
                      <BookmarkPlus className="w-4 h-4" />
                      Сохранить сценарий
                    </button>
                  )}
                </div>
              </div>
            </div>
          ) : showLivePanel ? (
            <div className="flex-1 overflow-y-auto px-6 py-6">
              <div className="max-w-3xl mx-auto">
                {activeRunMeta && (
                  <div
                    className="mb-4 flex items-center gap-2 text-xs px-3 py-2 rounded-lg border"
                    style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
                  >
                    <Circle className="w-2 h-2 fill-current flex-shrink-0" style={{ color: statusColor(activeRunMeta.status) }} />
                    <span style={{ color: statusColor(activeRunMeta.status) }}>{statusLabel(activeRunMeta.status)}</span>
                    {activeRunMeta.created_at && (
                      <>
                        <Clock className="w-3 h-3 ml-2" />
                        {formatWhen(activeRunMeta.created_at)}
                      </>
                    )}
                    {activeRunMeta.total_tool_calls > 0 && (
                      <span className="ml-auto">{activeRunMeta.total_tool_calls} инструмент(ов)</span>
                    )}
                  </div>
                )}

                <div
                  className="mb-4 px-4 py-3 rounded-xl border text-sm"
                  style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-elevated)', color: 'var(--color-text-secondary)' }}
                >
                  {activeRunMeta?.user_task}
                </div>

                {(liveSlice.toolCalls.length > 0 ||
                  liveSlice.agentTodos.length > 0 ||
                  isStreaming) && (
                  <div className="mb-4">
                    <ThinkingBlock
                      steps={[]}
                      toolCalls={liveSlice.toolCalls}
                      agentTodos={liveSlice.agentTodos}
                      planOutlineTitle="Ход выполнения"
                      isStreaming={isStreaming}
                      defaultOpen
                    />
                  </div>
                )}

                {liveSlice.agentInterrupt && activeRunId && (
                  <AgentInterruptCard
                    onApprove={() => void handleResume(true)}
                    onReject={() => void handleResume(false)}
                  />
                )}

                {liveSlice.artifacts.length > 0 && (
                  <WorkflowArtifacts items={liveSlice.artifacts} />
                )}

                {liveSlice.content && (
                  <div className="rounded-xl border p-4" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-elevated)' }}>
                    <p className="text-xs font-medium mb-3 uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
                      Результат
                    </p>
                    <MessageContent content={liveSlice.content} sources={[]} isStreaming={false} />
                  </div>
                )}

                {!liveSlice.content &&
                  !liveSlice.artifacts.length &&
                  !isStreaming &&
                  liveSlice.agentRunStatus === 'failed' && (
                  <p className="text-sm" style={{ color: 'var(--color-danger, #dc2626)' }}>
                    {liveSlice.errorMessage || 'Выполнение завершилось с ошибкой'}
                  </p>
                )}

                {!liveSlice.content && isStreaming && !liveSlice.agentTodos.length && !liveSlice.toolCalls.length && (
                  <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-text-muted)' }}>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Составляю план…
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
              <Sparkles className="w-10 h-10 mb-4" style={{ color: 'var(--color-text-disabled)' }} />
              <h2 className="text-lg font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                Workflows
              </h2>
              <p className="text-sm max-w-md mb-6" style={{ color: 'var(--color-text-muted)' }}>
                Выберите готовый сценарий слева, откройте запуск из истории или создайте новую задачу.
              </p>
              <button
                type="button"
                onClick={() => setShowComposer(true)}
                className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium text-white"
                style={{ backgroundColor: 'var(--color-text-primary)' }}
              >
                <Plus className="w-4 h-4" />
                Новая задача
              </button>
            </div>
          )}
        </main>
      </div>

      {saveOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div
            className="w-full max-w-md rounded-xl border p-5 shadow-xl"
            style={{ backgroundColor: 'var(--color-bg-elevated)', borderColor: 'var(--color-border)' }}
          >
            <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--color-text-primary)' }}>
              Сохранить сценарий
            </h3>
            <input
              value={saveTitle}
              onChange={(e) => setSaveTitle(e.target.value)}
              placeholder="Название, например: Проверка договора поставки"
              className="w-full rounded-lg border px-3 py-2 text-sm outline-none mb-4"
              style={{ borderColor: 'var(--color-border)' }}
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setSaveOpen(false)}
                className="px-3 py-1.5 rounded-lg text-sm border"
                style={{ borderColor: 'var(--color-border)' }}
              >
                Отмена
              </button>
              <button
                type="button"
                disabled={!saveTitle.trim() || saving}
                onClick={() => void handleSaveScenario()}
                className="px-4 py-1.5 rounded-lg text-sm font-medium text-white disabled:opacity-40"
                style={{ backgroundColor: 'var(--color-text-primary)' }}
              >
                {saving ? 'Сохранение…' : 'Сохранить'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default CaseWorkflowsPage
