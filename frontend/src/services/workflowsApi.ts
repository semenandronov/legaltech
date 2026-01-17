/**
 * API сервис для Agentic Workflows
 */
import api from './api'

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
  const response = await api.get('/api/workflow-agentic/definitions', { params })
  // Ensure we always return an array
  return Array.isArray(response.data) ? response.data : []
}

export const getDefinition = async (definitionId: string): Promise<WorkflowDefinition> => {
  const response = await api.get(`/workflow-agentic/definitions/${definitionId}`)
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
  is_public?: boolean
}): Promise<WorkflowDefinition> => {
  const response = await api.post('/api/workflow-agentic/definitions', data)
  return response.data
}

export const updateDefinition = async (
  definitionId: string,
  data: Partial<WorkflowDefinition>
): Promise<WorkflowDefinition> => {
  const response = await api.put(`/workflow-agentic/definitions/${definitionId}`, data)
  return response.data
}

export const deleteDefinition = async (definitionId: string): Promise<void> => {
  await api.delete(`/workflow-agentic/definitions/${definitionId}`)
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
  return response.data
}

export const getExecutions = async (params?: {
  status?: string
  case_id?: string
  limit?: number
  offset?: number
}): Promise<WorkflowExecution[]> => {
  const response = await api.get('/api/workflow-agentic/executions', { params })
  // Ensure we always return an array
  return Array.isArray(response.data) ? response.data : []
}

export const getExecution = async (executionId: string): Promise<WorkflowExecution> => {
  const response = await api.get(`/workflow-agentic/executions/${executionId}`)
  return response.data
}

export const cancelExecution = async (executionId: string): Promise<void> => {
  await api.post(`/workflow-agentic/executions/${executionId}/cancel`)
}

export const getExecutionResults = async (executionId: string): Promise<{
  status: string
  results: Record<string, any>
  artifacts: WorkflowArtifacts
  summary: string
  completed_at: string
}> => {
  const response = await api.get(`/workflow-agentic/executions/${executionId}/results`)
  return response.data
}

export const getExecutionSteps = async (executionId: string): Promise<WorkflowExecutionStep[]> => {
  const response = await api.get(`/workflow-agentic/executions/${executionId}/steps`)
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
  const response = await api.post(`/workflow-agentic/executions/${executionId}/validate`)
  return response.data
}

// SSE Stream for real-time updates
export const streamExecution = (
  executionId: string,
  onEvent: (event: WorkflowEvent) => void,
  onError?: (error: Error) => void
): (() => void) => {
  const baseUrl = import.meta.env.VITE_API_URL || ''
  const token = localStorage.getItem('access_token')
  const url = `${baseUrl}/api/workflow-agentic/executions/${executionId}/stream`

  const eventSource = new EventSource(url, {
    // @ts-ignore - некоторые браузеры поддерживают headers
    headers: token ? { Authorization: `Bearer ${token}` } : undefined
  })

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

// Stream workflow events as async generator
export async function* streamWorkflowEvents(executionId: string): AsyncGenerator<WorkflowEvent> {
  const baseUrl = import.meta.env.VITE_API_URL || ''
  const token = localStorage.getItem('access_token')
  const url = `${baseUrl}/api/workflow-agentic/executions/${executionId}/stream`
  
  try {
    const response = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    })
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    
    const reader = response.body?.getReader()
    if (!reader) return
    
    const decoder = new TextDecoder()
    let buffer = ''
    
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            yield data as WorkflowEvent
          } catch (e) {
            console.error('Failed to parse SSE event:', e)
          }
        }
      }
    }
  } catch (error) {
    console.error('Stream error:', error)
    // Yield error event
    yield {
      type: 'error',
      execution_id: executionId,
      timestamp: new Date().toISOString(),
      message: 'Connection error'
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

