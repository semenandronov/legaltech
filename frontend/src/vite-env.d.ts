/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string
  readonly VITE_GOOGLE_CLIENT_ID?: string
  readonly VITE_GOOGLE_API_KEY?: string
  /** @deprecated use VITE_FEATURE_AGENT_RUNS */
  readonly VITE_AGENT_RUNS_ENABLED?: string
  readonly VITE_FEATURE_LEGAL_CORPUS?: string
  readonly VITE_FEATURE_LEGAL_CORPUS_PAGES?: string
  readonly VITE_FEATURE_COURT_PRACTICE?: string
  readonly VITE_FEATURE_COURT_PRACTICE_PAGES?: string
  readonly VITE_FEATURE_DRAFT_TEMPLATES?: string
  readonly VITE_FEATURE_DRAFT_MODE?: string
  readonly VITE_FEATURE_EDITOR?: string
  readonly VITE_FEATURE_PLAYBOOKS?: string
  readonly VITE_FEATURE_AGENT_RUNS?: string
  readonly VITE_FEATURE_CHUNK_LAB?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

