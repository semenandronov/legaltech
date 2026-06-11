/** Feature flag: deep agent runs (Legora-style orchestration). */
export function agentRunsEnabled(): boolean {
  const raw = import.meta.env.VITE_AGENT_RUNS_ENABLED
  if (raw === undefined || raw === '') return false
  return String(raw).toLowerCase() === 'true'
}

export function canEnableDeepAgentMode(
  draftMode: boolean,
  legalResearch: boolean,
  courtPractice: boolean,
): boolean {
  return agentRunsEnabled() && !draftMode && !legalResearch && !courtPractice
}

export function canSelectDeepAgentMode(legalResearch: boolean, courtPractice: boolean): boolean {
  return agentRunsEnabled() && !legalResearch && !courtPractice
}
