import type { ThinkingStep } from '../components/Chat/ThinkingBlock'

export type AssistantActivityStatus = 'pending' | 'running' | 'completed' | 'error'

export interface AssistantActivityPayload {
  type?: 'assistant_activity'
  step_id?: string
  phase?: string
  step?: number
  totalSteps?: number
  label?: string
  detail?: string
  content?: string
  status?: AssistantActivityStatus
}

function composeContent(data: AssistantActivityPayload): string {
  if (typeof data.content === 'string' && data.content.trim()) {
    return data.content.trim()
  }
  const label = (data.label || '').trim()
  const detail = (data.detail || '').trim()
  if (label && detail) return `${label}: ${detail}`
  return label || detail
}

/** Upsert activity step by stable step_id (mapped to ThinkingStep.phase). */
export function applyAssistantActivityEvent(
  steps: ThinkingStep[],
  data: AssistantActivityPayload,
): ThinkingStep[] {
  const stepKey = String(data.step_id || data.phase || '').trim()
  if (!stepKey) return steps

  const nextStep: ThinkingStep = {
    phase: stepKey,
    step: typeof data.step === 'number' ? data.step : steps.length + 1,
    totalSteps: typeof data.totalSteps === 'number' ? data.totalSteps : 6,
    content: composeContent(data),
    status: data.status || 'running',
  }

  let merged = [...steps]
  const idx = merged.findIndex((s) => s.phase === stepKey)
  if (idx >= 0) {
    merged[idx] = { ...merged[idx], ...nextStep }
  } else {
    merged = [...merged, nextStep]
  }

  // Завершаем предыдущие этапы, когда пришёл более поздний шаг.
  if (nextStep.status === 'completed' || nextStep.status === 'running') {
    merged = merged.map((s) => {
      if (s.phase === stepKey) return s
      if (s.status === 'running' && s.step < nextStep.step) {
        return { ...s, status: 'completed' as const }
      }
      return s
    })
  }

  return merged.sort((a, b) => a.step - b.step)
}

/** Legacy reasoning SSE — same upsert semantics when phase is stable. */
export function applyReasoningEvent(
  steps: ThinkingStep[],
  data: {
    phase?: string
    step?: number
    totalSteps?: number
    content?: string
    status?: AssistantActivityStatus
  },
): ThinkingStep[] {
  const phase = String(data.phase || '').trim()
  if (!phase || !data.content) return steps

  const nextStep: ThinkingStep = {
    phase,
    step: data.step ?? steps.length + 1,
    totalSteps: data.totalSteps ?? 4,
    content: data.content,
    status: data.status || 'running',
  }

  const idx = steps.findIndex(
    (s) => s.phase === nextStep.phase && s.step === nextStep.step,
  )
  if (idx >= 0) {
    const updated = [...steps]
    updated[idx] = { ...updated[idx], ...nextStep }
    return updated
  }
  return [...steps, nextStep]
}
