import { productFeatures } from '@/lib/productFeatures'

/** Feature flag: deep agent runs (Legora-style orchestration). */
export function agentRunsEnabled(): boolean {
  return productFeatures.agentRuns
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
