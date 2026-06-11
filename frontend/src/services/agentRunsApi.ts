import { getApiUrl } from './api'

export type AgentRunStatus =
  | 'pending'
  | 'running'
  | 'waiting_for_user'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type AgentRunEventType =
  | 'stream_open'
  | 'run_started'
  | 'status'
  | 'todos_updated'
  | 'tool_started'
  | 'tool_completed'
  | 'text_delta'
  | 'interrupt'
  | 'run_completed'
  | 'run_failed'
  | 'run_cancelled'
  | 'error'

export interface AgentRunStreamEvent {
  type: AgentRunEventType
  run_id: string
  timestamp?: string
  message?: string
  data?: Record<string, unknown>
}

export interface CreateAgentRunResponse {
  id: string
  case_id: string
  thread_id: string
  status: AgentRunStatus
  user_task: string
  created_at?: string
}

export interface AgentRunListItem {
  id: string
  case_id: string
  status: AgentRunStatus
  user_task: string
  result_summary?: string | null
  error_message?: string | null
  total_tool_calls: number
  created_at?: string
  completed_at?: string | null
}

export interface AgentRunArtifactItem {
  type: string
  id: string
  title: string
  path: string
  preview?: string
  row_count?: number
  saved_count?: number
}

export interface AgentRunDetail extends AgentRunListItem {
  thread_id: string
  selected_file_ids?: string[] | null
  todos?: Array<{ content?: string; status?: string }> | null
  artifacts?: { items?: AgentRunArtifactItem[]; interrupt?: Record<string, unknown> } | null
  started_at?: string | null
}

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('access_token')
  return {
    'Content-Type': 'application/json',
    'X-Access-Token': token || '',
  }
}

export async function listAgentRuns(caseId: string, limit = 50): Promise<AgentRunListItem[]> {
  const params = new URLSearchParams({ case_id: caseId, limit: String(limit) })
  const res = await fetch(getApiUrl(`/api/agent-runs?${params}`), {
    headers: authHeaders(),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `listAgentRuns failed: ${res.status}`)
  }
  const data = await res.json()
  return data.items ?? []
}

export async function getAgentRun(runId: string): Promise<AgentRunDetail> {
  const res = await fetch(getApiUrl(`/api/agent-runs/${runId}`), {
    headers: authHeaders(),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `getAgentRun failed: ${res.status}`)
  }
  return res.json()
}

export async function cancelAgentRun(runId: string): Promise<void> {
  const res = await fetch(getApiUrl(`/api/agent-runs/${runId}/cancel`), {
    method: 'POST',
    headers: authHeaders(),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `cancelAgentRun failed: ${res.status}`)
  }
}

export async function createAgentRun(params: {
  caseId: string
  userTask: string
  fileIds?: string[]
}): Promise<CreateAgentRunResponse> {
  const res = await fetch(getApiUrl('/api/agent-runs'), {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      case_id: params.caseId,
      user_task: params.userTask,
      file_ids: params.fileIds?.length ? params.fileIds : undefined,
    }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `createAgentRun failed: ${res.status}`)
  }
  return res.json()
}

export interface AgentRunStreamOptions {
  signal?: AbortSignal
  onEvent: (event: AgentRunStreamEvent) => void
}

async function consumeAgentRunSse(response: Response, onEvent: (event: AgentRunStreamEvent) => void) {
  if (!response.ok) {
    throw new Error(`agent run stream failed: ${response.status}`)
  }
  const reader = response.body?.getReader()
  if (!reader) throw new Error('agent run stream: empty body')

  const decoder = new TextDecoder()
  let buffer = ''

  const processLine = (line: string) => {
    if (!line.startsWith('data: ')) return
    const raw = line.slice(6).trim()
    if (!raw) return
    try {
      const event = JSON.parse(raw) as AgentRunStreamEvent
      if (event?.type && event?.run_id) onEvent(event)
    } catch {
      /* ignore malformed chunk */
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      if (buffer) {
        for (const line of buffer.split('\n')) processLine(line)
      }
      break
    }
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) processLine(line)
  }
}

export async function streamAgentRun(runId: string, options: AgentRunStreamOptions): Promise<void> {
  const res = await fetch(getApiUrl(`/api/agent-runs/${runId}/stream`), {
    method: 'GET',
    headers: authHeaders(),
    signal: options.signal,
  })
  await consumeAgentRunSse(res, options.onEvent)
}

export async function resumeAgentRun(
  runId: string,
  body: { approved: boolean; payload?: Record<string, unknown> },
  options: AgentRunStreamOptions,
): Promise<void> {
  const res = await fetch(getApiUrl(`/api/agent-runs/${runId}/resume`), {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
    signal: options.signal,
  })
  await consumeAgentRunSse(res, options.onEvent)
}
