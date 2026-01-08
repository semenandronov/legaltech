// Import the existing extractErrorMessage from api.ts
import { extractErrorMessage } from './api'
import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || ''

const apiClient = axios.create({
  baseURL: BASE_URL,
})

// Add auth token to requests
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      // Try to refresh token
      const refreshToken = localStorage.getItem('refresh_token')
      if (refreshToken) {
        try {
          const response = await axios.post(`${BASE_URL}/api/auth/refresh`, null, {
            params: { refresh_token: refreshToken },
          })
          const { access_token } = response.data
          localStorage.setItem('access_token', access_token)
          
          // Retry original request
          if (error.config) {
            if (!error.config.headers) {
              error.config.headers = {}
            }
            error.config.headers.Authorization = `Bearer ${access_token}`
            return apiClient(error.config)
          }
        } catch (refreshError) {
          // Refresh failed, redirect to login
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
          window.location.href = '/login'
        }
      }
    }
    return Promise.reject(error)
  }
)

// Types
export interface TabularReview {
  id: string
  case_id: string
  name: string
  description?: string
  status: 'draft' | 'processing' | 'completed'
  table_mode?: 'document' | 'entity' | 'fact'
  entity_config?: any
  created_at: string
}

export interface TabularColumn {
  id: string
  column_label: string
  column_type: 'text' | 'bulleted_list' | 'number' | 'currency' | 'yes_no' | 'date' | 'tag' | 'multiple_tags' | 'verbatim' | 'manual_input'
  prompt: string
  column_config?: {
    options?: Array<{ label: string; color: string }>
    allow_custom?: boolean
  }
  is_pinned?: boolean
  order_index: number
}

export interface SourceReference {
  page?: number | null
  section?: string | null
  text: string
  bbox?: {
    x0: number
    y0: number
    x1: number
    y1: number
  } | null
  page_bbox?: {
    width: number
    height: number
  } | null
}

export interface Candidate {
  value: string
  normalized_value?: string | null
  confidence: number
  source_page?: number | null
  source_section?: string | null
  verbatim?: string | null
  reasoning?: string | null
  extraction_method?: string
  source_references?: SourceReference[]
}

export interface TabularCell {
  cell_value: string | null
  normalized_value?: string | null
  verbatim_extract?: string | null
  reasoning?: string | null
  source_references?: SourceReference[]
  confidence_score?: number | null
  source_page?: number | null
  source_section?: string | null
  status: 'pending' | 'processing' | 'completed' | 'reviewed' | 'conflict' | 'empty' | 'n_a'
  candidates?: Candidate[]
  conflict_resolution?: {
    resolved_by?: string
    resolution_method?: string
    selected_candidate_id?: number
    resolved_at?: string
  }
  // Phase 4: Citation system fields for deep links
  primary_source_doc_id?: string | null
  primary_source_char_start?: number | null
  primary_source_char_end?: number | null
  verified_flag?: boolean | null
}

export interface TabularRow {
  file_id: string
  file_name: string
  file_type?: string
  status: 'not_reviewed' | 'reviewed' | 'flagged' | 'pending_clarification'
  cells: Record<string, TabularCell>
}

export interface TableData {
  review: {
    id: string
    name: string
    description?: string
    status: string
    selected_file_ids?: string[]
    table_mode?: 'document' | 'entity' | 'fact'
    entity_config?: any
  }
  columns: TabularColumn[]
  rows: TabularRow[]
}

export interface CellDetails {
  id: string
  cell_value: string | null
  normalized_value?: string | null
  verbatim_extract?: string | null
  reasoning?: string | null
  source_references?: SourceReference[]
  confidence_score?: number | null
  source_page?: number | null
  source_section?: string | null
  status: string
  column_type?: string
  has_verbatim?: boolean
  highlight_mode?: 'verbatim' | 'page' | 'none'
  candidates?: Candidate[]
  conflict_resolution?: {
    resolved_by?: string
    resolution_method?: string
    selected_candidate_id?: number
    resolved_at?: string
  }
  // Phase 4: Citation system fields for deep links
  primary_source_doc_id?: string | null
  primary_source_char_start?: number | null
  primary_source_char_end?: number | null
  verified_flag?: boolean | null
}

export interface CreateFromDescriptionPayload {
  description: string
  existing_review_id?: string | null
}

export interface CreateFromDescriptionResponse {
  status: string
  message: string
  review_id?: string
  clarificationQuestions?: string[]
}

// API functions
export const tabularReviewApi = {
  // List tabular reviews
  async listReviews(caseId?: string, skip: number = 0, limit: number = 20): Promise<{
    reviews: Array<{
      id: string
      case_id: string
      name: string
      description?: string
      status: string
      created_at?: string
      updated_at?: string
    }>
    total: number
    skip: number
    limit: number
  }> {
    try {
      const params: any = { skip, limit }
      if (caseId) {
        params.case_id = caseId
      }
      const response = await apiClient.get('/api/tabular-review/', {
        params,
      })
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Create a new tabular review
  async createReview(
    caseId: string, 
    name: string, 
    description?: string,
    selectedFileIds?: string[]
  ): Promise<TabularReview> {
    try {
      const response = await apiClient.post('/api/tabular-review/', {
        case_id: caseId,
        name,
        description,
        selected_file_ids: selectedFileIds,
      })
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Delete a tabular review
  async deleteReview(reviewId: string): Promise<void> {
    try {
      await apiClient.delete(`/api/tabular-review/${reviewId}`)
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Get tabular review details (use table-data endpoint for consistency)
  async getReview(reviewId: string): Promise<TableData> {
    try {
      const response = await apiClient.get(`/api/tabular-review/${reviewId}/table-data`)
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Get table data
  async getTableData(reviewId: string): Promise<TableData> {
    try {
      const response = await apiClient.get(`/api/tabular-review/${reviewId}/table-data`)
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  async updateTableMode(
    reviewId: string,
    tableMode: "document" | "entity" | "fact",
    entityConfig?: any
  ): Promise<{
    id: string
    table_mode: "document" | "entity" | "fact"
    entity_config?: any
  }> {
    try {
      const response = await apiClient.patch(`/api/tabular-review/${reviewId}/mode`, {
        table_mode: tableMode,
        entity_config: entityConfig,
      })
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Add a column
  async addColumn(
    reviewId: string,
    columnLabel: string,
    columnType: string,
    prompt: string,
    columnConfig?: {
      options?: Array<{ label: string; color: string }>
      allow_custom?: boolean
    }
  ): Promise<TabularColumn> {
    try {
      const response = await apiClient.post(`/api/tabular-review/${reviewId}/columns`, {
        column_label: columnLabel,
        column_type: columnType,
        prompt,
        column_config: columnConfig,
      })
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Update column
  async updateColumn(
    reviewId: string,
    columnId: string,
    updates: {
      column_label?: string
      prompt?: string
      column_config?: {
        options?: Array<{ label: string; color: string }>
        allow_custom?: boolean
      }
    }
  ): Promise<TabularColumn> {
    try {
      const response = await apiClient.patch(
        `/api/tabular-review/${reviewId}/columns/${columnId}`,
        updates
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Delete column
  async deleteColumn(reviewId: string, columnId: string): Promise<void> {
    try {
      await apiClient.delete(`/api/tabular-review/${reviewId}/columns/${columnId}`)
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Reorder columns
  async reorderColumns(reviewId: string, columnIds: string[]): Promise<TabularColumn[]> {
    try {
      const response = await apiClient.post(`/api/tabular-review/${reviewId}/columns/reorder`, {
        column_ids: columnIds,
      })
      return response.data.columns
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Run extraction
  async runExtraction(reviewId: string): Promise<{
    status: string
    saved_count: number
    error_count: number
    total_tasks: number
  }> {
    try {
      const response = await apiClient.post(`/api/tabular-review/${reviewId}/run`)
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Run extraction for a specific column
  async runColumnExtraction(
    reviewId: string,
    columnId: string
  ): Promise<{
    status: string
    saved_count: number
    error_count: number
    total_tasks: number
    column_id: string
  }> {
    try {
      const response = await apiClient.post(
        `/api/tabular-review/${reviewId}/columns/${columnId}/run`
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Get cell details
  async getCellDetails(
    reviewId: string,
    fileId: string,
    columnId: string
  ): Promise<CellDetails> {
    try {
      const response = await apiClient.get(
        `/api/tabular-review/${reviewId}/cell/${fileId}/${columnId}`
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Update cell
  async updateCell(
    reviewId: string,
    fileId: string,
    columnId: string,
    cellValue: string,
    isManualOverride: boolean = true
  ): Promise<{
    id: string
    cell_value: string
    status: string
    updated_at?: string
  }> {
    try {
      const response = await apiClient.patch(
        `/api/tabular-review/${reviewId}/cells/${fileId}/${columnId}`,
        {
          cell_value: cellValue,
          is_manual_override: isManualOverride,
        }
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Update document status
  async updateDocumentStatus(
    reviewId: string,
    fileId: string,
    status: string
  ): Promise<{ id: string; file_id: string; status: string; locked: boolean }> {
    try {
      const response = await apiClient.post(
        `/api/tabular-review/${reviewId}/document-status`,
        {
          file_id: fileId,
          status,
        }
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Bulk update document status
  async bulkUpdateStatus(
    reviewId: string,
    fileIds: string[],
    status: string
  ): Promise<{ success: boolean; updated_count: number }> {
    try {
      const response = await apiClient.post(
        `/api/tabular-review/${reviewId}/bulk/status`,
        {
          file_ids: fileIds,
          status,
        }
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Bulk run extraction
  async bulkRunExtraction(
    reviewId: string,
    fileIds: string[],
    columnIds: string[]
  ): Promise<{
    status: string
    saved_count: number
    error_count: number
    total_tasks: number
    files_processed: number
    columns_processed: number
  }> {
    try {
      const response = await apiClient.post(
        `/api/tabular-review/${reviewId}/bulk/run`,
        {
          file_ids: fileIds,
          column_ids: columnIds,
        }
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Bulk delete rows
  async bulkDeleteRows(
    reviewId: string,
    fileIds: string[]
  ): Promise<{ success: boolean; deleted_count: number }> {
    try {
      const response = await apiClient.delete(
        `/api/tabular-review/${reviewId}/bulk/rows`,
        {
          data: {
            file_ids: fileIds,
          },
        }
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Get cell history
  async getCellHistory(
    reviewId: string,
    fileId: string,
    columnId: string,
    limit: number = 50
  ): Promise<
    Array<{
      id: string
      cell_value: string | null
      verbatim_extract: string | null
      reasoning: string | null
      source_references: any
      confidence_score: number | null
      source_page: number | null
      source_section: string | null
      status: string
      changed_by: string | null
      change_type: string
      previous_cell_value: string | null
      change_reason: string | null
      created_at: string
    }>
  > {
    try {
      const response = await apiClient.get(
        `/api/tabular-review/${reviewId}/cells/${fileId}/${columnId}/history`,
        {
          params: { limit },
        }
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Revert cell to version
  async revertCell(
    reviewId: string,
    fileId: string,
    columnId: string,
    historyId: string,
    changeReason?: string
  ): Promise<{ id: string; cell_value: string | null; status: string; updated_at: string }> {
    try {
      const response = await apiClient.post(
        `/api/tabular-review/${reviewId}/cells/${fileId}/${columnId}/revert`,
        {
          history_id: historyId,
          change_reason: changeReason,
        }
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Get cell diff
  async getCellDiff(
    reviewId: string,
    fileId: string,
    columnId: string,
    historyId1: string,
    historyId2: string
  ): Promise<{
    cell_value: { old: string | null; new: string | null; changed: boolean }
    verbatim_extract: { old: string | null; new: string | null; changed: boolean }
    reasoning: { old: string | null; new: string | null; changed: boolean }
    confidence_score: { old: number | null; new: number | null; changed: boolean }
    source_page: { old: number | null; new: number | null; changed: boolean }
    source_section: { old: string | null; new: string | null; changed: boolean }
    status: { old: string; new: string; changed: boolean }
  }> {
    try {
      const response = await apiClient.get(
        `/api/tabular-review/${reviewId}/cells/${fileId}/${columnId}/diff`,
        {
          params: {
            history_id_1: historyId1,
            history_id_2: historyId2,
          },
        }
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Export to CSV
  async exportToCSV(reviewId: string): Promise<Blob> {
    try {
      const response = await apiClient.post(
        `/api/tabular-review/${reviewId}/export/csv`,
        {},
        { responseType: 'blob' }
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Export to Excel
  async exportToExcel(reviewId: string): Promise<Blob> {
    try {
      const response = await apiClient.post(
        `/api/tabular-review/${reviewId}/export/excel`,
        {},
        { responseType: 'blob' }
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Get templates
  async getTemplates(params?: {
    category?: string
    featured?: boolean
    search?: string
  }): Promise<Array<{
    id: string
    name: string
    description?: string
    columns: any[]
    is_public: boolean
    is_system?: boolean
    is_featured?: boolean
    category?: string
    tags?: string[]
    usage_count?: number
    created_at?: string
  }>> {
    try {
      const response = await apiClient.get('/api/tabular-review/templates', { params })
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Apply template to review
  async applyTemplate(
    reviewId: string,
    templateId: string
  ): Promise<{
    message: string
    columns: Array<{ id: string; column_label: string; column_type: string }>
  }> {
    try {
      const response = await apiClient.post(
        `/api/tabular-review/${reviewId}/templates/apply?template_id=${templateId}`
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Save template
  async saveTemplate(
    name: string,
    description: string,
    columns: any[],
    isPublic: boolean = false,
    category?: string,
    tags?: string[],
    isFeatured: boolean = false
  ): Promise<{ 
    id: string
    name: string
    columns: any[]
    category?: string
    tags?: string[]
    is_featured?: boolean
  }> {
    try {
      const response = await apiClient.post('/api/tabular-review/templates', {
        name,
        description,
        columns,
        is_public: isPublic,
        category,
        tags,
        is_featured: isFeatured,
      })
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Update selected files
  async updateSelectedFiles(
    reviewId: string,
    fileIds: string[]
  ): Promise<{ id: string; selected_file_ids: string[]; message: string }> {
    try {
      const response = await apiClient.post(`/api/tabular-review/${reviewId}/files`, {
        file_ids: fileIds,
      })
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Get available files
  async getAvailableFiles(reviewId: string): Promise<{
    files: Array<{
      id: string
      filename: string
      file_type?: string
      created_at?: string
    }>
    total: number
    selected_count: number
  }> {
    try {
      const response = await apiClient.get(`/api/tabular-review/${reviewId}/available-files`)
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Resolve conflict
  async resolveConflict(
    reviewId: string,
    fileId: string,
    columnId: string,
    selectedCandidateId: number,
    resolutionMethod: 'select' | 'merge' | 'n_a' = 'select'
  ): Promise<{
    id: string
    cell_value: string
    status: string
    updated_at: string
  }> {
    try {
      const response = await apiClient.patch(
        `/api/tabular-review/${reviewId}/cells/${fileId}/${columnId}/resolve-conflict`,
        {
          selected_candidate_id: selectedCandidateId,
          resolution_method: resolutionMethod,
        }
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Chat over table
  async chatOverTable(
    reviewId: string,
    question: string
  ): Promise<{
    answer: string
    citations: Array<{ file: string; file_id: string }>
    table_stats: {
      total_rows: number
      total_columns: number
    }
  }> {
    try {
      const response = await apiClient.post(`/api/tabular-review/${reviewId}/chat`, {
        question,
      })
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Generate column prompt using AI
  async generateColumnPrompt(
    columnLabel: string,
    columnType: string
  ): Promise<{ prompt: string }> {
    try {
      const response = await apiClient.post('/api/tabular-review/columns/generate-prompt', {
        column_label: columnLabel,
        column_type: columnType,
      })
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Review Queue
  async getReviewQueue(
    reviewId: string,
    includeReviewed: boolean = false
  ): Promise<{
    items: Array<{
      id: string
      file_id: string
      column_id: string
      cell_id: string
      priority: number
      reason: string
      is_reviewed: boolean
      reviewed_by?: string | null
      reviewed_at?: string | null
      created_at: string
    }>
    stats: {
      total_items: number
      by_reason: Record<string, number>
      by_priority: Record<number, number>
      high_priority_count: number
    }
  }> {
    try {
      const response = await apiClient.get(`/api/tabular-review/${reviewId}/review-queue`, {
        params: { include_reviewed: includeReviewed },
      })
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  async rebuildReviewQueue(reviewId: string): Promise<{
    message: string
    stats: {
      total_items: number
      by_reason: Record<string, number>
      by_priority: Record<number, number>
      high_priority_count: number
    }
  }> {
    try {
      const response = await apiClient.post(`/api/tabular-review/${reviewId}/review-queue/rebuild`)
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  async markQueueItemReviewed(
    reviewId: string,
    itemId: string
  ): Promise<{
    id: string
    is_reviewed: boolean
    reviewed_at: string | null
  }> {
    try {
      const response = await apiClient.patch(
        `/api/tabular-review/${reviewId}/review-queue/${itemId}/mark-reviewed`
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  // Smart column creation
  async createColumnFromDescription(
    reviewId: string,
    description: string
  ): Promise<{
    id: string
    column_label: string
    column_type: string
    prompt: string
    column_config?: any
    order_index: number
  }> {
    try {
      const response = await apiClient.post(
        `/api/tabular-review/${reviewId}/columns/smart-from-description`,
        { description }
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  async createColumnFromExamples(
    reviewId: string,
    examples: Array<{
      document_text: string
      expected_value: string
      context?: string
    }>
  ): Promise<{
    id: string
    column_label: string
    column_type: string
    prompt: string
    column_config?: any
    order_index: number
  }> {
    try {
      const response = await apiClient.post(
        `/api/tabular-review/${reviewId}/columns/smart-from-examples`,
        { examples }
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },

  async createFromDescription(
    caseId: string,
    payload: CreateFromDescriptionPayload,
  ): Promise<CreateFromDescriptionResponse> {
    try {
      const response = await apiClient.post(
        '/api/tabular-review/create-from-description',
        {
          case_id: caseId,
          ...payload,
        },
      )
      return response.data
    } catch (error) {
      throw new Error(extractErrorMessage(error))
    }
  },
}

