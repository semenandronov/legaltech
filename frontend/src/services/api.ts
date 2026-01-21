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

// Request interceptor to add JWT token
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor to handle token refresh
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as AxiosRequestConfig & { _retry?: boolean }

    // If error is 401 and we haven't tried to refresh yet
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true

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

          // Retry original request with new token
          if (originalRequest.headers) {
            originalRequest.headers.Authorization = `Bearer ${access_token}`
          }
          return apiClient(originalRequest)
        }
      } catch (refreshError) {
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
  quote?: string       // Text from chunk (for preview)
  source_id?: string   // Document ID (file_id) for reference
  chunk_id?: string    // Unique chunk ID for precise navigation - KEY for reliable highlighting!
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
  const response = await apiClient.get(getApiUrl(`/api/v2/assistant/chat/${caseId}/sessions`))
  return response.data.sessions || []
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
  const response = await apiClient.get(getApiUrl('/api/dashboard/recent'), {
    params: { limit },
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
  const response = await apiClient.get(getApiUrl(`/api/cases/${caseId}`))
  return response.data
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
}

export interface FilesResponse {
  files: UploadedFile[]
  total: number
  added?: number
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

  return response.data
}

export const deleteFileFromCase = async (
  caseId: string,
  fileId: string
): Promise<FilesResponse> => {
  const response = await apiClient.delete(getApiUrl(`/api/cases/${caseId}/files/${fileId}`))
  return response.data
}

export const getCaseFiles = async (caseId: string): Promise<FilesResponse> => {
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
  const response = await apiClient.get(getApiUrl(`/api/cases/${caseId}/files`))
  return response.data
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

// Default export for convenience
const api = {
  get: apiClient.get.bind(apiClient),
  post: apiClient.post.bind(apiClient),
  put: apiClient.put.bind(apiClient),
  delete: apiClient.delete.bind(apiClient),
  patch: apiClient.patch.bind(apiClient),
}

export default api


