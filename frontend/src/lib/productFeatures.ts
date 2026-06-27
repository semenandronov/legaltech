/**
 * Product surface flags (build-time via VITE_FEATURE_*).
 *
 * Defaults keep local dev fully enabled. Production VM overlays via `.env.vm-ui`
 * merged at deploy (see scripts/lib/deploy-common.sh).
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

/** Страницы/сайдбар: отдельный флаг *_PAGES, иначе наследует основной. */
function readPagesFlag(
  pagesEnv: string | undefined,
  primaryEnv: string | undefined,
  defaultEnabled: boolean,
): boolean {
  if (pagesEnv !== undefined && pagesEnv !== '') {
    return parseEnvBool(pagesEnv, defaultEnabled)
  }
  return parseEnvBool(primaryEnv, defaultEnabled)
}

export const productFeatures = {
  /** Тумблер «Справочник» в чате (НПА / legal corpus retrieval). */
  legalCorpus: parseEnvBool(import.meta.env.VITE_FEATURE_LEGAL_CORPUS, true),
  /** Страница /legal-corpus и пункт в сайдбаре. */
  legalCorpusPages: readPagesFlag(
    import.meta.env.VITE_FEATURE_LEGAL_CORPUS_PAGES,
    import.meta.env.VITE_FEATURE_LEGAL_CORPUS,
    true,
  ),
  /** Тумблер «Суд. практика» в чате. */
  courtPractice: parseEnvBool(import.meta.env.VITE_FEATURE_COURT_PRACTICE, true),
  /** Страница /court-practice и пункт в сайдбаре. */
  courtPracticePages: readPagesFlag(
    import.meta.env.VITE_FEATURE_COURT_PRACTICE_PAGES,
    import.meta.env.VITE_FEATURE_COURT_PRACTICE,
    true,
  ),
  /** Админ-страница шаблонов Draft. */
  draftTemplates: parseEnvBool(import.meta.env.VITE_FEATURE_DRAFT_TEMPLATES, true),
  /** Режим Draft в ассистентах (внутренний и глобальный). */
  draftMode: parseEnvBool(import.meta.env.VITE_FEATURE_DRAFT_MODE, true),
  /** Редактор документов по делу. */
  editor: parseEnvBool(import.meta.env.VITE_FEATURE_EDITOR, true),
  /** Playbooks по делу. */
  playbooks: parseEnvBool(import.meta.env.VITE_FEATURE_PLAYBOOKS, true),
  /** Workflows / agent runs: страница, карточки, баннеры, сценарии на лендинге. */
  agentRuns: readAgentRunsFlag(),
  /** Chunk lab (внутренний dev-tool, маршрут /chunk-lab). */
  chunkLab: parseEnvBool(import.meta.env.VITE_FEATURE_CHUNK_LAB, true),
} as const

export type ProductFeatureKey = keyof typeof productFeatures

export function isProductFeatureEnabled(key: ProductFeatureKey): boolean {
  return productFeatures[key]
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
