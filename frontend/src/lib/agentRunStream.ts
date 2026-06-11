import type { ToolCallInfo } from '../components/Chat/ThinkingBlock'
import type { WorkflowArtifactItem } from '../components/AgentRuns/WorkflowArtifacts'
import type { AgentRunStreamEvent } from '../services/agentRunsApi'

export interface AgentTodoItem {
  content: string
  status: string
}

export interface AgentRunMessageSlice {
  content: string
  toolCalls: ToolCallInfo[]
  agentTodos: AgentTodoItem[]
  artifacts: WorkflowArtifactItem[]
  agentInterrupt?: Record<string, unknown> | null
  agentRunId?: string
  agentRunStatus?: 'running' | 'completed' | 'failed' | 'waiting_for_user'
  errorMessage?: string
}

function parseArtifact(raw: unknown): WorkflowArtifactItem | null {
  if (!raw || typeof raw !== 'object') return null
  const a = raw as Record<string, unknown>
  const id = String(a.id ?? '').trim()
  const path = String(a.path ?? '').trim()
  const title = String(a.title ?? '').trim()
  const type = String(a.type ?? 'artifact')
  if (!id || !path || !title) return null
  return {
    type,
    id,
    title,
    path,
    preview: typeof a.preview === 'string' ? a.preview : undefined,
    row_count: typeof a.row_count === 'number' ? a.row_count : undefined,
    saved_count: typeof a.saved_count === 'number' ? a.saved_count : undefined,
  }
}

function mergeArtifacts(existing: WorkflowArtifactItem[], incoming: WorkflowArtifactItem): WorkflowArtifactItem[] {
  if (existing.some((it) => it.type === incoming.type && it.id === incoming.id)) {
    return existing
  }
  return [...existing, incoming]
}

function artifactsFromPayload(data: Record<string, unknown>): WorkflowArtifactItem[] {
  const raw = data.artifacts
  if (!raw || typeof raw !== 'object') return []
  const items = (raw as { items?: unknown }).items
  if (!Array.isArray(items)) return []
  return items.map(parseArtifact).filter((x): x is WorkflowArtifactItem => x !== null)
}

export function artifactsFromStoredRecord(
  artifacts?: { items?: unknown[]; interrupt?: unknown } | null,
): WorkflowArtifactItem[] {
  if (!artifacts?.items || !Array.isArray(artifacts.items)) return []
  return artifacts.items.map(parseArtifact).filter((x): x is WorkflowArtifactItem => x !== null)
}

export function createEmptyAgentRunSlice(runId?: string): AgentRunMessageSlice {
  return {
    content: '',
    toolCalls: [],
    agentTodos: [],
    artifacts: [],
    agentInterrupt: null,
    agentRunId: runId,
    agentRunStatus: 'running',
  }
}

function upsertToolCall(toolCalls: ToolCallInfo[], name: string, patch: Partial<ToolCallInfo>): ToolCallInfo[] {
  const idx = [...toolCalls].reverse().findIndex((t) => t.name === name && t.status === 'running')
  if (idx >= 0) {
    const realIdx = toolCalls.length - 1 - idx
    const updated = [...toolCalls]
    updated[realIdx] = { ...updated[realIdx], ...patch }
    return updated
  }
  return [...toolCalls, { name, status: patch.status || 'running', ...patch }]
}

export function applyAgentRunEvent(
  slice: AgentRunMessageSlice,
  event: AgentRunStreamEvent,
): AgentRunMessageSlice {
  const next: AgentRunMessageSlice = {
    ...slice,
    toolCalls: [...slice.toolCalls],
    agentTodos: [...slice.agentTodos],
    artifacts: [...slice.artifacts],
    agentRunId: event.run_id || slice.agentRunId,
  }

  const data = event.data || {}

  switch (event.type) {
    case 'todos_updated': {
      const todos = Array.isArray(data.todos) ? data.todos : []
      next.agentTodos = todos.map((t) => ({
        content: String((t as { content?: string }).content ?? ''),
        status: String((t as { status?: string }).status ?? 'pending'),
      }))
      break
    }
    case 'tool_started': {
      const tool = String(data.tool ?? 'tool')
      next.toolCalls = upsertToolCall(next.toolCalls, tool, {
        status: 'running',
        input: data.params_preview,
      })
      break
    }
    case 'tool_completed': {
      const tool = String(data.tool ?? 'tool')
      const success = data.success !== false
      next.toolCalls = upsertToolCall(next.toolCalls, tool, {
        status: success ? 'completed' : 'error',
        output: data.output_summary,
      })
      const artifact = parseArtifact(data.artifact)
      if (artifact) next.artifacts = mergeArtifacts(next.artifacts, artifact)
      break
    }
    case 'text_delta': {
      const text = typeof data.text === 'string' ? data.text : ''
      if (text) next.content += text
      break
    }
    case 'interrupt': {
      next.agentInterrupt = data
      next.agentRunStatus = 'waiting_for_user'
      break
    }
    case 'run_completed':
      next.agentRunStatus = 'completed'
      if (!next.content && typeof data.result_summary === 'string') {
        next.content = data.result_summary
      }
      for (const item of artifactsFromPayload(data)) {
        next.artifacts = mergeArtifacts(next.artifacts, item)
      }
      break
    case 'run_cancelled':
    case 'run_failed':
    case 'error':
      next.agentRunStatus = 'failed'
      next.errorMessage = event.message || String(data.message ?? 'Ошибка выполнения агента')
      break
    default:
      break
  }

  return next
}
