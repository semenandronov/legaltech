/**
 * Product surface flags (build-time via VITE_FEATURE_*).
 *
 * Defaults: chat instruments (legal corpus, court practice, draft) on; pages/sidebar off.
 * Production VM overlays via `.env.vm-ui` merged at deploy (see scripts/lib/deploy-common.sh).
 */

function parseEnvBool(value: string | undefined, defaultEnabled: boolean): boolean {
  if (value === undefined || value === '') return defaultEnabled
  const normalized = value.trim().toLowerCase()
  if (normalized === 'true' || normalized === '1' || normalized === 'yes') return true
  if (normalized === 'false' || normalized === '0' || normalized === 'no') return false
  return defaultEnabled
}

function readAgentRunsFlag(): boolean {
  const primary = import.meta.env.VITE_FEATURE_AGENT_RUNS
  if (primary !== undefined && primary !== '') {
    return parseEnvBool(primary, false)
  }
  return parseEnvBool(import.meta.env.VITE_AGENT_RUNS_ENABLED, false)
}

export const productFeatures = {
  /** Страница /assistant и пункт «Ассистент» в главном меню. */
  globalAssistant: parseEnvBool(import.meta.env.VITE_FEATURE_GLOBAL_ASSISTANT, false),
  /**
   * Внутренний ассистент по делу: /cases/:id/chat, карточка на обзоре,
   * сессии в истории и редиректы «открыть дело → чат».
   */
  caseAssistant: parseEnvBool(import.meta.env.VITE_FEATURE_CASE_ASSISTANT, false),
  /**
   * Чат «Ассистент» на странице Операций (кнопка в шапке + боковая панель).
   * По умолчанию включён — agent-first разбор выписки.
   */
  operationsAssistant: parseEnvBool(import.meta.env.VITE_FEATURE_OPERATIONS_ASSISTANT, true),
  /** Страница /cases/:id/operations и входы в неё из интерфейса. */
  operationsPage: parseEnvBool(import.meta.env.VITE_FEATURE_OPERATIONS_PAGE, false),
  /** Тумблер «Справочник» в чате (НПА / legal corpus retrieval). */
  legalCorpus: parseEnvBool(import.meta.env.VITE_FEATURE_LEGAL_CORPUS, true),
  /** Страница /legal-corpus и пункт в сайдбаре (отдельно от тумблера в чате). */
  legalCorpusPages: parseEnvBool(import.meta.env.VITE_FEATURE_LEGAL_CORPUS_PAGES, false),
  /** Тумблер «Суд. практика» в чате. */
  courtPractice: parseEnvBool(import.meta.env.VITE_FEATURE_COURT_PRACTICE, true),
  /** Страница /court-practice и пункт в сайдбаре. */
  courtPracticePages: parseEnvBool(import.meta.env.VITE_FEATURE_COURT_PRACTICE_PAGES, false),
  /** Админ-страница шаблонов Draft и пункт в сайдбаре. */
  draftTemplates: parseEnvBool(import.meta.env.VITE_FEATURE_DRAFT_TEMPLATES, false),
  /** Режим Draft в ассистентах (внутренний и глобальный). */
  draftMode: parseEnvBool(import.meta.env.VITE_FEATURE_DRAFT_MODE, true),
  /** Редактор документов по делу. */
  editor: parseEnvBool(import.meta.env.VITE_FEATURE_EDITOR, false),
  /** Playbooks по делу. */
  playbooks: parseEnvBool(import.meta.env.VITE_FEATURE_PLAYBOOKS, false),
  /** Workflows / agent runs: страница, карточки, баннеры, сценарии на лендинге. */
  agentRuns: readAgentRunsFlag(),
  /** Chunk lab (внутренний dev-tool, маршрут /chunk-lab). */
  chunkLab: parseEnvBool(import.meta.env.VITE_FEATURE_CHUNK_LAB, false),
} as const

export type ProductFeatureKey = keyof typeof productFeatures

export function isProductFeatureEnabled(key: ProductFeatureKey): boolean {
  return productFeatures[key]
}

/** Куда вести при открытии дела: чат (если включён) или обзор. */
export function caseHomePath(caseId: string): string {
  return productFeatures.caseAssistant ? `/cases/${caseId}/chat` : `/cases/${caseId}`
}

/** Есть ли хотя бы один переключаемый инструмент в настройках чата. */
export function chatInstrumentControlsEnabled(): boolean {
  return (
    productFeatures.draftMode ||
    productFeatures.legalCorpus ||
    productFeatures.courtPractice
  )
}

export function chatHasActiveInstruments(state: {
  draftMode: boolean
  legalResearch: boolean
  courtPractice: boolean
}): boolean {
  return (
    (productFeatures.draftMode && state.draftMode) ||
    (productFeatures.legalCorpus && state.legalResearch) ||
    (productFeatures.courtPractice && state.courtPractice)
  )
}
