import axios from 'axios'
import { extractErrorMessage } from './api'
import type { ColumnValueFilterCondition } from '@/utils/tabularColumnFilters'

const BASE_URL = import.meta.env.VITE_API_URL || ''

const apiClient = axios.create({ baseURL: BASE_URL })

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token && config.headers) {
    config.headers['X-Access-Token'] = token
  }
  return config
})

export interface OperationsAvailableFile {
  file_id: string
  filename: string
  transaction_count: number
  date_min?: string | null
  date_max?: string | null
}

export type OperationsFlowFilter = 'all' | 'debit' | 'credit'

export interface OperationSourceReference {
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

export interface OperationTransaction {
  id: string
  file_id: string
  source_filename?: string | null
  global_row_index: number
  operation_date?: string | null
  operation_datetime_text?: string | null
  amount_rub?: number | null
  amount_raw?: string | null
  description?: string | null
  row_columns: Record<string, string>
  page_start?: number | null
  flow_direction?: 'debit' | 'credit' | null
  verbatim_row_text?: string | null
  source_references?: OperationSourceReference[]
  highlight_fragments?: string[]
}

export interface OperationsSummary {
  total: number
  returned: number
  amount_sum_rub: number
  date_min?: string | null
  date_max?: string | null
  file_count: number
}

export interface OperationsTransactionsResponse {
  transactions: OperationTransaction[]
  summary: OperationsSummary
  column_headers: string[]
}

export interface OperationsListParams {
  fileId: string
  dateFrom?: string
  dateTo?: string
  search?: string
  minAmount?: string
  maxAmount?: string
  flow?: Exclude<OperationsFlowFilter, 'all'>
  limit?: number
  offset?: number
}

export interface OperationsSessionUiState {
  valueFilters: ColumnValueFilterCondition[]
  rowSearch: string
}

export interface OperationsSession {
  file_id: string
  filename?: string | null
  ui_state: {
    value_filters?: ColumnValueFilterCondition[]
    row_search?: string
  }
  updated_at?: string | null
}

export interface OperationsSessionSummary {
  file_id: string
  filename?: string | null
  updated_at?: string | null
  transaction_count?: number | null
  date_min?: string | null
  date_max?: string | null
}

function parseSessionUiState(raw: OperationsSession['ui_state'] | undefined): OperationsSessionUiState {
  const filters = raw?.value_filters ?? []
  return {
    valueFilters: filters.map((c) => ({
      columnId: c.columnId ?? '',
      operator: c.operator ?? 'equals',
      selectedValues: [...(c.selectedValues ?? [])],
      textQuery: c.textQuery ?? '',
      dateFrom: c.dateFrom ?? null,
      dateTo: c.dateTo ?? null,
      numberFrom: c.numberFrom ?? null,
      numberTo: c.numberTo ?? null,
    })),
    rowSearch: raw?.row_search ?? '',
  }
}

function buildQueryParams(params: OperationsListParams): Record<string, string | number> {
  const query: Record<string, string | number> = {
    file_id: params.fileId,
  }
  if (params.dateFrom) query.date_from = params.dateFrom
  if (params.dateTo) query.date_to = params.dateTo
  if (params.search) query.search = params.search
  if (params.minAmount) query.min_amount = params.minAmount
  if (params.maxAmount) query.max_amount = params.maxAmount
  if (params.flow) query.flow = params.flow
  if (params.limit != null) query.limit = params.limit
  if (params.offset != null) query.offset = params.offset
  return query
}

export const operationsApi = {
  async listAvailableFiles(caseId: string): Promise<OperationsAvailableFile[]> {
    const response = await apiClient.get<{ files: OperationsAvailableFile[] }>(
      `/api/cases/${caseId}/operations/available-files`,
    )
    return response.data.files || []
  },

  async listTransactions(
    caseId: string,
    params: OperationsListParams,
  ): Promise<OperationsTransactionsResponse> {
    const response = await apiClient.get<OperationsTransactionsResponse>(
      `/api/cases/${caseId}/operations/transactions`,
      { params: buildQueryParams(params) },
    )
    return response.data
  },

  async exportTransactions(
    caseId: string,
    params: OperationsListParams & { format: 'excel' | 'csv' },
  ): Promise<Blob> {
    const response = await apiClient.get(`/api/cases/${caseId}/operations/export`, {
      params: { ...buildQueryParams(params), format: params.format },
      responseType: 'blob',
    })
    return response.data
  },

  async listSessions(caseId: string): Promise<OperationsSessionSummary[]> {
    const response = await apiClient.get<{ sessions: OperationsSessionSummary[] }>(
      `/api/cases/${caseId}/operations/sessions`,
    )
    return response.data.sessions || []
  },

  async getSession(caseId: string, fileId: string): Promise<OperationsSessionUiState> {
    const response = await apiClient.get<OperationsSession>(
      `/api/cases/${caseId}/operations/session`,
      { params: { file_id: fileId } },
    )
    return parseSessionUiState(response.data.ui_state)
  },

  async saveSession(
    caseId: string,
    fileId: string,
    uiState: OperationsSessionUiState,
    filename?: string,
  ): Promise<void> {
    await apiClient.put(`/api/cases/${caseId}/operations/session`, {
      file_id: fileId,
      filename,
      ui_state: {
        value_filters: uiState.valueFilters,
        row_search: uiState.rowSearch,
      },
    })
  },

  async touchSession(caseId: string, fileId: string, filename?: string): Promise<void> {
    await apiClient.post(`/api/cases/${caseId}/operations/session/touch`, null, {
      params: { file_id: fileId, ...(filename ? { filename } : {}) },
    })
  },

  async getChatHistory(caseId: string, fileId: string): Promise<
    Array<{
      id: string
      role: 'user' | 'assistant'
      content: string
      citations?: Array<{ file: string; file_id: string }>
    }>
  > {
    const response = await apiClient.get<{ messages: Array<{ id: string; role: 'user' | 'assistant'; content: string; citations?: Array<{ file: string; file_id: string }> }> }>(
      `/api/cases/${caseId}/operations/chat/history`,
      { params: { file_id: fileId } },
    )
    return response.data.messages || []
  },

  async chatStream(
    caseId: string,
    question: string,
    fileId: string,
    uiState: OperationsSessionUiState,
    callbacks: {
      onTextDelta?: (delta: string) => void
      onDone?: (payload: {
        answer: string
        citations: Array<{ file: string; file_id: string }>
        table_stats: Record<string, number>
      }) => void
      onError?: (message: string) => void
    },
    signal?: AbortSignal,
  ): Promise<void> {
    const token = localStorage.getItem('access_token')
    const response = await fetch(`${BASE_URL}/api/cases/${caseId}/operations/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Access-Token': token || '',
      },
      body: JSON.stringify({
        question,
        file_id: fileId,
        ui_state: {
          value_filters: uiState.valueFilters,
          row_search: uiState.rowSearch,
        },
      }),
      signal,
    })

    if (!response.ok) {
      const message = `HTTP error! status: ${response.status}`
      callbacks.onError?.(message)
      throw new Error(message)
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    if (!reader) throw new Error('No response body')

    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) {
        const lines = part.split('\n')
        let eventType = ''
        let data = ''
        for (const line of lines) {
          if (line.startsWith('event:')) eventType = line.slice(6).trim()
          else if (line.startsWith('data:')) data += line.slice(5).trim()
        }
        if (!data) continue
        try {
          const payload = JSON.parse(data)
          if (eventType === 'text_delta' || payload.type === 'text_delta') {
            const delta = payload.text || payload.delta || ''
            if (delta) callbacks.onTextDelta?.(delta)
          } else if (eventType === 'tabular_chat_done' || payload.type === 'tabular_chat_done') {
            callbacks.onDone?.({
              answer: payload.answer || '',
              citations: payload.citations || [],
              table_stats: payload.table_stats || {},
            })
          } else if (eventType === 'error' || payload.type === 'error') {
            callbacks.onError?.(payload.message || 'Ошибка чата')
          }
        } catch {
          // ignore malformed chunks
        }
      }
    }
  },
}

export function formatOperationsError(error: unknown): string {
  return extractErrorMessage(error)
}
