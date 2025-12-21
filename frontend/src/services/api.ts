import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || ''

// Create axios instance
const apiClient = axios.create()

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
  async (error) => {
    const originalRequest = error.config

    // If error is 401 and we haven't tried to refresh yet
    if (error.response?.status === 401 && !originalRequest._retry) {
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
          originalRequest.headers.Authorization = `Bearer ${access_token}`
          return apiClient(originalRequest)
        }
      } catch (refreshError) {
        // Refresh failed, logout user
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        localStorage.removeItem('user')
        window.location.href = '/login'
        return Promise.reject(refreshError)
      }
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
  page?: number
  chunk_index?: number
  start_line?: number
  end_line?: number
  text_preview?: string
  similarity_score?: number
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

export interface CaseInfo {
  title: string
  description?: string
  case_type?: string
  analysis_config?: any
}

export const uploadFiles = async (
  files: File[],
  caseInfo?: CaseInfo | null,
  analysisOptions?: any
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

export const fetchHistory = async (caseId: string): Promise<HistoryMessage[]> => {
  const response = await apiClient.get(getApiUrl(`/api/chat/${caseId}/history`))
  return response.data.messages || []
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

export const getCasesList = async (
  skip: number = 0,
  limit: number = 100,
  status?: string,
  case_type?: string
): Promise<CasesListResponse> => {
  const params: any = { skip, limit }
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

// Analysis API
export interface TimelineEvent {
  id: string
  date: string
  event_type: string | null
  description: string
  source_document: string
  source_page: number | null
  source_line: number | null
  metadata: any
}

export interface DiscrepancyItem {
  id: string
  type: string
  severity: 'HIGH' | 'MEDIUM' | 'LOW'
  description: string
  source_documents: string[]
  details: any
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

export const getKeyFacts = async (caseId: string): Promise<{ facts: any; created_at?: string }> => {
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/key-facts`))
  return response.data
}

export const getSummary = async (caseId: string): Promise<{ summary: string; key_facts: any; created_at?: string }> => {
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/summary`))
  return response.data
}

export const getRisks = async (caseId: string): Promise<{ analysis: string; discrepancies: any; created_at?: string }> => {
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/risks`))
  return response.data
}

export interface RelationshipNode {
  id: string
  type: string
  label: string
  properties: any
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
  properties?: any
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
export const getProfile = async (): Promise<any> => {
  const response = await apiClient.get(getApiUrl('/api/settings/profile'))
  return response.data
}

export const updateProfile = async (data: { full_name?: string; company?: string }): Promise<any> => {
  const response = await apiClient.put(getApiUrl('/api/settings/profile'), data)
  return response.data
}

export const updatePassword = async (data: { current_password: string; new_password: string }): Promise<any> => {
  const response = await apiClient.put(getApiUrl('/api/settings/password'), data)
  return response.data
}

export const getNotifications = async (): Promise<any> => {
  const response = await apiClient.get(getApiUrl('/api/settings/notifications'))
  return response.data
}

export const updateNotifications = async (settings: any): Promise<any> => {
  const response = await apiClient.put(getApiUrl('/api/settings/notifications'), settings)
  return response.data
}

export const getIntegrations = async (): Promise<any> => {
  const response = await apiClient.get(getApiUrl('/api/settings/integrations'))
  return response.data
}

export const updateIntegrations = async (settings: any): Promise<any> => {
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

export const classifyDocuments = async (caseId: string, fileId?: string): Promise<any> => {
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

export const getEntities = async (caseId: string, fileId?: string): Promise<EntitiesResponse> => {
  const params: any = {}
  if (fileId) params.file_id = fileId
  const response = await apiClient.get(getApiUrl(`/api/analysis/${caseId}/entities`), { params })
  return response.data
}

export const extractEntities = async (caseId: string, fileId?: string): Promise<any> => {
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

export const checkPrivilege = async (caseId: string, fileId: string): Promise<any> => {
  const response = await apiClient.post(
    getApiUrl(`/api/analysis/${caseId}/privilege`),
    { file_id: fileId }
  )
  return response.data
}

// Analysis Report API
export interface AnalysisReport {
  case_id: string
  case_title: string | null
  total_files: number
  categorization: {
    high_relevance: {
      count: number
      label: string
      files: any[]
    }
    privileged: {
      count: number
      label: string
      files: any[]
      warning: string
    }
    medium_relevance: {
      count: number
      label: string
      files: any[]
    }
    low_relevance: {
      count: number
      label: string
      files: any[]
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
export const batchConfirm = async (caseId: string, fileIds: string[]): Promise<any> => {
  const response = await apiClient.post(
    getApiUrl(`/api/analysis/${caseId}/batch/confirm`),
    { file_ids: fileIds }
  )
  return response.data
}

export const batchReject = async (caseId: string, fileIds: string[]): Promise<any> => {
  const response = await apiClient.post(
    getApiUrl(`/api/analysis/${caseId}/batch/reject`),
    { file_ids: fileIds }
  )
  return response.data
}

export const batchWithhold = async (caseId: string, fileIds: string[]): Promise<any> => {
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

export const getRelatedDocuments = async (caseId: string, fileId: string, limit?: number): Promise<RelatedDocumentsResponse> => {
  const params: any = {}
  if (limit) params.limit = limit
  const response = await apiClient.get(
    getApiUrl(`/api/analysis/${caseId}/files/${fileId}/related`),
    { params }
  )
  return response.data
}


