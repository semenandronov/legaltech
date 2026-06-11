import { describe, expect, it } from 'vitest'
import { applyAgentRunEvent, createEmptyAgentRunSlice } from './agentRunStream'
import type { AgentRunStreamEvent } from '../services/agentRunsApi'

describe('applyAgentRunEvent', () => {
  it('accumulates text deltas and tool calls', () => {
    let slice = createEmptyAgentRunSlice('run-1')
    const started: AgentRunStreamEvent = {
      type: 'tool_started',
      run_id: 'run-1',
      data: { tool: 'agent_tabular_review', params_preview: { review_name: 'Test' } },
    }
    slice = applyAgentRunEvent(slice, started)
    expect(slice.toolCalls).toHaveLength(1)
    expect(slice.toolCalls[0].status).toBe('running')

    const delta: AgentRunStreamEvent = {
      type: 'text_delta',
      run_id: 'run-1',
      data: { text: 'Готово' },
    }
    slice = applyAgentRunEvent(slice, delta)
    expect(slice.content).toBe('Готово')
  })
})
