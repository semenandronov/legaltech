import axios from 'axios'
import { extractErrorMessage } from './api'
import type { AssistantActivityPayload } from '@/lib/assistantActivity'
import type { ColumnValueFilterCondition } from '@/utils/tabularColumnFilters'
import type { BankruptcyPeriodId, OperationsViewMode } from '@/utils/operationsBankruptcyPeriods'
import { assertDownloadBlob, extractBlobErrorMessage } from '@/utils/fileDownload'

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
  excludeOperationalNoise?: boolean
  descriptionExact?: string
  limit?: number
  offset?: number
}

export interface OperationsSessionUiState {
  valueFilters: ColumnValueFilterCondition[]
  rowSearch: string
  petitionDate: string
  activePeriod: BankruptcyPeriodId | null
  hideOperationalNoise: boolean
  viewMode: OperationsViewMode
  basketIds: string[]
}

export interface OperationsPeriodInsight {
  period_id: BankruptcyPeriodId
  label: string
  date_from: string
  date_to: string
  count: number
}

export interface OperationsAnalysisInsights {
  petition_date?: string | null
  total_operations: number
  operational_noise_count: number
  filtered_count: number
  periods: OperationsPeriodInsight[]
}

export interface OperationsCounterpartyGroup {
  description: string
  op_count: number
  amount_sum_rub: number
  abs_amount_sum_rub: number
}

export interface OperationsCounterpartyGroupsResponse {
  groups: OperationsCounterpartyGroup[]
  returned: number
  total_groups: number
}

export interface OperationsAnalysisParams {
  fileId: string
  petitionDate?: string
  excludeOperationalNoise?: boolean
  search?: string
  dateFrom?: string
  dateTo?: string
}

export interface OperationsSession {
  file_id: string
  filename?: string | null
  ui_state: {
    value_filters?: ColumnValueFilterCondition[]
    row_search?: string
    petition_date?: string | null
    active_period?: BankruptcyPeriodId | null
    hide_operational_noise?: boolean
    view_mode?: OperationsViewMode
    basket_ids?: string[]
    petitionDate?: string | null
    activePeriod?: BankruptcyPeriodId | null
    hideOperationalNoise?: boolean
    viewMode?: OperationsViewMode
    basketIds?: string[]
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
  const activePeriodRaw = raw?.active_period ?? raw?.activePeriod
  const viewModeRaw = raw?.view_mode ?? raw?.viewMode
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
    petitionDate: String(raw?.petition_date ?? raw?.petitionDate ?? ''),
    activePeriod:
      activePeriodRaw === '1m' || activePeriodRaw === '6m' || activePeriodRaw === '1y' || activePeriodRaw === '3y'
        ? activePeriodRaw
        : null,
    hideOperationalNoise: Boolean(raw?.hide_operational_noise ?? raw?.hideOperationalNoise ?? false),
    viewMode: viewModeRaw === 'counterparties' ? 'counterparties' : 'operations',
    basketIds: [...(raw?.basket_ids ?? raw?.basketIds ?? [])],
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
  if (params.excludeOperationalNoise) query.exclude_operational_noise = 'true'
  if (params.descriptionExact != null) query.description_exact = params.descriptionExact
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

  async getAnalysisInsights(
    caseId: string,
    params: OperationsAnalysisParams,
  ): Promise<OperationsAnalysisInsights> {
    const response = await apiClient.get<OperationsAnalysisInsights>(
      `/api/cases/${caseId}/operations/analysis-insights`,
      {
        params: {
          file_id: params.fileId,
          petition_date: params.petitionDate || undefined,
          exclude_operational_noise: params.excludeOperationalNoise ? 'true' : undefined,
          search: params.search || undefined,
        },
      },
    )
    return response.data
  },

  async listCounterpartyGroups(
    caseId: string,
    params: OperationsAnalysisParams,
  ): Promise<OperationsCounterpartyGroupsResponse> {
    const response = await apiClient.get<OperationsCounterpartyGroupsResponse>(
      `/api/cases/${caseId}/operations/counterparty-groups`,
      {
        params: {
          file_id: params.fileId,
          date_from: params.dateFrom || undefined,
          date_to: params.dateTo || undefined,
          search: params.search || undefined,
          exclude_operational_noise: params.excludeOperationalNoise ? 'true' : undefined,
        },
      },
    )
    return response.data
  },

  async exportTransactions(
    caseId: string,
    params: {
      fileId: string
      format: 'excel' | 'csv'
      /** IDs of currently visible (filtered) rows — WYSIWYG export. */
      transactionIds?: string[]
    },
  ): Promise<Blob> {
    if (!params.fileId?.trim()) {
      throw new Error('Не выбрана выписка для экспорта')
    }
    try {
      const response = await apiClient.post(
        `/api/cases/${caseId}/operations/export`,
        {
          file_id: params.fileId,
          format: params.format,
          transaction_ids: params.transactionIds?.length ? params.transactionIds : null,
        },
        { responseType: 'blob' },
      )
      return await assertDownloadBlob(response, [params.format === 'csv' ? 'csv' : 'excel'])
    } catch (error) {
      throw new Error(await extractBlobErrorMessage(error, 'Не удалось экспортировать операции'))
    }
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
        petition_date: uiState.petitionDate || null,
        active_period: uiState.activePeriod,
        hide_operational_noise: uiState.hideOperationalNoise,
        view_mode: uiState.viewMode,
        basket_ids: uiState.basketIds,
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
      onAssistantActivity?: (payload: AssistantActivityPayload) => void
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
          petition_date: uiState.petitionDate || null,
          active_period: uiState.activePeriod,
          hide_operational_noise: uiState.hideOperationalNoise,
          view_mode: uiState.viewMode,
          basket_ids: uiState.basketIds,
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
          } else if (
            eventType === 'assistant_activity' ||
            payload.type === 'assistant_activity'
          ) {
            callbacks.onAssistantActivity?.(payload as AssistantActivityPayload)
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
