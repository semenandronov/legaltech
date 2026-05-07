/**
 * Shared types and helpers for live workflow execution (global assistant + case chat).
 */
import type {
  WorkflowEvent,
  WorkflowExecution,
  WorkflowExecutionStep,
} from '../services/workflowsApi'
import type { WorkflowPlanOutlineRow, WorkflowAgentTodoItem } from '../components/Chat/ThinkingBlock'

export interface WorkflowLiveStep {
  id: string
  name: string
  tool?: string
  order: number
}

export interface WorkflowLiveContext {
  execution_id: string
  workflow_id?: string
  workflow_name: string
  case_id?: string
  document_ids?: string[]
  steps: WorkflowLiveStep[]
  started_at?: string
  /** Куда вести «Назад» из артефактов (чат дела или глобальный ассистент) */
  return_chat_path?: string
}

export interface WorkflowArtifactsPayload {
  tables: Array<Record<string, unknown>>
  documents: Array<Record<string, unknown>>
  reports: Array<Record<string, unknown>>
  checks: Array<Record<string, unknown>>
}

export function buildPlanOutlineFromContext(ctx: WorkflowLiveContext | null): WorkflowPlanOutlineRow[] {
  if (!ctx?.steps?.length) return []
  return [...ctx.steps]
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    .map((s) => ({
      id: String(s.id || `step_${s.order}`),
      label: s.name || s.tool || `Шаг ${s.order}`,
      tool: s.tool ? String(s.tool).trim().toLowerCase() : undefined,
      status: 'pending' as const,
    }))
}

export function mapDbStepStatus(st: string): WorkflowPlanOutlineRow['status'] {
  if (st === 'completed' || st === 'skipped') return 'completed'
  if (st === 'failed') return 'error'
  if (st === 'running') return 'running'
  return 'pending'
}

export function planRowsFromExecution(
  execution: WorkflowExecution,
  options?: { skipExecutionPlanTemplate?: boolean }
): WorkflowPlanOutlineRow[] | null {
  const steps = execution.steps
  if (steps && steps.length > 0) {
    return [...steps]
      .sort((a, b) => a.sequence_number - b.sequence_number)
      .map((s) => ({
        id: s.step_id,
        label: s.step_name,
        tool: s.tool_name ? s.tool_name.trim().toLowerCase() : undefined,
        status: mapDbStepStatus(s.status),
      }))
  }
  if (options?.skipExecutionPlanTemplate) {
    return null
  }
  const ep = execution.execution_plan as
    | { steps?: Array<{ id?: string; name?: string; tool_name?: string }> }
    | undefined
  if (ep?.steps?.length) {
    return ep.steps.map((s, i) => ({
      id: String(s.id || `plan_${i + 1}`),
      label: String(s.name || s.id || `Шаг ${i + 1}`),
      tool: s.tool_name ? s.tool_name.trim().toLowerCase() : undefined,
      status: 'pending' as const,
    }))
  }
  return null
}

/** Нормализация статуса из SSE / LangChain (строка, Enum, { value }) */
export function normalizeAgentTodoStatusRaw(raw: unknown): string {
  if (raw == null) return 'pending'
  if (typeof raw === 'string') return raw.trim()
  if (typeof raw === 'object' && raw !== null && 'value' in (raw as object)) {
    return String((raw as { value: unknown }).value ?? '').trim()
  }
  const s = String(raw).trim()
  if (s.includes('.')) return s.split('.').pop()!.trim().toLowerCase()
  return s
}

export function mapAgentTodoStatusToPlan(
  raw: string
): WorkflowPlanOutlineRow['status'] {
  let s = (raw || '').toLowerCase().trim()
  if (s.includes('.')) s = s.split('.').pop() || s
  if (s === 'completed' || s === 'complete' || s === 'done' || s.includes('completed')) {
    return 'completed'
  }
  if (s === 'in_progress' || s === 'running' || s === 'active' || s.includes('progress')) {
    return 'running'
  }
  if (s === 'failed' || s.includes('fail') || s.includes('error') || s.includes('cancel')) {
    return 'error'
  }
  return 'pending'
}

/** Строки плана из потока ``agent_todos_updated`` (настоящий план Deep Agents / write_todos). */
export function agentTodosToPlanRows(todos: WorkflowAgentTodoItem[]): WorkflowPlanOutlineRow[] {
  return todos.map((t, i) => ({
    id: `da_todo_${i}_${String(t.content).slice(0, 48)}`,
    label: t.content,
    tool: undefined,
    status: mapAgentTodoStatusToPlan(t.status),
  }))
}

/** Прогресс 0–100 по доле завершённых подзадач */
export function progressPercentFromAgentTodos(todos: WorkflowAgentTodoItem[]): number {
  if (!todos.length) return 0
  let done = 0
  for (const t of todos) {
    if (mapAgentTodoStatusToPlan(t.status) === 'completed') done += 1
  }
  return Math.max(0, Math.min(100, Math.round((100 * done) / todos.length)))
}

export function mergePlanWithDbSteps(
  rows: WorkflowPlanOutlineRow[],
  dbSteps: WorkflowExecutionStep[]
): WorkflowPlanOutlineRow[] {
  if (!rows.length || !dbSteps?.length) return rows
  return rows.map((row) => {
    const db =
      dbSteps.find((s) => s.step_id === row.id) ||
      dbSteps.find((s) => s.step_name === row.label) ||
      null
    if (!db) return row
    return { ...row, status: mapDbStepStatus(db.status) }
  })
}

export function applyEventToPlanRows(
  rows: WorkflowPlanOutlineRow[],
  eventType: string,
  event: WorkflowEvent
): WorkflowPlanOutlineRow[] {
  if (!rows.length) return rows
  const next = rows.map((r) => ({ ...r }))
  const tool = String(
    (event.data as { tool?: string; selected_tool?: string; tool_name?: string } | undefined)?.tool ||
      (event.data as { selected_tool?: string })?.selected_tool ||
      (event.data as { tool_name?: string })?.tool_name ||
      ''
  )
    .trim()
    .toLowerCase()

  if (eventType === 'step_started') {
    if (tool) {
      const byTool = next.findIndex((r) => r.tool === tool && r.status === 'pending')
      if (byTool >= 0) {
        next[byTool].status = 'running'
        return next
      }
      const byToolRun = next.findIndex((r) => r.tool === tool && r.status === 'running')
      if (byToolRun >= 0) return next
    }
    const pend = next.findIndex((r) => r.status === 'pending')
    if (pend >= 0) next[pend].status = 'running'
    return next
  }

  if (eventType === 'step_completed') {
    const runIdx = next.findIndex((r) => r.status === 'running')
    if (runIdx >= 0) {
      next[runIdx].status = 'completed'
      return next
    }
    if (tool) {
      const idx = next.findIndex((r) => r.tool === tool && r.status !== 'completed' && r.status !== 'error')
      if (idx >= 0) next[idx].status = 'completed'
    }
    return next
  }

  if (eventType === 'step_failed') {
    const runIdx = next.findIndex((r) => r.status === 'running')
    if (runIdx >= 0) next[runIdx].status = 'error'
    else if (tool) {
      const idx = next.findIndex((r) => r.tool === tool)
      if (idx >= 0) next[idx].status = 'error'
    }
    return next
  }

  return next
}

export function extractArtifactTextPreview(artifacts: WorkflowArtifactsPayload): string {
  for (const doc of artifacts.documents || []) {
    const d = doc as Record<string, unknown>
    const t = d.draft_content || d.text || d.content || d.body || d.html
    if (typeof t === 'string' && t.trim().length > 40) {
      return t.trim()
    }
  }
  for (const table of artifacts.tables || []) {
    const t = table as Record<string, unknown>
    const x = t.preview || t.summary_text || t.markdown || t.caption
    if (typeof x === 'string' && x.trim().length > 20) {
      return x.trim()
    }
  }
  return ''
}

export function formatWorkflowFinalMessage(workflowName: string, event: WorkflowEvent): string {
  const resultData = event.data || {}
  const summary =
    typeof resultData.summary === 'string'
      ? resultData.summary
      : typeof (resultData as { results?: { summary?: string } }).results?.summary === 'string'
        ? (resultData as { results?: { summary?: string } }).results!.summary!
        : ''
  const mergedArtifacts = normalizeWorkflowArtifacts(resultData.artifacts, resultData as Record<string, unknown>)
  const nTables = mergedArtifacts.tables?.length || 0
  const nDocuments = mergedArtifacts.documents?.length || 0
  const nReports = mergedArtifacts.reports?.length || 0
  const nChecks = mergedArtifacts.checks?.length || 0
  const totalCards = nTables + nDocuments + nReports + nChecks

  let msg = `✅ Workflow «${workflowName}» завершён.`
  if (summary && summary.trim()) {
    msg += `\n\n${summary.trim()}`
  }
  if (totalCards > 0) {
    const parts: string[] = []
    if (nDocuments) parts.push(`документов: ${nDocuments}`)
    if (nTables) parts.push(`таблиц: ${nTables}`)
    if (nReports) parts.push(`отчётов: ${nReports}`)
    if (nChecks) parts.push(`проверок: ${nChecks}`)
    msg += `\n\n${parts.join(', ')} — откройте карточки ниже.`
  }

  const preview = extractArtifactTextPreview(mergedArtifacts)
  const summaryShort = !summary || summary.trim().length < 100
  if (preview && summaryShort) {
    const cap = 1800
    const clipped = preview.length > cap ? `${preview.slice(0, cap)}…` : preview
    if (!summary || !summary.includes(clipped.slice(0, Math.min(60, clipped.length)))) {
      msg += `\n\n---\n**Фрагмент текста**\n\n${clipped}`
    }
  }

  return msg
}

export function normalizeWorkflowArtifacts(
  raw: unknown,
  envelope?: Record<string, unknown>
): WorkflowArtifactsPayload {
  const primary = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const secondary = (envelope?.artifacts && typeof envelope.artifacts === 'object'
    ? envelope.artifacts
    : {}) as Record<string, unknown>
  const pick = (k: keyof WorkflowArtifactsPayload) => {
    const p = Array.isArray(primary[k as string]) ? (primary[k as string] as unknown[]) : []
    const s = Array.isArray(secondary[k as string]) ? (secondary[k as string] as unknown[]) : []
    return (p.length > 0 ? p : s) as Array<Record<string, unknown>>
  }
  return {
    tables: pick('tables'),
    documents: pick('documents'),
    reports: pick('reports'),
    checks: pick('checks'),
  }
}

export function enrichWorkflowArtifacts(
  raw: WorkflowArtifactsPayload,
  caseId: string | undefined | null
): WorkflowArtifactsPayload {
  if (!caseId) return raw
  const inject = (rows: Array<Record<string, unknown>> | undefined) =>
    (rows || []).map((r) => (r.case_id || r.caseId ? r : { ...r, case_id: caseId }))
  return {
    tables: inject(raw.tables),
    documents: inject(raw.documents),
    reports: inject(raw.reports),
    checks: inject(raw.checks),
  }
}

export function countWorkflowArtifacts(a: WorkflowArtifactsPayload | undefined): number {
  if (!a) return 0
  return (
    (a.tables?.length || 0) +
    (a.documents?.length || 0) +
    (a.reports?.length || 0) +
    (a.checks?.length || 0)
  )
}

export function artifactDisplayName(artifact: Record<string, unknown>, fallback: string): string {
  return String(
    artifact.title ||
      artifact.filename ||
      artifact.name ||
      artifact.document_name ||
      artifact.report_name ||
      artifact.id ||
      fallback
  )
}
