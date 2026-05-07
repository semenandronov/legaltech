/**
 * API сервис для Agentic Workflows
 */
import api from './api'

type SharedGetCacheEntry<T> = { expiresAt: number; value: T }
const workflowGetCache = new Map<string, SharedGetCacheEntry<unknown>>()
const workflowGetInFlight = new Map<string, Promise<unknown>>()

async function cachedWorkflowGet<T>(key: string, ttlMs: number, fetcher: () => Promise<T>): Promise<T> {
  const now = Date.now()
  const cached = workflowGetCache.get(key)
  if (cached && cached.expiresAt > now) {
    return cached.value as T
  }
  const inFlight = workflowGetInFlight.get(key)
  if (inFlight) return inFlight as Promise<T>
  const task = (async () => {
    const value = await fetcher()
    workflowGetCache.set(key, { expiresAt: Date.now() + ttlMs, value })
    return value
  })()
  workflowGetInFlight.set(key, task)
  try {
    return await task
  } finally {
    workflowGetInFlight.delete(key)
  }
}

function invalidateWorkflowCache(prefix: string): void {
  for (const key of workflowGetCache.keys()) {
    if (key.startsWith(prefix)) workflowGetCache.delete(key)
  }
}

// Типы
export interface WorkflowStep {
  id?: string
  name: string
  tool: string
  description?: string
  params?: Record<string, any>
  depends_on?: string[]
}

export interface WorkflowConfig {
  steps: WorkflowStep[]
  output_format?: string
  require_approval?: boolean
}

export interface WorkflowDefinition {
  id: string
  name: string
  display_name: string
  description?: string
  category: string
  available_tools: string[]
  is_system: boolean
  is_public: boolean
  user_id?: string
  usage_count: number
  avg_execution_time?: number
  success_rate?: number
  created_at: string
  estimated_time?: string
  config: WorkflowConfig
  // Детали (только при запросе конкретного definition)
  default_plan?: WorkflowPlan
  output_schema?: Record<string, any>
  planning_prompt?: string
  summary_prompt?: string
  max_steps?: number
  timeout_minutes?: number
  requires_approval?: boolean
}

export interface WorkflowPlan {
  goals: WorkflowGoal[]
  steps: WorkflowPlanStep[]
  estimated_total_duration_seconds: number
  summary: string
}

export interface WorkflowGoal {
  id: string
  description: string
  priority: number
}

export interface WorkflowPlanStep {
  id: string
  name: string
  description: string
  step_type: string
  tool_name?: string
  tool_params?: Record<string, any>
  depends_on: string[]
  expected_output?: string
  goal_id?: string
  estimated_duration_seconds: number
}

export interface WorkflowExecution {
  id: string
  definition_id?: string
  case_id?: string
  user_id: string
  user_task: string
  workflow_name?: string
  status: WorkflowStatus | 'running'
  current_step_id?: string
  progress_percent: number
  progress?: number // alias
  status_message?: string
  summary?: string
  error_message?: string
  started_at: string
  completed_at?: string
  elapsed_time?: string
  total_steps_completed: number
  documents_processed?: number
  result_url?: string
  created_at: string
  // Детали (при запросе конкретного execution)
  input_config?: Record<string, any>
  selected_file_ids?: string[]
  execution_plan?: WorkflowPlan
  results?: Record<string, any>
  artifacts?: WorkflowArtifacts
  total_llm_calls?: number
  total_tokens_used?: number
  steps?: WorkflowExecutionStep[]
}

export type WorkflowStatus =
  | 'pending'
  | 'planning'
  | 'awaiting_approval'
  | 'waiting_for_lawyer'
  | 'executing'
  | 'validating'
  | 'generating_report'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface WorkflowExecutionStep {
  id: string
  execution_id: string
  step_id: string
  sequence_number: number
  step_name: string
  step_type: string
  description?: string
  tool_name?: string
  tool_params?: Record<string, any>
  depends_on: string[]
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'cancelled'
  output_summary?: string
  error?: string
  retry_count: number
  started_at?: string
  completed_at?: string
  duration_seconds?: number
  created_at: string
}

export interface WorkflowArtifacts {
  reports: Array<{ id: string; name: string; type: string }>
  tables: Array<{ id: string; name: string }>
  documents: Array<{ id: string; name: string }>
  checks: Array<{ id: string; document_id: string }>
}

export interface WorkflowCategory {
  name: string
  display_name: string
  description: string
}

export interface WorkflowTool {
  name: string
  display_name: string
  description: string
  params_schema?: Record<string, any>
}

export interface WorkflowEvent {
  type: string
  event_type?: string
  execution_id: string
  step_id?: string
  step_name?: string
  data?: Record<string, any>
  details?: Record<string, any> | string
  timestamp: string
  progress_percent?: number
  progress?: number
  message: string
}

// API методы

// Metadata
export const getCategories = async (): Promise<WorkflowCategory[]> => {
  const response = await api.get('/api/workflow-agentic/metadata/categories')
  return Array.isArray(response.data) ? response.data : []
}

export const getTools = async (): Promise<WorkflowTool[]> => {
  const response = await api.get('/api/workflow-agentic/metadata/tools')
  return Array.isArray(response.data) ? response.data : []
}

export const getSystemTemplates = async (): Promise<any[]> => {
  const response = await api.get('/api/workflow-agentic/metadata/system-templates')
  return Array.isArray(response.data) ? response.data : []
}

// Definitions CRUD
export const getDefinitions = async (params?: {
  category?: string
  include_system?: boolean
  include_public?: boolean
  limit?: number
  offset?: number
}): Promise<WorkflowDefinition[]> => {
  const key = `wf-definitions:${JSON.stringify(params || {})}`
  return cachedWorkflowGet(key, 3000, async () => {
    const response = await api.get('/api/workflow-agentic/definitions', { params })
    return Array.isArray(response.data) ? response.data : []
  })
}

export const getDefinition = async (definitionId: string): Promise<WorkflowDefinition> => {
  const response = await api.get(`/api/workflow-agentic/definitions/${definitionId}`)
  return response.data
}

export const createDefinition = async (data: {
  name: string
  display_name: string
  description?: string
  category: string
  available_tools: string[]
  default_plan?: Record<string, any>
  output_schema?: Record<string, any>
  planning_prompt?: string
  summary_prompt?: string
  max_steps?: number
  timeout_minutes?: number
  requires_approval?: boolean
  is_public?: boolean
}): Promise<WorkflowDefinition> => {
  const response = await api.post('/api/workflow-agentic/definitions', data)
  return response.data
}

export const updateDefinition = async (
  definitionId: string,
  data: Partial<WorkflowDefinition>
): Promise<WorkflowDefinition> => {
  const response = await api.put(`/api/workflow-agentic/definitions/${definitionId}`, data)
  return response.data
}

export const deleteDefinition = async (definitionId: string): Promise<void> => {
  await api.delete(`/api/workflow-agentic/definitions/${definitionId}`)
}

// Planning
export const createPlan = async (data: {
  definition_id?: string
  user_task: string
  case_id?: string
  file_ids?: string[]
}): Promise<{
  plan: WorkflowPlan
  validation_errors: string[]
  is_valid: boolean
  estimated_duration_seconds: number
}> => {
  const response = await api.post('/api/workflow-agentic/plan', data)
  return response.data
}

// Execution
export const executeWorkflow = async (data: {
  definition_id?: string
  user_task: string
  case_id?: string
  file_ids?: string[]
  input_config?: Record<string, any>
}): Promise<{
  execution_id: string
  status: string
  message: string
}> => {
  const response = await api.post('/api/workflow-agentic/execute', data)
  invalidateWorkflowCache('wf-executions:')
  return response.data
}

export const getExecutions = async (params?: {
  status?: string
  case_id?: string
  limit?: number
  offset?: number
}): Promise<WorkflowExecution[]> => {
  const key = `wf-executions:${JSON.stringify(params || {})}`
  return cachedWorkflowGet(key, 3000, async () => {
    const response = await api.get('/api/workflow-agentic/executions', { params })
    return Array.isArray(response.data) ? response.data : []
  })
}

export const getExecution = async (executionId: string): Promise<WorkflowExecution> => {
  return cachedWorkflowGet(`wf-execution:${executionId}`, 1500, async () => {
    const response = await api.get(`/api/workflow-agentic/executions/${executionId}`)
    return response.data
  })
}

export const cancelExecution = async (executionId: string): Promise<void> => {
  await api.post(`/api/workflow-agentic/executions/${executionId}/cancel`)
  invalidateWorkflowCache(`wf-execution:${executionId}`)
  invalidateWorkflowCache('wf-executions:')
}

export const getExecutionResults = async (executionId: string): Promise<{
  status: string
  results: Record<string, any>
  artifacts: WorkflowArtifacts
  summary: string
  completed_at: string
}> => {
  const response = await api.get(`/api/workflow-agentic/executions/${executionId}/results`)
  return response.data
}

export const getExecutionSteps = async (executionId: string): Promise<WorkflowExecutionStep[]> => {
  const response = await api.get(`/api/workflow-agentic/executions/${executionId}/steps`)
  return Array.isArray(response.data) ? response.data : []
}

export const validateExecution = async (executionId: string): Promise<{
  is_valid: boolean
  confidence_score: number
  issues: Array<{
    severity: string
    message: string
    step_id?: string
    suggestion?: string
  }>
  summary: string
}> => {
  const response = await api.post(`/api/workflow-agentic/executions/${executionId}/validate`)
  return response.data
}

/**
 * URL SSE для workflow. В dev всегда относительный `/api/...` — тот же origin, что у Vite,
 * прокси в vite.config.ts пересылает на бэкенд. Если подставлять `VITE_API_URL` с другим
 * host/port, EventSource часто не получает события (зависание на «Подключение к потоку…»),
 * хотя axios с CORS к тому же API работает.
 */
export function buildWorkflowSseUrl(executionId: string): string {
  const token = localStorage.getItem('access_token')
  const qs = token ? `?token=${encodeURIComponent(token)}` : ''
  const path = `/api/workflow-agentic/executions/${executionId}/stream${qs}`
  if (import.meta.env.DEV) {
    return path
  }
  const base = (import.meta.env.VITE_API_URL || '').trim().replace(/\/$/, '')
  return base ? `${base}${path}` : path
}

// SSE Stream for real-time updates
// ВАЖНО: EventSource API не поддерживает кастомные headers,
// поэтому токен передаётся через query параметр
export const streamExecution = (
  executionId: string,
  onEvent: (event: WorkflowEvent) => void,
  onError?: (error: Error) => void
): (() => void) => {
  const url = buildWorkflowSseUrl(executionId)

  const eventSource = new EventSource(url)

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as WorkflowEvent
      onEvent(data)
    } catch (e) {
      console.error('Failed to parse SSE event:', e)
    }
  }

  eventSource.onerror = (error) => {
    console.error('SSE error:', error)
    if (onError) {
      onError(new Error('SSE connection error'))
    }
    eventSource.close()
  }

  // Возвращаем функцию закрытия
  return () => {
    eventSource.close()
  }
}

// Aliases for compatibility
export const getWorkflowDefinitions = getDefinitions
export const getWorkflowExecutions = getExecutions

// Execute workflow with new signature
export const executeWorkflowWithDocs = async (
  definitionId: string,
  params: {
    case_id?: string
    document_ids?: string[]
    options?: Record<string, any>
  }
): Promise<WorkflowExecution> => {
  const response = await api.post('/api/workflow-agentic/execute', {
    definition_id: definitionId,
    case_id: params.case_id,
    file_ids: params.document_ids,
    input_config: params.options,
    user_task: 'Execute workflow'
  })
  return {
    id: response.data.execution_id,
    status: response.data.status,
    started_at: new Date().toISOString(),
    workflow_name: 'Workflow',
    progress: 0,
    progress_percent: 0,
    user_id: '',
    user_task: '',
    total_steps_completed: 0,
    created_at: new Date().toISOString()
  }
}

/** Закрывает активный EventSource для execution (два параллельных SSE ломают stream lock на бэкенде). */
const workflowStreamReleaseByExecution = new Map<string, () => void>()

export function releaseWorkflowEventStream(executionId: string): void {
  workflowStreamReleaseByExecution.get(executionId)?.()
  workflowStreamReleaseByExecution.delete(executionId)
}

/**
 * Поток событий workflow по SSE.
 *
 * Раньше использовали fetch + ReadableStream: во многих окружениях тело ответа
 * буферизуется до крупного чанка — пользователь не видел прогресс минутами, хотя
 * workflow на сервере шёл. EventSource доставляет default message-события по мере прихода.
 */
export async function* streamWorkflowEvents(executionId: string): AsyncGenerator<WorkflowEvent> {
  releaseWorkflowEventStream(executionId)

  const url = buildWorkflowSseUrl(executionId)

  const incoming: WorkflowEvent[] = []
  let wake: (() => void) | null = null
  let fatal = false
  let silentClose = false
  let lastErrorAt = 0

  const notify = () => {
    wake?.()
    wake = null
  }

  const waitNext = () =>
    new Promise<void>((resolve) => {
      if (incoming.length > 0 || fatal) {
        resolve()
        return
      }
      wake = resolve
    })

  const es = new EventSource(url)

  const hardRelease = () => {
    if (silentClose) return
    silentClose = true
    fatal = true
    notify()
    try {
      es.close()
    } catch {
      /* ignore */
    }
  }

  workflowStreamReleaseByExecution.set(executionId, hardRelease)

  es.onmessage = (ev: MessageEvent) => {
    try {
      incoming.push(JSON.parse(ev.data) as WorkflowEvent)
    } catch (e) {
      console.error('Failed to parse SSE event:', e)
    }
    notify()
  }

  es.onerror = () => {
    if (silentClose) {
      try {
        es.close()
      } catch {
        /* ignore */
      }
      return
    }
    // Do not close on transient SSE errors: EventSource auto-reconnects.
    // Closing here forces frontend into aggressive polling and increases backend load.
    const now = Date.now()
    if (now - lastErrorAt > 15000) {
      lastErrorAt = now
      incoming.push({
        type: 'status',
        execution_id: executionId,
        timestamp: new Date().toISOString(),
        message: 'Переподключение к потоку workflow...',
      } as WorkflowEvent)
      notify()
    }
  }

  try {
    while (!fatal || incoming.length > 0) {
      await waitNext()
      while (incoming.length > 0) {
        const ev = incoming.shift()!
        yield ev
        const t = String((ev as any).type || (ev as any).event_type || '').toLowerCase()
        if (['completed', 'failed', 'cancelled', 'completed_with_errors', 'error'].includes(t)) {
          fatal = true
          es.close()
          return
        }
      }
      if (fatal) break
    }
  } finally {
    if (workflowStreamReleaseByExecution.get(executionId) === hardRelease) {
      workflowStreamReleaseByExecution.delete(executionId)
    }
    fatal = true
    silentClose = true
    try {
      es.close()
    } catch {
      /* ignore */
    }
  }
}

// Utility functions
export const getStatusColor = (status: WorkflowStatus | string): string => {
  switch (status) {
    case 'completed':
      return 'var(--color-success)'
    case 'failed':
    case 'cancelled':
      return 'var(--color-error)'
    case 'executing':
    case 'planning':
    case 'validating':
    case 'generating_report':
      return 'var(--color-accent)'
    case 'awaiting_approval':
    case 'waiting_for_lawyer':
      return 'var(--color-warning)'
    case 'pending':
    default:
      return 'var(--color-text-secondary)'
  }
}

export const getStatusLabel = (status: WorkflowStatus | string): string => {
  switch (status) {
    case 'pending':
      return 'Ожидание'
    case 'planning':
      return 'Планирование'
    case 'awaiting_approval':
      return 'Ожидает одобрения'
    case 'waiting_for_lawyer':
      return 'Ожидает юриста'
    case 'executing':
      return 'Выполнение'
    case 'validating':
      return 'Валидация'
    case 'generating_report':
      return 'Генерация отчёта'
    case 'completed':
      return 'Завершено'
    case 'failed':
      return 'Ошибка'
    case 'cancelled':
      return 'Отменено'
    default:
      return status
  }
}

export const getCategoryLabel = (category: string): string => {
  switch (category) {
    case 'due_diligence':
      return 'Due Diligence'
    case 'litigation':
      return 'Судебные споры'
    case 'compliance':
      return 'Комплаенс'
    case 'research':
      return 'Исследование'
    case 'contract_analysis':
      return 'Анализ контрактов'
    case 'custom':
      return 'Пользовательский'
    default:
      return category
  }
}

export const getCategoryIcon = (category: string): string => {
  switch (category) {
    case 'due_diligence':
      return '🔍'
    case 'litigation':
      return '⚖️'
    case 'compliance':
      return '✅'
    case 'research':
      return '📚'
    case 'contract_analysis':
      return '📋'
    case 'custom':
      return '⚙️'
    default:
      return '📁'
  }
}

export const formatDuration = (seconds: number): string => {
  if (seconds < 60) {
    return `${seconds} сек`
  } else if (seconds < 3600) {
    const mins = Math.floor(seconds / 60)
    return `${mins} мин`
  } else {
    const hours = Math.floor(seconds / 3600)
    const mins = Math.floor((seconds % 3600) / 60)
    return mins > 0 ? `${hours} ч ${mins} мин` : `${hours} ч`
  }
}

