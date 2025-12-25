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
  created_at: string
}

export interface TabularColumn {
  id: string
  column_label: string
  column_type: 'text' | 'date' | 'currency' | 'number' | 'yes_no' | 'tags' | 'verbatim'
  prompt: string
  order_index: number
}

export interface TabularCell {
  cell_value: string | null
  verbatim_extract?: string | null
  reasoning?: string | null
  confidence_score?: number | null
  source_page?: number | null
  source_section?: string | null
  status: 'pending' | 'processing' | 'completed' | 'reviewed'
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
  }
  columns: TabularColumn[]
  rows: TabularRow[]
}

export interface CellDetails {
  id: string
  cell_value: string | null
  verbatim_extract?: string | null
  reasoning?: string | null
  confidence_score?: number | null
  source_page?: number | null
  source_section?: string | null
  status: string
  column_type?: string
  has_verbatim?: boolean
  highlight_mode?: 'verbatim' | 'page' | 'none'
}

// API functions
export const tabularReviewApi = {
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

  // Add a column
  async addColumn(
    reviewId: string,
    columnLabel: string,
    columnType: string,
    prompt: string
  ): Promise<TabularColumn> {
    try {
      const response = await apiClient.post(`/api/tabular-review/${reviewId}/columns`, {
        column_label: columnLabel,
        column_type: columnType,
        prompt,
      })
      return response.data
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
  async getTemplates(): Promise<Array<{
    id: string
    name: string
    description?: string
    columns: any[]
    is_public: boolean
  }>> {
    try {
      const response = await apiClient.get('/api/tabular-review/templates')
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
    isPublic: boolean = false
  ): Promise<{ id: string; name: string; columns: any[] }> {
    try {
      const response = await apiClient.post('/api/tabular-review/templates', {
        name,
        description,
        columns,
        is_public: isPublic,
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
}

