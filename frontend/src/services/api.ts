import axios, { AxiosError, AxiosRequestConfig } from 'axios'
import { logger } from '../lib/logger'

const BASE_URL = import.meta.env.VITE_API_URL || ''

// Error types
export interface ApiError {
  message: string
  status?: number
  detail?: string | Array<{ loc?: string[]; msg?: string }>
  code?: string
}

export class ApiException extends Error {
  status?: number
  detail?: string | Array<{ loc?: string[]; msg?: string }>
  code?: string

  constructor(message: string, status?: number, detail?: string | Array<{ loc?: string[]; msg?: string }>, code?: string) {
    super(message)
    this.name = 'ApiException'
    this.status = status
    this.detail = detail
    this.code = code
  }
}

// Helper to extract error message from axios error
export const extractErrorMessage = (error: unknown): string => {
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<{ detail?: string | Array<{ loc?: string[]; msg?: string }>; message?: string }>
    const data = axiosError.response?.data
    
    if (typeof data?.detail === 'string') {
      return data.detail
    } else if (Array.isArray(data?.detail)) {
      return data.detail.map((e) => {
        const field = e.loc?.join('.') || 'field'
        return `${field}: ${e.msg || 'validation error'}`
      }).join('; ')
    } else if (data?.message) {
      return data.message
    } else if (axiosError.message) {
      return axiosError.message
    }
  } else if (error instanceof Error) {
    return error.message
  }
  
  return 'Произошла неизвестная ошибка'
}

// Create axios instance
const apiClient = axios.create({
  baseURL: BASE_URL || undefined, // Use BASE_URL if set, otherwise undefined (relative paths)
})

type SharedGetCacheEntry<T> = { expiresAt: number; value: T }
const sharedGetCache = new Map<string, SharedGetCacheEntry<unknown>>()
const sharedGetInFlight = new Map<string, Promise<unknown>>()

async function cachedGet<T>(key: string, ttlMs: number, fetcher: () => Promise<T>): Promise<T> {
  const now = Date.now()
  const cached = sharedGetCache.get(key)
  if (cached && cached.expiresAt > now) {
    return cached.value as T
  }
  const inFlight = sharedGetInFlight.get(key)
  if (inFlight) {
    return inFlight as Promise<T>
  }
  const task = (async () => {
    const value = await fetcher()
    sharedGetCache.set(key, { expiresAt: Date.now() + ttlMs, value })
    return value
  })()
  sharedGetInFlight.set(key, task)
  try {
    return await task
  } finally {
    sharedGetInFlight.delete(key)
  }
}

function invalidateCachedGet(prefix: string): void {
  for (const key of sharedGetCache.keys()) {
    if (key.startsWith(prefix)) {
      sharedGetCache.delete(key)
    }
  }
}

// Request interceptor to add JWT token
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers['X-Access-Token'] = token
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Token refresh mutex: prevents multiple simultaneous refresh requests
let isRefreshing = false
let refreshSubscribers: Array<(token: string) => void> = []

function subscribeTokenRefresh(cb: (token: string) => void) {
  refreshSubscribers.push(cb)
}

function onTokenRefreshed(token: string) {
  refreshSubscribers.forEach(cb => cb(token))
  refreshSubscribers = []
}

// Response interceptor to handle token refresh
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as AxiosRequestConfig & { _retry?: boolean }

    // If error is 401 and we haven't tried to refresh yet
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true

      // If already refreshing, wait for the refresh to complete
      if (isRefreshing) {
        return new Promise((resolve) => {
          subscribeTokenRefresh((newToken: string) => {
            if (originalRequest.headers) {
              originalRequest.headers['X-Access-Token'] = newToken
            }
            resolve(apiClient(originalRequest))
          })
        })
      }

      isRefreshing = true

      try {
        const refreshToken = localStorage.getItem('refresh_token')
        if (refreshToken) {
          const response = await axios.post(
            getApiUrl('/api/auth/refresh'),
            null,
            {
              params: { refresh_token: refreshToken },
            }
          )

          const { access_token } = response.data
          localStorage.setItem('access_token', access_token)
          isRefreshing = false

          // Notify all waiting requests
          onTokenRefreshed(access_token)

          // Retry original request with new token
          if (originalRequest.headers) {
            originalRequest.headers['X-Access-Token'] = access_token
          }
          return apiClient(originalRequest)
        }
      } catch (refreshError) {
        isRefreshing = false
        refreshSubscribers = []
        // Refresh failed, logout user
        logger.error('Token refresh failed:', refreshError)
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        localStorage.removeItem('user')
        window.location.href = '/login'
        return Promise.reject(refreshError)
      }
    }

    // Log error for debugging
    if (error.response) {
      logger.error('API Error:', {
        status: error.response.status,
        data: error.response.data,
        url: error.config?.url,
      })
    } else {
      logger.error('API Network Error:', error.message)
    }

    return Promise.reject(error)
  }
)

export interface UploadResponse {
  caseId: string
  fileNames: string[]
}

export interface SourceInfo {
  file: string
  title?: string  // Optional title (alternative to file)
  page?: number
  citation_id?: string // Stable citation id (do not rely on array index)
  chunk_index?: number
  start_line?: number
  end_line?: number
  text_preview?: string
  similarity_score?: number
  // Enhanced citation fields for document highlighting (Harvey/Lexis+ style)
  char_start?: number  // EXACT start character position in document (from chunk)
  char_end?: number    // EXACT end character position in document (from chunk)
  context_before?: string  // Context before quote (50 chars)
  context_after?: string   // Context after quote (50 chars)
  quote?: string       // Backward-compatible quote field
  quote_anchor?: string // Stable anchor text for viewer highlighting
  /** Ordered cell values for Excel/table HTML highlight (prefer over labeled chunk quote). */
  highlight_targets?: string[]
  source_id?: string   // Document ID (file_id) for reference
  chunk_id?: string    // Unique chunk ID for precise navigation - KEY for reliable highlighting!
  bbox?: { x0?: number; y0?: number; x1?: number; y1?: number } // Bounding box on page
  /** Все регионы prov из Docling для одного чанка (мульти-подсветка в PDF). */
  bbox_regions?: Array<{ x0?: number; y0?: number; x1?: number; y1?: number }>
  page_bbox?: { width?: number; height?: number } // Page dimensions used to normalize bbox
  url?: string         // External URL (for pravo.gov.ru and other external sources)
  source_type?: string // Source type: 'document' | 'external' | 'garant' | 'web'
  case_id?: string     // Case ID (for case files — enables full document preview)
}

export interface ChatResponse {
  answer: string
  sources: SourceInfo[]
  status: string
}

export interface HistoryMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: (string | SourceInfo)[]
  created_at?: string
}

export const getApiUrl = (path: string) => {
  const prefix = BASE_URL.endsWith('/') ? BASE_URL.slice(0, -1) : BASE_URL
  return `${prefix}${path}`
}

export interface AnalysisConfig {
  enable_timeline?: boolean
  enable_entities?: boolean
  enable_classification?: boolean
  enable_privilege_check?: boolean
  [key: string]: unknown
}

export interface CaseInfo {
  title: string
  description?: string
  case_type?: string
  analysis_config?: AnalysisConfig
}

export const uploadFiles = async (
  files: File[],
  caseInfo?: CaseInfo | null,
  analysisOptions?: AnalysisConfig,
  onProgress?: (percent: number) => void
): Promise<UploadResponse> => {
  const formData = new FormData()
  files.forEach((file) => {
    formData.append('files', file)
  })

  // Add case info if provided
  if (caseInfo) {
    const caseInfoData = {
      ...caseInfo,
      analysis_config: analysisOptions,
    }
    formData.append('case_info', JSON.stringify(caseInfoData))
  }

  const response = await apiClient.post(getApiUrl('/api/upload'), formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
    onUploadProgress: (progressEvent) => {
      if (onProgress && progressEvent.total) {
        const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total)
        onProgress(percent)
      }
    },
  })

  if (response.data.status !== 'success') {
    throw new Error(response.data.message || 'Ошибка при загрузке файлов')
  }

  return {
    caseId: response.data.case_id,
    fileNames: response.data.file_names || [],
  }
}

export const sendMessage = async (
  caseId: string,
  question: string,
): Promise<ChatResponse> => {
  const response = await apiClient.post(getApiUrl('/api/chat'), {
    case_id: caseId,
    question,
  })

  return {
    answer: response.data.answer,
    sources: response.data.sources || [],
    status: response.data.status || 'success',
  }
}

export const fetchHistory = async (caseId: string, sessionId?: string): Promise<HistoryMessage[]> => {
  const url = sessionId 
    ? getApiUrl(`/api/v2/assistant/chat/${caseId}/history?session_id=${sessionId}`)
    : getApiUrl(`/api/v2/assistant/chat/${caseId}/history`)
  const response = await apiClient.get(url)
  return response.data.messages || []
}

export const getChatSessionsForCase = async (caseId: string): Promise<Array<{
  session_id: string
  first_message: string
  last_message: string
  first_message_at: string | null
  last_message_at: string | null
  message_count: number
}>> => {
  return cachedGet(`chat-sessions:${caseId}`, 2000, async () => {
    const response = await apiClient.get(getApiUrl(`/api/v2/assistant/chat/${caseId}/sessions`))
    return response.data.sessions || []
  })
}

export const getChatSessions = async (): Promise<Array<{
  case_id: string
  case_name: string
  last_message: string
  last_message_at: string
  message_count: number
}>> => {
  const response = await apiClient.get(getApiUrl('/api/chat/sessions'))
  return response.data || []
}

export const deleteChatSession = async (caseId: string, sessionId: string): Promise<void> => {
  await apiClient.delete(getApiUrl(`/api/v2/assistant/chat/${caseId}/sessions/${sessionId}`))
}

export interface RecentActivityItem {
  type: 'case_chat' | 'global_chat' | 'tabular_review' | 'operations'
  id: string
  title: string
  case_id: string | null
  case_name: string | null
  updated_at: string | null
}

export const getRecentActivity = async (limit = 15): Promise<RecentActivityItem[]> => {
  const response = await apiClient.get(getApiUrl(`/api/v2/recent-activity?limit=${limit}`))
  return response.data.items || []
}

export const getGlobalAssistantSessions = async (): Promise<Array<{
  session_id: string
  title: string
  message_count: number
  updated_at: string | null
}>> => {
  const response = await apiClient.get(getApiUrl('/api/v2/assistant/global-sessions'))
  return response.data || []
}

export const getGlobalAssistantSession = async (sessionId: string): Promise<{
  session_id: string
  title: string
  draft_title?: string
  draft_content?: string
  messages: Array<{
    role: 'user' | 'assistant'
    content: string
    reasoning_steps?: Array<{ phase: string; step: number; totalSteps?: number; content: string }> | null
  }>
}> => {
  const response = await apiClient.get(getApiUrl(`/api/v2/assistant/global-sessions/${sessionId}`))
  return response.data
}

export const saveSessionDraft = async (sessionId: string, draftTitle: string, draftContent: string): Promise<void> => {
  await apiClient.patch(getApiUrl(`/api/v2/assistant/global-sessions/${sessionId}/draft`), {
    draft_title: draftTitle,
    draft_content: draftContent,
  })
}

export const improveAssistantPrompt = async (text: string): Promise<string> => {
  const response = await apiClient.post<{ improved?: string }>(getApiUrl('/api/v2/assistant/improve-prompt'), {
    text,
  })
  return (response.data.improved ?? '').trim()
}

export interface AssistantFeedbackPayload {
  trace_id: string
  rating: 'positive' | 'negative'
  reason?: string
  comment?: string
}

export const sendAssistantFeedback = async (payload: AssistantFeedbackPayload): Promise<{ ok: boolean; score_sent: boolean }> => {
  const response = await apiClient.post(getApiUrl('/api/metrics/assistant-feedback'), payload)
  return response.data
}

// Dashboard API
export interface DashboardStats {
  total_cases: number
  total_documents: number
  total_analyses: number
  cases_this_month: number
  documents_this_month: number
  analyses_this_month: number
}

export interface CaseListItem {
  id: string
  title: string | null
  case_type: string | null
  status: string
  num_documents: number
  tabular_reviews_count?: number
  created_at: string
  updated_at: string
}

export interface CasesListResponse {
  cases: CaseListItem[]
  total: number
  skip: number
  limit: number
}

export const getDashboardStats = async (): Promise<DashboardStats> => {
  const response = await apiClient.get(getApiUrl('/api/dashboard/stats'))
  return response.data
}

interface CasesListParams {
  skip: number
  limit: number
  status?: string
  case_type?: string
}

export const getCasesList = async (
  skip: number = 0,
  limit: number = 100,
  status?: string,
  case_type?: string
): Promise<CasesListResponse> => {
  const params: CasesListParams = { skip, limit }
  if (status) params.status = status
  if (case_type) params.case_type = case_type
  
  const response = await apiClient.get(getApiUrl('/api/dashboard/cases'), { params })
  return response.data
}

export const getRecentCases = async (limit: number = 5): Promise<CaseListItem[]> => {
  // API: GET /api/dashboard/recent — limit <= 20 (см. FastAPI Query)
  const safeLimit = Math.min(20, Math.max(1, Math.trunc(limit)))
  const response = await apiClient.get(getApiUrl('/api/dashboard/recent'), {
    params: { limit: safeLimit },
  })
  return response.data
}

// Cases API
export interface CaseResponse {
  id: string
  title: string | null
  description: string | null
  case_type: string | null
  status: string
  num_documents: number
  file_names: string[]
  created_at: string
  updated_at: string
}

export const getCase = async (caseId: string): Promise<CaseResponse> => {
  return cachedGet(`case:${caseId}`, 2000, async () => {
    const response = await apiClient.get(getApiUrl(`/api/cases/${caseId}`))
    return response.data
  })
}

export const createCase = async (caseInfo: CaseInfo): Promise<CaseResponse> => {
  const response = await apiClient.post(getApiUrl('/api/cases/'), caseInfo)
  return response.data
}

// File management API
export interface UploadedFile {
  id: string
  filename: string
  file_type: string
  size?: number
  created_at?: string
  folder_id?: string | null
}

export interface FilesResponse {
  files: UploadedFile[]
  total: number
  added?: number
  new_file_ids?: string[]
  status?: string
  errors?: Array<{ name: string; detail: string }>
}

export interface GoogleDriveImportFileItem {
  id: string
  name: string
  mime_type: string
}

export interface GoogleDriveImportPayload {
  access_token: string
  files: GoogleDriveImportFileItem[]
}

export const addFilesToCase = async (
  caseId: string,
  files: File[],
  onProgress?: (percent: number) => void
): Promise<FilesResponse> => {
  const formData = new FormData()
  files.forEach((file) => {
    formData.append('files', file)
  })

  const response = await apiClient.post(
    getApiUrl(`/api/cases/${caseId}/files`),
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total)
          onProgress(percent)
        }
      },
    }
  )

  invalidateCachedGet(`case-files:${caseId}`)
  invalidateCachedGet(`case-documents:${caseId}`)
  return response.data
}

export const importFilesFromGoogleDrive = async (
  caseId: string,
  payload: GoogleDriveImportPayload,
): Promise<FilesResponse> => {
  const response = await apiClient.post(
    getApiUrl(`/api/cases/${caseId}/import/google-drive`),
    payload,
  )
  invalidateCachedGet(`case-files:${caseId}`)
  invalidateCachedGet(`case-documents:${caseId}`)
  return response.data
}

export interface FileProcessingProgress {
  stage?: string
  percent?: number
  message?: string
  pages_done?: number | null
  pages_total?: number | null
  batch_index?: number | null
  batch_count?: number | null
}

export interface FileProcessingStatus {
  id: string
  filename: string
  status: 'pending' | 'processing' | 'ready' | 'error' | 'cancelled'
  error?: string | null
  processing_started_at?: string | null
  progress?: FileProcessingProgress | null
}

export interface ProcessingStatusResponse {
  case_id: string
  files: FileProcessingStatus[]
  all_done: boolean
  any_processing: boolean
  has_errors: boolean
}

export const getProcessingStatus = async (caseId: string): Promise<ProcessingStatusResponse> => {
  const response = await apiClient.get(getApiUrl(`/api/cases/${caseId}/processing-status`))
  return response.data
}

export const cancelFileProcessing = async (caseId: string, fileId: string): Promise<void> => {
  await apiClient.post(getApiUrl(`/api/cases/${caseId}/files/${fileId}/cancel`))
}

export const deleteFileFromCase = async (
  caseId: string,
  fileId: string
): Promise<FilesResponse> => {
  const response = await apiClient.delete(getApiUrl(`/api/cases/${caseId}/files/${fileId}`))
  invalidateCachedGet(`case-files:${caseId}`)
  invalidateCachedGet(`case-documents:${caseId}`)
  return response.data
}

export const deleteCase = async (caseId: string): Promise<void> => {
  await apiClient.delete(getApiUrl(`/api/cases/${caseId}`))
}

export const getCaseFiles = async (caseId: string): Promise<FilesResponse> => {
  return cachedGet(`case-files:${caseId}`, 2000, async () => {
    const response = await apiClient.get(getApiUrl(`/api/cases/${caseId}/files`))
    return {
      files: response.data.documents?.map((doc: any) => ({
        id: doc.id,
        filename: doc.filename,
        file_type: doc.file_type,
        created_at: doc.created_at,
      })) || [],
      total: response.data.total || 0,
    }
  })
}

// Folders (case-level folder tree)
export interface FolderItem {
  id: string
  name: string
  parent_id: string | null
  file_count: number
  color?: string
  icon?: string
  children?: FolderItem[]
}

export const getCaseFolders = async (caseId: string): Promise<FolderItem[]> => {
  return cachedGet(`case-folders:${caseId}`, 2000, async () => {
    try {
      const response = await apiClient.get(getApiUrl(`/api/cases/${caseId}/folders`))
      return Array.isArray(response.data) ? response.data : (response.data?.folders ?? [])
    } catch {
      return []
    }
  })
}

export const createFolder = async (
  caseId: string,
  name: string,
  parentId: string | null
): Promise<void> => {
  await apiClient.post(getApiUrl(`/api/cases/${caseId}/folders`), {
    name,
    parent_id: parentId,
  })
  invalidateCachedGet(`case-folders:${caseId}`)
}

export const renameFolder = async (
  caseId: string,
  folderId: string,
  newName: string
): Promise<void> => {
  await apiClient.patch(getApiUrl(`/api/cases/${caseId}/folders/${folderId}`), {
    name: newName,
  })
  invalidateCachedGet(`case-folders:${caseId}`)
}

export const deleteFolder = async (
  caseId: string,
  folderId: string
): Promise<void> => {
  await apiClient.delete(getApiUrl(`/api/cases/${caseId}/folders/${folderId}`))
  invalidateCachedGet(`case-folders:${caseId}`)
}

export const moveFileToFolder = async (
  caseId: string,
  fileId: string,
  folderId: string | null
): Promise<void> => {
  await apiClient.patch(getApiUrl(`/api/cases/${caseId}/files/${fileId}`), {
    folder_id: folderId,
  })
  invalidateCachedGet(`case-files:${caseId}`)
  invalidateCachedGet(`case-documents:${caseId}`)
}

export interface ProcessResponse {
  status: string
  message: string
  case_id: string
  num_files: number
}

export const processCaseFiles = async (
  caseId: string,
  analysisConfig?: AnalysisConfig
): Promise<ProcessResponse> => {
  const response = await apiClient.post(getApiUrl(`/api/cases/${caseId}/process`), {
    analysis_config: analysisConfig,
  })
  return response.data
}

// Analysis API
export interface TimelineEventMetadata {
  [key: string]: unknown
}

export interface TimelineEvent {
  id: string
  date: string
  event_type: string | null
  description: string
  source_document: string
  source_page: number | null
  source_line: number | null
  metadata: TimelineEventMetadata
}

export interface DiscrepancyDetails {
  [key: string]: unknown
}

export interface DiscrepancyItem {
  id: string
  type: string
  severity: 'HIGH' | 'MEDIUM' | 'LOW'
  description: string
  source_documents: string[]
  details: DiscrepancyDetails
  created_at: string
}

export interface AnalysisStatus {
  case_status: string
  analysis_results: Record<string, {
    status: string
    created_at: string
    updated_at: string
  }>
}

export const startAnalysis = async (
  caseId: string,
  analysisTypes: string[]
): Promise<{ status: string; message: string }> => {
  const response = await apiClient.post(
    getApiUrl(`/api/analysis/${caseId}/start`),
    {
      analysis_types: analysisTypes,
    }
  )
  return response.data
}

export const getAnalysisStatus = async (caseId: string): Promise<AnalysisStatus> => {
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/status`))
  return response.data
}

export const getTimeline = async (caseId: string): Promise<{ events: TimelineEvent[]; total: number }> => {
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/timeline`))
  return response.data
}

export const getDiscrepancies = async (
  caseId: string
): Promise<{
  discrepancies: DiscrepancyItem[]
  total: number
  high_risk: number
  medium_risk: number
  low_risk: number
}> => {
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/discrepancies`))
  return response.data
}

export interface KeyFact {
  [key: string]: unknown
}

export interface KeyFactsResponse {
  facts: KeyFact
  created_at?: string
}

export const getKeyFacts = async (caseId: string): Promise<KeyFactsResponse> => {
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/key-facts`))
  return response.data
}

export interface SummaryResponse {
  summary: string
  key_facts: KeyFact
  created_at?: string
}

export const getSummary = async (caseId: string): Promise<SummaryResponse> => {
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/summary`))
  return response.data
}

export interface RisksResponse {
  analysis: string
  discrepancies: DiscrepancyDetails
  created_at?: string
}

export const getRisks = async (caseId: string): Promise<RisksResponse> => {
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/risks`))
  return response.data
}

export interface RelationshipNodeProperties {
  [key: string]: unknown
}

export interface RelationshipNode {
  id: string
  type: string
  label: string
  properties: RelationshipNodeProperties
  source_document?: string | null
  source_page?: number | null
}

export interface RelationshipLink {
  source: string
  target: string
  type: string
  label?: string | null
  source_document?: string | null
  source_page?: number | null
  properties?: RelationshipNodeProperties
}

export interface RelationshipGraph {
  nodes: RelationshipNode[]
  links: RelationshipLink[]
}

export const getRelationshipGraph = async (caseId: string): Promise<RelationshipGraph> => {
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/relationship-graph`))
  return response.data
}

// Reports API
export interface AvailableReport {
  type: string
  name: string
  formats: string[]
  description: string
}

export const getReportsList = async (caseId: string): Promise<{ case_id: string; available_reports: AvailableReport[] }> => {
  const response = await apiClient.get(getApiUrl(`/api/reports/${caseId}`))
  return response.data
}

export const generateReport = async (
  caseId: string,
  reportType: string,
  format: string
): Promise<Blob> => {
  const response = await apiClient.post(
    getApiUrl(`/api/reports/${caseId}/generate`),
    null,
    {
      params: { report_type: reportType, format },
      responseType: 'blob',
    }
  )
  return response.data
}

// Settings API
export interface UserProfile {
  id: string
  email: string
  full_name: string | null
  company: string | null
  role: string
  created_at: string
}

export interface NotificationSettings {
  email_on_analysis_complete?: boolean
  email_on_critical_discrepancies?: boolean
  weekly_digest?: boolean
  reminders_for_important_dates?: boolean
  news_and_updates?: boolean
  [key: string]: boolean | undefined
}

export interface GoogleDriveSettings {
  enabled: boolean
  connected_account?: string | null
}

export interface SlackSettings {
  enabled: boolean
  workspace?: string | null
  webhook_url?: string | null
}

export interface IntegrationSettings {
  google_drive?: GoogleDriveSettings
  slack?: SlackSettings
  [key: string]: GoogleDriveSettings | SlackSettings | unknown
}

export const getProfile = async (): Promise<UserProfile> => {
  const response = await apiClient.get(getApiUrl('/api/settings/profile'))
  return response.data
}

export const updateProfile = async (data: { full_name?: string; company?: string }): Promise<UserProfile> => {
  const response = await apiClient.put(getApiUrl('/api/settings/profile'), data)
  return response.data
}

export interface PasswordUpdateResponse {
  message: string
}

export const updatePassword = async (data: { current_password: string; new_password: string }): Promise<PasswordUpdateResponse> => {
  const response = await apiClient.put(getApiUrl('/api/settings/password'), data)
  return response.data
}

export const getNotifications = async (): Promise<NotificationSettings> => {
  const response = await apiClient.get(getApiUrl('/api/settings/notifications'))
  return response.data
}

export const updateNotifications = async (settings: NotificationSettings): Promise<NotificationSettings> => {
  const response = await apiClient.put(getApiUrl('/api/settings/notifications'), settings)
  return response.data
}

export const getIntegrations = async (): Promise<IntegrationSettings> => {
  const response = await apiClient.get(getApiUrl('/api/settings/integrations'))
  return response.data
}

export const updateIntegrations = async (settings: IntegrationSettings): Promise<IntegrationSettings> => {
  const response = await apiClient.put(getApiUrl('/api/settings/integrations'), settings)
  return response.data
}

// Documents API
export interface DocumentItem {
  id: string
  filename: string
  file_type: string
  created_at: string
}

export interface DocumentListResponse {
  documents: DocumentItem[]
  total: number
}

export const getDocuments = async (caseId: string): Promise<DocumentListResponse> => {
  return cachedGet(`case-documents:${caseId}`, 2000, async () => {
    const response = await apiClient.get(getApiUrl(`/api/cases/${caseId}/files`))
    return response.data
  })
}

// Classification API
export interface DocumentClassification {
  id: string
  file_id: string
  file_name: string
  doc_type: string
  relevance_score: number
  is_privileged: boolean
  privilege_type: string
  key_topics: string[]
  confidence: number
  reasoning: string
  created_at: string
}

export interface ClassificationsResponse {
  classifications: DocumentClassification[]
  total: number
}

export const getClassifications = async (caseId: string): Promise<ClassificationsResponse> => {
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/classify`))
  return response.data
}

export interface ClassifyDocumentsResponse {
  status: string
  message: string
  classifications?: DocumentClassification[]
}

export const classifyDocuments = async (caseId: string, fileId?: string): Promise<ClassifyDocumentsResponse> => {
  const response = await apiClient.post(
    getApiUrl(`/api/analysis/${caseId}/classify`),
    fileId ? { file_id: fileId } : {}
  )
  return response.data
}

// Entities API
export interface ExtractedEntity {
  id: string
  file_id: string
  file_name: string
  text: string
  type: string
  confidence: number
  context: string
  source_document: string
  source_page: number | null
  source_line: number | null
  created_at: string
}

export interface EntitiesResponse {
  entities: ExtractedEntity[]
  entities_by_type: Record<string, ExtractedEntity[]>
  total_entities: number
  by_type_count: Record<string, number>
}

interface EntitiesParams {
  file_id?: string
}

export const getEntities = async (caseId: string, fileId?: string): Promise<EntitiesResponse> => {
  const params: EntitiesParams = {}
  if (fileId) params.file_id = fileId
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/entities`), { params })
  return response.data
}

export interface ExtractEntitiesResponse {
  status: string
  message: string
  entities?: ExtractedEntity[]
}

export const extractEntities = async (caseId: string, fileId?: string): Promise<ExtractEntitiesResponse> => {
  const response = await apiClient.post(
    getApiUrl(`/api/analysis/${caseId}/entities`),
    fileId ? { file_id: fileId } : {}
  )
  return response.data
}

// Privilege API
export interface PrivilegeCheck {
  id: string
  file_id: string
  is_privileged: boolean
  privilege_type: string
  confidence: number
  reasoning: string[]
  withhold_recommendation: boolean
  requires_human_review: boolean
  created_at: string
}

export interface PrivilegeChecksResponse {
  privilege_checks: PrivilegeCheck[]
  total: number
  privileged_count: number
  requires_review_count: number
}

export const getPrivilegeChecks = async (caseId: string): Promise<PrivilegeChecksResponse> => {
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/privilege`))
  return response.data
}

export interface CheckPrivilegeResponse {
  status: string
  message: string
  privilege_check?: PrivilegeCheck
}

export const checkPrivilege = async (caseId: string, fileId: string): Promise<CheckPrivilegeResponse> => {
  const response = await apiClient.post(
    getApiUrl(`/api/analysis/${caseId}/privilege`),
    { file_id: fileId }
  )
  return response.data
}

// Analysis Report API
export interface CategorizedFile {
  id: string
  filename: string
  file_type: string
  [key: string]: unknown
}

export interface AnalysisReport {
  case_id: string
  case_title: string | null
  total_files: number
  categorization: {
    high_relevance: {
      count: number
      label: string
      files: CategorizedFile[]
    }
    privileged: {
      count: number
      label: string
      files: CategorizedFile[]
      warning: string
    }
    medium_relevance: {
      count: number
      label: string
      files: CategorizedFile[]
    }
    low_relevance: {
      count: number
      label: string
      files: CategorizedFile[]
    }
  }
  statistics: {
    total_entities: number
    entities_by_type: Record<string, number>
    timeline_events: number
    discrepancies: number
    classified_files: number
    privilege_checked_files: number
  }
  summary: {
    high_relevance_count: number
    privileged_count: number
    low_relevance_count: number
    message: string
  }
}

export const getAnalysisReport = async (caseId: string): Promise<AnalysisReport> => {
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/report`))
  return response.data
}

// Batch Actions API
export interface BatchActionResponse {
  status: string
  message: string
  processed_count?: number
  failed_count?: number
}

export const batchConfirm = async (caseId: string, fileIds: string[]): Promise<BatchActionResponse> => {
  const response = await apiClient.post(
    getApiUrl(`/api/analysis/${caseId}/batch/confirm`),
    { file_ids: fileIds }
  )
  return response.data
}

export const batchReject = async (caseId: string, fileIds: string[]): Promise<BatchActionResponse> => {
  const response = await apiClient.post(
    getApiUrl(`/api/analysis/${caseId}/batch/reject`),
    { file_ids: fileIds }
  )
  return response.data
}

export const batchWithhold = async (caseId: string, fileIds: string[]): Promise<BatchActionResponse> => {
  const response = await apiClient.post(
    getApiUrl(`/api/analysis/${caseId}/batch/withhold`),
    { file_ids: fileIds }
  )
  return response.data
}

// Document Content API
export const getDocumentContent = async (caseId: string, fileId: string): Promise<Blob> => {
  const response = await apiClient.get(
    getApiUrl(`/api/cases/${caseId}/files/${fileId}/content`),
    { responseType: 'blob' }
  )
  return response.data
}

/** Replace plain text for a case file (workflow drafts, .txt artifacts). */
export const updateCaseFileText = async (
  caseId: string,
  fileId: string,
  text: string
): Promise<void> => {
  await apiClient.put(getApiUrl(`/api/cases/${caseId}/files/${fileId}/text`), { text })
}

// Related Documents API
export interface RelatedDocument {
  file_id: string
  filename: string
  relevance_score: number
  classification?: {
    doc_type: string
    relevance_score: number
  }
}

export interface RelatedDocumentsResponse {
  source_file_id: string
  source_filename: string
  related_documents: RelatedDocument[]
  total_related: number
}

interface RelatedDocumentsParams {
  limit?: number
}

export const getRelatedDocuments = async (caseId: string, fileId: string, limit?: number): Promise<RelatedDocumentsResponse> => {
  const params: RelatedDocumentsParams = {}
  if (limit) params.limit = limit
  const response = await apiClient.get(
    getApiUrl(`/api/analysis/${caseId}/files/${fileId}/related`),
    { params }
  )
  return response.data
}

// ─── Общий правовой справочник (глобальный ассистент) ───

export interface LegalCorpusStatus {
  chunk_count: number
  has_corpus: boolean
  is_uploader: boolean
}

export interface LegalCorpusFileRow {
  corpus_file_id: string
  source_filename: string
  chunk_count: number
}

export interface LegalCorpusInstrument {
  instrument_id: string
  short_name: string
  title: string
  aliases?: string[]
}

const isTimeoutError = (error: unknown): boolean => {
  return axios.isAxiosError(error) && (error.code === 'ECONNABORTED' || String(error.message || '').toLowerCase().includes('timeout'))
}

export const fetchLegalCorpusStatus = async (): Promise<LegalCorpusStatus> => {
  return cachedGet('legal-corpus:status', 10000, async () => {
    try {
      const response = await apiClient.get<LegalCorpusStatus>(
        getApiUrl('/api/v2/legal-corpus/status'),
        { timeout: 30000 }
      )
      return response.data
    } catch (err) {
      if (!isTimeoutError(err)) throw err
      // One retry for slow cold-start / DB wake-up
      const retry = await apiClient.get<LegalCorpusStatus>(
        getApiUrl('/api/v2/legal-corpus/status'),
        { timeout: 45000 }
      )
      return retry.data
    }
  })
}

export const fetchLegalCorpusFiles = async (): Promise<{ files: LegalCorpusFileRow[] }> => {
  return cachedGet('legal-corpus:files', 10000, async () => {
    try {
      const response = await apiClient.get<{ files: LegalCorpusFileRow[] }>(
        getApiUrl('/api/v2/legal-corpus/files'),
        { timeout: 30000 }
      )
      return response.data
    } catch (err) {
      if (!isTimeoutError(err)) throw err
      const retry = await apiClient.get<{ files: LegalCorpusFileRow[] }>(
        getApiUrl('/api/v2/legal-corpus/files'),
        { timeout: 45000 }
      )
      return retry.data
    }
  })
}

export const fetchLegalCorpusInstruments = async (): Promise<{ instruments: LegalCorpusInstrument[] }> => {
  return cachedGet('legal-corpus:instruments', 60_000, async () => {
    const response = await apiClient.get<{ instruments: LegalCorpusInstrument[] }>(
      getApiUrl('/api/v2/legal-corpus/instruments'),
      { timeout: 30000 }
    )
    return response.data
  })
}

export interface LegalCorpusUploadResult {
  indexed: Array<{ filename: string; corpus_file_id: string; chunks_indexed: number }>
  errors: Array<{ filename: string; detail: string }>
  chunk_count_total: number
}

export const uploadLegalCorpusFiles = async (files: File[]): Promise<LegalCorpusUploadResult> => {
  const formData = new FormData()
  for (const f of files) {
    formData.append('files', f)
  }
  const response = await apiClient.post<LegalCorpusUploadResult>(
    getApiUrl('/api/v2/legal-corpus/upload'),
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } }
  )
  invalidateCachedGet('legal-corpus:status')
  invalidateCachedGet('legal-corpus:files')
  return response.data
}

export interface LegalCorpusJobStartResponse {
  job_id: string
  status: string
  total_files: number
}

export interface LegalCorpusJobSnapshot {
  job_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  message: string
  progress_percent: number
  total_files: number
  processed_files: number
  indexed_chunks: number
  errors: Array<{ filename: string; detail: string }>
  results: Array<{ filename: string; corpus_file_id: string; chunks_indexed: number }>
  created_at: number
  finished_at: number | null
}

export const startLegalCorpusUploadJob = async (
  files: File[],
  instrumentId?: string | null
): Promise<LegalCorpusJobStartResponse> => {
  const formData = new FormData()
  for (const f of files) formData.append('files', f)
  if (instrumentId) formData.append('instrument_id', instrumentId)
  const response = await apiClient.post<LegalCorpusJobStartResponse>(
    getApiUrl('/api/v2/legal-corpus/upload-job'),
    formData,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      // Large DOCX/PDF uploads can exceed 120s on slow links; job runs after quick 202-style JSON.
      timeout: 600_000,
    }
  )
  invalidateCachedGet('legal-corpus:status')
  invalidateCachedGet('legal-corpus:files')
  invalidateCachedGet('legal-corpus:instruments')
  return response.data
}

export function buildLegalCorpusJobSseUrl(jobId: string): string {
  const token = localStorage.getItem('access_token')
  const qs = token ? `?token=${encodeURIComponent(token)}` : ''
  const path = `/api/v2/legal-corpus/jobs/${encodeURIComponent(jobId)}/events${qs}`
  if (import.meta.env.DEV) return path
  const base = (import.meta.env.VITE_API_URL || '').trim().replace(/\/$/, '')
  return base ? `${base}${path}` : path
}

export const deleteLegalCorpusFile = async (corpusFileId: string): Promise<void> => {
  await apiClient.delete(getApiUrl(`/api/v2/legal-corpus/file/${encodeURIComponent(corpusFileId)}`))
  invalidateCachedGet('legal-corpus:status')
  invalidateCachedGet('legal-corpus:files')
}

export const deleteAllLegalCorpusFiles = async (): Promise<{
  deleted_chunks: number
  deleted_files: number
  chunk_count_total: number
}> => {
  const response = await apiClient.delete<{
    deleted_chunks: number
    deleted_files: number
    chunk_count_total: number
  }>(getApiUrl('/api/v2/legal-corpus/files'))
  invalidateCachedGet('legal-corpus:status')
  invalidateCachedGet('legal-corpus:files')
  return response.data
}

// ─── Судебная практика (КАД) ───

export interface CourtPracticeStatus {
  chunk_count: number
  document_count: number
  is_uploader: boolean
  batches: Array<{
    batch_id: string
    documents: number
    chunks: number
    created_at: string | null
  }>
}

export const fetchCourtPracticeStatus = async (): Promise<CourtPracticeStatus> => {
  return cachedGet('court-practice:status', 10000, async () => {
    const response = await apiClient.get<CourtPracticeStatus>(
      getApiUrl('/api/v2/court-practice/status'),
      { timeout: 30000 }
    )
    return response.data
  })
}

export interface CourtPracticeJobStartResponse {
  job_id: string
  status: string
}

export const startCourtPracticeUploadJob = async (
  file: File,
  maxRows?: number
): Promise<CourtPracticeJobStartResponse> => {
  const formData = new FormData()
  formData.append('file', file)
  const response = await apiClient.post<CourtPracticeJobStartResponse>(
    getApiUrl(
      `/api/v2/court-practice/upload-job${maxRows ? `?max_rows=${encodeURIComponent(String(maxRows))}` : ''}`
    ),
    formData,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600_000,
    }
  )
  invalidateCachedGet('court-practice:status')
  return response.data
}

export function buildCourtPracticeJobSseUrl(jobId: string): string {
  const token = localStorage.getItem('access_token')
  const qs = token ? `?token=${encodeURIComponent(token)}` : ''
  const path = `/api/v2/court-practice/jobs/${encodeURIComponent(jobId)}/events${qs}`
  if (import.meta.env.DEV) return path
  const base = (import.meta.env.VITE_API_URL || '').trim().replace(/\/$/, '')
  return base ? `${base}${path}` : path
}

export const deleteCourtPracticeBatch = async (
  batchId: string
): Promise<{ deleted_documents: number; deleted_chunks: number }> => {
  const response = await apiClient.delete<{ deleted_documents: number; deleted_chunks: number }>(
    getApiUrl(`/api/v2/court-practice/batch/${encodeURIComponent(batchId)}`)
  )
  invalidateCachedGet('court-practice:status')
  return response.data
}

export const deleteAllCourtPractice = async (): Promise<{
  deleted_documents: number
  deleted_chunks: number
}> => {
  const response = await apiClient.delete<{ deleted_documents: number; deleted_chunks: number }>(
    getApiUrl('/api/v2/court-practice/all')
  )
  invalidateCachedGet('court-practice:status')
  return response.data
}

// ─── Публичные шаблоны Draft (загрузка любым авторизованным пользователем) ───

export interface AdminDraftTemplateRow {
  id: string
  title: string
  description: string
  created_at: string | null
  content_length: number
}

export const fetchAdminDraftTemplates = async (): Promise<{ templates: AdminDraftTemplateRow[] }> => {
  const response = await apiClient.get<{ templates: AdminDraftTemplateRow[] }>(
    getApiUrl('/api/v2/admin/draft-templates'),
    { timeout: 45000 }
  )
  return response.data
}

export const uploadAdminDraftTemplate = async (
  file: File,
  title: string,
  description: string
): Promise<{ id: string; title: string; description: string; content_length: number }> => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('title', title)
  formData.append('description', description)
  const response = await apiClient.post(getApiUrl('/api/v2/admin/draft-templates'), formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
  return response.data
}

export const deleteAdminDraftTemplate = async (templateId: string): Promise<void> => {
  await apiClient.delete(
    getApiUrl(`/api/v2/admin/draft-templates/${encodeURIComponent(templateId)}`),
    { timeout: 45000 }
  )
}

// Default export for convenience
const api = {
  get: apiClient.get.bind(apiClient),
  post: apiClient.post.bind(apiClient),
  put: apiClient.put.bind(apiClient),
  delete: apiClient.delete.bind(apiClient),
  patch: apiClient.patch.bind(apiClient),
}

export default api


