import { useEffect } from 'react'
import { toast } from 'sonner'
import type { SourceInfo } from '../services/api'
import {
  streamWorkflowEvents,
  releaseWorkflowEventStream,
  getExecution,
  getExecutionResults,
  type WorkflowEvent,
} from '../services/workflowsApi'
import type { WorkflowAgentTodoItem, WorkflowPlanOutlineRow } from '../components/Chat/ThinkingBlock'

export type { WorkflowAgentTodoItem } from '../components/Chat/ThinkingBlock'
import {
  type WorkflowLiveContext,
  type WorkflowArtifactsPayload,
  mergePlanWithDbSteps,
  applyEventToPlanRows,
  planRowsFromExecution,
  enrichWorkflowArtifacts,
  normalizeWorkflowArtifacts,
  formatWorkflowFinalMessage,
  agentTodosToPlanRows,
  progressPercentFromAgentTodos,
  normalizeAgentTodoStatusRaw,
} from './workflowLiveHelpers'

const SUCCESS_SPAM = /workflow.*успешн|успешн.*workflow|завершён.*workflow|workflow.*заверш/i

function looksLikeDuplicateSuccess(prevContent: string | undefined, msg: string): boolean {
  if (!prevContent || !msg) return false
  if (prevContent === msg) return true
  if (SUCCESS_SPAM.test(prevContent) && SUCCESS_SPAM.test(msg)) return true
  return false
}

export interface WorkflowLiveChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: SourceInfo[]
  reasoningSteps?: Array<{
    phase: string
    step: number
    totalSteps: number
    content: string
    status?: 'pending' | 'running' | 'completed' | 'error'
    toolName?: string
  }>
  workflowArtifacts?: WorkflowArtifactsPayload
  workflowProgressPercent?: number
  workflowStatus?: 'running' | 'completed' | 'failed'
  workflowPlanOutline?: WorkflowPlanOutlineRow[]
  /** Подзадачи агента (LangChain write_todos), отдельно от плана workflow */
  workflowAgentTodos?: WorkflowAgentTodoItem[]
  /** План из потока Deep Agents (todo) vs шаблон/БД */
  workflowPlanSource?: 'deepagents' | 'definition'
}

export function useWorkflowLiveExecution(options: {
  locationSearch: string
  setMessages: React.Dispatch<React.SetStateAction<WorkflowLiveChatMessage[]>>
  setIsStreaming: (v: boolean) => void
  /** Вызывается при старте: куда вести из артефактов */
  onReturnPath: (path: string) => void
  /** Если в контексте нет return_chat_path */
  defaultReturnChatPath: string
}): void {
  const { locationSearch, setMessages, setIsStreaming, onReturnPath, defaultReturnChatPath } = options

  useEffect(() => {
    const params = new URLSearchParams(locationSearch)
    const executionId = params.get('workflow_execution_id')
    if (!executionId) {
      return
    }
    let cancelled = false
    const rawContext = localStorage.getItem('pending_workflow_live_run')
    let ctx: WorkflowLiveContext | null = null
    if (rawContext) {
      try {
        ctx = JSON.parse(rawContext) as WorkflowLiveContext
      } catch {
        ctx = null
      }
    }

    const returnPath = ctx?.return_chat_path || defaultReturnChatPath
    onReturnPath(returnPath)

    const workflowName = ctx?.workflow_name || 'Workflow'
    const stepMeta = new Map<string, { name: string; tool?: string }>()
    const liveEventSteps: Array<{
      phase: string
      step: number
      totalSteps: number
      content: string
      status?: 'pending' | 'running' | 'completed' | 'error'
      toolName?: string
    }> = []
    const workflowSourcesMap = new Map<string, SourceInfo>()
    let workflowProgress = 0
    let workflowStatus: 'running' | 'completed' | 'failed' = 'running'
    let finalizationCommitted = false
    const getLastAssistantIndex = (items: WorkflowLiveChatMessage[]): number => {
      for (let i = items.length - 1; i >= 0; i -= 1) {
        if (items[i].role === 'assistant') return i
      }
      return -1
    }
    const normalizeEventType = (raw?: string): string => {
      const base = String(raw || '').trim().toLowerCase()
      if (!base) return 'status'
      if (base === 'error') return 'failed'
      if (base === 'complete') return 'completed'
      return base
    }
    const getEventType = (event: WorkflowEvent): string => normalizeEventType(event.type || event.event_type)
    const commitFinalizationOnce = (): boolean => {
      if (finalizationCommitted) return false
      finalizationCommitted = true
      return true
    }

    /** Настоящий план из write_todos / SSE; не перезаписывать шаблоном из БД */
    let deepAgentsPlanLocked = false
    let workflowPlanSource: 'deepagents' | 'definition' | undefined
    let planOutlineRows: WorkflowPlanOutlineRow[] = []
    let planHydratedFromApi = false

    const withPlanOutline = (msg: WorkflowLiveChatMessage): WorkflowLiveChatMessage => {
      const outline = planOutlineRows.length > 0 ? planOutlineRows.map((r) => ({ ...r })) : undefined
      return {
        ...msg,
        workflowPlanOutline: outline,
        workflowPlanSource: outline ? workflowPlanSource : undefined,
        workflowAgentTodos: workflowPlanSource === 'deepagents' ? undefined : msg.workflowAgentTodos,
      }
    }

    const normalizeAgentTodos = (raw: unknown): WorkflowAgentTodoItem[] => {
      if (!Array.isArray(raw)) return []
      const out: WorkflowAgentTodoItem[] = []
      for (const item of raw) {
        if (item && typeof item === 'object' && 'content' in item) {
          const o = item as Record<string, unknown>
          const content = String(o.content ?? '').trim()
          if (!content) continue
          out.push({
            content,
            status: normalizeAgentTodoStatusRaw(o.status),
          })
        }
      }
      return out.slice(0, 48)
    }

    const appendWorkflowSources = (event: WorkflowEvent) => {
      const candidates: unknown[] = []
      const pushSourceLike = (value: unknown) => {
        if (value && typeof value === 'object') candidates.push(value)
      }

      pushSourceLike(event.data?.source)
      if (Array.isArray(event.data?.sources)) event.data.sources.forEach(pushSourceLike)
      if (Array.isArray(event.data?.citations)) event.data.citations.forEach(pushSourceLike)
      pushSourceLike((event.data as { result?: { source?: unknown } })?.result?.source)
      const res = event.data as { result?: { sources?: unknown[]; citations?: unknown[] } } | undefined
      if (Array.isArray(res?.result?.sources)) res!.result!.sources!.forEach(pushSourceLike)
      if (Array.isArray(res?.result?.citations)) res!.result!.citations!.forEach(pushSourceLike)

      candidates.forEach((src, idx) => {
        const s = src as Record<string, unknown>
        const normalized: SourceInfo = {
          file: (s.file_name || s.file || s.title) as string,
          title: (s.title || s.file_name || s.file || 'Источник') as string,
          page: (s.page as number | undefined) ?? undefined,
          text_preview: (s.quote_anchor || s.quote || s.text_preview || s.snippet || '') as string,
          source_id: (s.source_id || s.id) as string | undefined,
          quote: (s.quote || s.quote_anchor || s.text_preview) as string | undefined,
          quote_anchor: (s.quote_anchor || s.quote) as string | undefined,
          char_start: s.char_start as number | undefined,
          char_end: s.char_end as number | undefined,
          url: (s.url || '') as string,
          source_type: (s.source_type || 'document') as string,
          case_id: (s.case_id as string | undefined) || undefined,
        }
        const key = `${normalized.source_id || normalized.title || 'src'}:${normalized.page || ''}:${idx}`
        workflowSourcesMap.set(key, normalized)
      })
    }

    const buildReasoningSteps = () => [...liveEventSteps].slice(-40)

    const appendLiveReasoning = (event: WorkflowEvent) => {
      const eventType = getEventType(event)
      if (eventType === 'status' && !event.message && !event.data?.status_message) {
        return
      }
      if (
        workflowPlanSource !== 'deepagents' &&
        planOutlineRows.length > 0 &&
        (eventType === 'step_started' || eventType === 'step_completed')
      ) {
        return
      }
      const data = event.data || {}
      const toolName = (data.tool || data.selected_tool || data.tool_name) as string | undefined
      const summary = (data.summary || data.output_summary || data.error || data.reason) as string | undefined
      const decisionReason = (data.decision_reason || data.message) as string | undefined
      const stepId = event.step_id || ''
      const stepTitle = stepMeta.get(stepId)?.name || event.step_name || stepId || 'этап'
      const stepTool = toolName || stepMeta.get(stepId)?.tool

      const fallbackByType: Record<string, string> = {
        started: 'Workflow запущен',
        status: 'Статус workflow обновлен',
        planning: 'Агент планирует выполнение',
        planning_started: 'DeepAgents: старт исполнения',
        review_iteration_started: 'Итерация проверки качества',
        review_iteration_failed: 'Проверка качества: нужна переработка',
        review_iteration_passed: 'Проверка качества: шаг пройден',
        agent_todos_updated: 'Подзадачи агента обновлены',
        completed: 'Workflow завершен',
        completed_with_errors: 'Workflow завершён с предупреждениями (проверьте результат)',
        failed: 'Workflow завершился с ошибкой',
      }

      const dynamicText =
        eventType === 'tool_reasoned'
          ? `Агент выбрал инструмент${stepTool ? `: ${stepTool}` : ''}${decisionReason ? ` — ${decisionReason}` : ''}`
          : eventType === 'step_started'
            ? `Начал этап: ${stepTitle}${stepTool ? ` (tool: ${stepTool})` : ''}`
            : eventType === 'step_completed'
              ? `Завершил этап: ${stepTitle}${summary ? ` — ${String(summary).slice(0, 220)}` : ''}`
              : eventType === 'step_failed'
                ? `Ошибка на этапе: ${stepTitle}${summary ? ` — ${String(summary).slice(0, 220)}` : ''}`
                : (event.message || fallbackByType[eventType] || `Событие: ${eventType}`)

      let msg = String(dynamicText || '').trim()
      if (!msg) return
      if (msg.includes('__stream_lock__')) return

      const prev = liveEventSteps[liveEventSteps.length - 1]
      if (prev && prev.content === msg && prev.phase === eventType) {
        return
      }
      if (prev && looksLikeDuplicateSuccess(prev.content, msg)) {
        return
      }
      // Сжимаем повторяющиеся «валидация успешна» при quality gates
      if (
        eventType === 'step_completed' &&
        typeof summary === 'string' &&
        SUCCESS_SPAM.test(summary) &&
        prev &&
        SUCCESS_SPAM.test(prev.content)
      ) {
        return
      }

      const next = {
        phase: eventType || 'workflow_event',
        step: liveEventSteps.length + 1,
        totalSteps: liveEventSteps.length + 1,
        content: msg,
        status: (
          eventType === 'completed'
            ? 'completed'
            : eventType === 'failed' || eventType === 'step_failed'
              ? 'error'
              : eventType === 'step_completed'
                ? 'completed'
                : 'running'
        ) as 'completed' | 'error' | 'running' | 'pending',
        toolName: stepTool,
      }
      const maxSteps = 30
      liveEventSteps.push(next)
      const merged = buildReasoningSteps().slice(-maxSteps)
      setMessages((prevMsgs) => {
        const nextMsgs = [...prevMsgs]
        const assistantIdx = getLastAssistantIndex(nextMsgs)
        if (assistantIdx >= 0) {
          nextMsgs[assistantIdx] = withPlanOutline({
            ...nextMsgs[assistantIdx],
            reasoningSteps: merged,
            workflowProgressPercent: workflowProgress,
            workflowStatus,
          })
        }
        return nextMsgs
      })
    }

    setMessages([
      withPlanOutline({
        role: 'assistant',
        content: '',
        reasoningSteps: [
          {
            phase: 'workflow_bootstrap',
            step: 1,
            totalSteps: 1,
            content: `Подключение к потоку выполнения workflow "${workflowName}"...`,
            status: 'running',
          },
        ],
        workflowProgressPercent: 0,
        workflowStatus: 'running',
      }),
    ])

    const run = async () => {
      setIsStreaming(true)
      let sawTerminalEvent = false
      const startedAt = Date.now()
      let lastSseAt = Date.now()
      let pollingLocked = false
      const heartbeat = window.setInterval(() => {
        if (cancelled || sawTerminalEvent) return
        if (planOutlineRows.length > 0) return
        const elapsedSec = Math.max(1, Math.floor((Date.now() - startedAt) / 1000))
        setMessages((prev) => {
          const next = [...prev]
          const assistantIdx = getLastAssistantIndex(next)
          if (assistantIdx < 0) return prev
          const current = next[assistantIdx]
          const steps = [...(current.reasoningSteps || [])]
          const hbIdx = steps.findIndex((s) => s.phase === 'workflow_heartbeat')
          const bsIdx = steps.findIndex((s) => s.phase === 'workflow_bootstrap')
          if (bsIdx >= 0) {
            steps[bsIdx] = { ...steps[bsIdx], status: 'completed' as const }
          }
          const hbStep = {
            phase: 'workflow_heartbeat',
            step: steps.length + 1,
            totalSteps: steps.length + 1,
            content: `Агент выполняет этап... ${elapsedSec}с`,
            status: 'running' as const,
          }
          if (hbIdx >= 0) steps[hbIdx] = hbStep
          else steps.push(hbStep)
          next[assistantIdx] = withPlanOutline({
            ...current,
            reasoningSteps: steps.slice(-40),
            workflowStatus: 'running',
            workflowProgressPercent: current.workflowProgressPercent ?? workflowProgress,
          })
          return next
        })
      }, 2000)
      const polling = window.setInterval(async () => {
        if (cancelled || sawTerminalEvent || pollingLocked) return
        const sseSilenceMsEarly = Date.now() - lastSseAt
        // When SSE is healthy, avoid redundant polling load.
        if (sseSilenceMsEarly < 15000) return
        pollingLocked = true
        try {
          const execution = await getExecution(executionId)
          if (!deepAgentsPlanLocked && !planOutlineRows.length && !planHydratedFromApi) {
            const fromApi = planRowsFromExecution(execution, { skipExecutionPlanTemplate: true })
            if (fromApi?.length) {
              planOutlineRows = fromApi
              planHydratedFromApi = true
              workflowPlanSource = 'definition'
            }
          }
          if (
            workflowPlanSource !== 'deepagents' &&
            planOutlineRows.length &&
            execution.steps &&
            execution.steps.length > 0
          ) {
            planOutlineRows = mergePlanWithDbSteps(planOutlineRows, execution.steps)
          }
          const polledProgress = Number(execution.progress_percent ?? execution.progress ?? workflowProgress)
          if (!Number.isNaN(polledProgress)) {
            workflowProgress = Math.max(0, Math.min(100, Math.round(polledProgress)))
          }

          const polledStatus = normalizeEventType(execution.status)
          if (polledStatus === 'completed') workflowStatus = 'completed'
          else if (['failed', 'cancelled', 'completed_with_errors'].includes(polledStatus)) workflowStatus = 'failed'
          else workflowStatus = 'running'

          if (workflowStatus === 'running') {
            setMessages((prev) => {
              const next = [...prev]
              const assistantIdx = getLastAssistantIndex(next)
              if (assistantIdx < 0) return prev
              next[assistantIdx] = withPlanOutline({
                ...next[assistantIdx],
                workflowProgressPercent: workflowProgress,
                workflowStatus,
              })
              return next
            })
          }

          const statusMessage = (execution.status_message || '').trim()
          const sseSilenceMs = Date.now() - lastSseAt
          if (statusMessage && !statusMessage.includes('__stream_lock__') && sseSilenceMs > 15000) {
            const nextStep = {
              phase: 'workflow_poll_status',
              step: liveEventSteps.length + 1,
              totalSteps: liveEventSteps.length + 1,
              content: `Статус: ${statusMessage}`,
              status: (workflowStatus === 'failed' ? 'error' : 'running') as 'running' | 'error',
            }
            const existingIdx = liveEventSteps.findIndex((s) => s.phase === 'workflow_poll_status')
            if (existingIdx >= 0) liveEventSteps[existingIdx] = nextStep
            else liveEventSteps.push(nextStep)
            setMessages((prev) => {
              const next = [...prev]
              const assistantIdx = getLastAssistantIndex(next)
              if (assistantIdx < 0) return prev
              next[assistantIdx] = withPlanOutline({
                ...next[assistantIdx],
                reasoningSteps: buildReasoningSteps(),
                workflowProgressPercent: workflowProgress,
                workflowStatus,
              })
              return next
            })
          }

          if (workflowStatus !== 'running') {
            if (!commitFinalizationOnce()) return
            sawTerminalEvent = true
            try {
              const results = await getExecutionResults(executionId)
              const caseIdForArtifacts = execution.case_id || ctx?.case_id
              const normalizedArtifacts = enrichWorkflowArtifacts(
                normalizeWorkflowArtifacts(results.artifacts, results as Record<string, unknown>),
                caseIdForArtifacts
              )
              const syntheticCompleted: WorkflowEvent = {
                type: workflowStatus === 'failed' ? 'failed' : 'completed',
                execution_id: executionId,
                timestamp: new Date().toISOString(),
                message: workflowStatus === 'failed' ? 'Workflow завершился с ошибкой' : 'Workflow завершен',
                progress_percent: workflowStatus === 'failed' ? workflowProgress : 100,
                data: {
                  summary: results.summary || '',
                  artifacts: normalizedArtifacts,
                  error: workflowStatus === 'failed' ? (results as { error_message?: string })?.error_message : undefined,
                },
              }
              setMessages((prev) => {
                const next = [...prev]
                const assistantIdx = getLastAssistantIndex(next)
                if (assistantIdx < 0) return prev
                next[assistantIdx] = withPlanOutline({
                  ...next[assistantIdx],
                  content:
                    workflowStatus === 'failed'
                      ? `❌ Workflow "${workflowName}" завершился с ошибкой.`
                      : formatWorkflowFinalMessage(workflowName, syntheticCompleted),
                  reasoningSteps: buildReasoningSteps(),
                  sources: Array.from(workflowSourcesMap.values()),
                  workflowArtifacts: normalizedArtifacts,
                  workflowProgressPercent: workflowStatus === 'failed' ? workflowProgress : 100,
                  workflowStatus,
                })
                return next
              })
            } catch {
              /* stream handler fallback */
            }
          }
        } catch {
          /* polling optional */
        } finally {
          pollingLocked = false
        }
      }, 10000)
      try {
        for await (const event of streamWorkflowEvents(executionId)) {
          if (cancelled) break
          const eventType = getEventType(event)
          lastSseAt = Date.now()
          const eventProgress = Number(event.progress_percent ?? event.progress ?? workflowProgress)
          if (!Number.isNaN(eventProgress)) {
            workflowProgress = Math.max(0, Math.min(100, Math.round(eventProgress)))
          }
          if (eventType === 'step_started' && event.step_id) {
            const eventTool = (event.data?.tool || event.data?.selected_tool || event.data?.tool_name) as
              | string
              | undefined
            const eventStepName = (event.step_name || event.data?.step_name || event.step_id) as string
            stepMeta.set(event.step_id, { name: eventStepName, tool: eventTool })
          }
          if (workflowPlanSource !== 'deepagents') {
            planOutlineRows = applyEventToPlanRows(planOutlineRows, eventType, event)
          }
          if (eventType === 'agent_todos_updated') {
            const todos = normalizeAgentTodos(event.data?.todos)
            if (todos.length > 0) {
              deepAgentsPlanLocked = true
              workflowPlanSource = 'deepagents'
              planOutlineRows = agentTodosToPlanRows(todos)
              const fromTodos = progressPercentFromAgentTodos(todos)
              workflowProgress = Math.max(workflowProgress, fromTodos, eventProgress || 0)
              setMessages((prev) => {
                const next = [...prev]
                const assistantIdx = getLastAssistantIndex(next)
                if (assistantIdx < 0) return prev
                next[assistantIdx] = withPlanOutline({
                  ...next[assistantIdx],
                  workflowProgressPercent: workflowProgress,
                  workflowStatus,
                })
                return next
              })
            }
          }
          if (
            planOutlineRows.length > 0 &&
            (eventType === 'step_started' || eventType === 'step_completed' || eventType === 'step_failed')
          ) {
            setMessages((prev) => {
              const next = [...prev]
              const assistantIdx = getLastAssistantIndex(next)
              if (assistantIdx < 0) return prev
              next[assistantIdx] = withPlanOutline(next[assistantIdx])
              return next
            })
          }
          appendWorkflowSources(event)
          if (eventType !== 'agent_todos_updated') {
            appendLiveReasoning(event)
          }

          if (eventType === 'completed' || eventType === 'completed_with_errors') {
            if (!commitFinalizationOnce()) break
            sawTerminalEvent = true
            workflowStatus = 'completed'
            if (planOutlineRows.length > 0) {
              planOutlineRows = planOutlineRows.map((r) =>
                r.status === 'error' ? r : { ...r, status: 'completed' as const }
              )
            }
            const caseIdForArtifacts =
              ctx?.case_id || (event.data as { case_id?: string } | undefined)?.case_id
            const normalizedArtifacts = enrichWorkflowArtifacts(
              normalizeWorkflowArtifacts(event.data?.artifacts, event.data as Record<string, unknown>),
              caseIdForArtifacts
            )
            const qgWarn = eventType === 'completed_with_errors'
            setMessages((prev) => {
              const next = [...prev]
              const assistantIdx = getLastAssistantIndex(next)
              if (assistantIdx >= 0) {
                const baseContent = formatWorkflowFinalMessage(workflowName, event)
                next[assistantIdx] = withPlanOutline({
                  ...next[assistantIdx],
                  content: qgWarn
                    ? `${baseContent}\n\n⚠️ Автопроверка quality gates не пройдена; проверьте документ вручную.`
                    : baseContent,
                  reasoningSteps: buildReasoningSteps(),
                  sources: Array.from(workflowSourcesMap.values()),
                  workflowArtifacts: normalizedArtifacts,
                  workflowProgressPercent: 100,
                  workflowStatus: 'completed',
                })
              }
              return next
            })
            if (qgWarn) {
              toast.warning(`Workflow "${workflowName}" завершён: требуется проверка (quality gates)`)
            } else {
              toast.success(`Workflow "${workflowName}" завершен`)
            }
            break
          }
          if (eventType === 'failed') {
            if (!commitFinalizationOnce()) break
            sawTerminalEvent = true
            workflowStatus = 'failed'
            if (planOutlineRows.length > 0) {
              planOutlineRows = planOutlineRows.map((r) =>
                r.status === 'running' ? { ...r, status: 'error' as const } : r
              )
            }
            setMessages((prev) => {
              const next = [...prev]
              const assistantIdx = getLastAssistantIndex(next)
              if (assistantIdx >= 0) {
                next[assistantIdx] = withPlanOutline({
                  ...next[assistantIdx],
                  content: `❌ Workflow "${workflowName}" завершился с ошибкой: ${event.data?.error || event.message || 'Неизвестная ошибка'}`,
                  reasoningSteps: buildReasoningSteps(),
                  sources: Array.from(workflowSourcesMap.values()),
                  workflowProgressPercent: workflowProgress,
                  workflowStatus: 'failed',
                })
              }
              return next
            })
            toast.error(`Workflow "${workflowName}" завершился с ошибкой`)
            break
          }
        }
        if (!cancelled && !sawTerminalEvent) {
          try {
            if (!commitFinalizationOnce()) return
            const results = await getExecutionResults(executionId)
            const execBrief = await getExecution(executionId)
            const caseIdForArtifacts = execBrief.case_id || ctx?.case_id
            const normalizedArtifacts = enrichWorkflowArtifacts(
              normalizeWorkflowArtifacts(results.artifacts, results as Record<string, unknown>),
              caseIdForArtifacts
            )
            const syntheticCompleted: WorkflowEvent = {
              type: 'completed',
              execution_id: executionId,
              timestamp: new Date().toISOString(),
              message: 'Workflow завершен',
              progress_percent: 100,
              data: {
                summary: results.summary || '',
                artifacts: normalizedArtifacts,
              },
            }
            if (planOutlineRows.length > 0 && results.status !== 'failed') {
              planOutlineRows = planOutlineRows.map((r) =>
                r.status === 'error' ? r : { ...r, status: 'completed' as const }
              )
            }
            setMessages((prev) => {
              const next = [...prev]
              const assistantIdx = getLastAssistantIndex(next)
              if (assistantIdx >= 0) {
                next[assistantIdx] = withPlanOutline({
                  ...next[assistantIdx],
                  content: formatWorkflowFinalMessage(workflowName, syntheticCompleted),
                  reasoningSteps: buildReasoningSteps(),
                  sources: Array.from(workflowSourcesMap.values()),
                  workflowArtifacts: normalizedArtifacts,
                  workflowProgressPercent: 100,
                  workflowStatus: results.status === 'failed' ? 'failed' : 'completed',
                })
              }
              return next
            })
          } catch {
            setMessages((prev) => {
              const next = [...prev]
              const assistantIdx = getLastAssistantIndex(next)
              if (assistantIdx >= 0) {
                next[assistantIdx] = withPlanOutline({
                  ...next[assistantIdx],
                  content:
                    'Workflow завершил выполнение на сервере, но финальные события не были получены. Обновите страницу истории/результатов.',
                  workflowStatus: 'failed',
                })
              }
              return next
            })
          }
        }
      } finally {
        window.clearInterval(heartbeat)
        window.clearInterval(polling)
        localStorage.removeItem('pending_workflow_live_run')
        setIsStreaming(false)
      }
    }

    void run()

    return () => {
      cancelled = true
      releaseWorkflowEventStream(executionId)
    }
  }, [locationSearch, setMessages, setIsStreaming, onReturnPath, defaultReturnChatPath])
}
