import { useEffect, useRef, useState, useCallback } from 'react'
import { tabularReviewApi } from '../services/tabularReviewApi'
import type { TabularCellRealtimeUpdate } from '../utils/tabularTableState'

interface TabularReviewWebSocketMessage {
  type:
    | 'connected'
    | 'cell_updated'
    | 'column_added'
    | 'column_deleted'
    | 'extraction_progress'
    | 'extraction_cell_finished'
    | 'column_extraction_completed'
    | 'error'
    | 'table_created'
  cell_id?: string
  file_id?: string
  column_id?: string
  cell_value?: string | null
  normalized_value?: string | null
  verbatim_extract?: string | null
  reasoning?: string | null
  source_references?: Array<{ page?: number | null; section?: string | null; text: string }>
  status?: string
  confidence_score?: number | null
  source_page?: number | null
  source_section?: string | null
  success?: boolean
  cell?: {
    id?: string
    cell_value?: string | null
    status?: string
  }
  column?: {
    id: string
    column_label: string
    column_type: string
    prompt: string
    column_config?: unknown
    order_index: number
  }
  progress?: {
    column_id: string
    progress: number
    total: number
    saved_count?: number
    error_count?: number
  }
  table?: {
    id: string
    name: string
    description?: string
    columns_count?: number
    rows_count?: number
  }
  message?: string
  review_id?: string
  saved_count?: number
  filled_count?: number
  error_count?: number
  total_tasks?: number
}

interface UseTabularReviewWebSocketOptions {
  reviewId: string | null
  enabled?: boolean
  onCellUpdated?: (data: TabularCellRealtimeUpdate) => void
  onExtractionCellFinished?: (data: {
    column_id: string
    file_id: string
    success: boolean
  }) => void
  onColumnAdded?: (column: TabularReviewWebSocketMessage['column']) => void
  onColumnDeleted?: (columnId: string) => void
  onExtractionProgress?: (progress: {
    column_id: string
    progress: number
    total: number
    saved_count?: number
    error_count?: number
  }) => void
  onColumnExtractionCompleted?: (data: {
    column_id: string
    status: string
    saved_count?: number
    filled_count?: number
    error_count?: number
    total_tasks?: number
    message?: string
  }) => void
  onTableCreated?: (table: NonNullable<TabularReviewWebSocketMessage['table']>) => void
  onError?: (error: string) => void
}

function parseCellUpdatedMessage(data: TabularReviewWebSocketMessage): TabularCellRealtimeUpdate | null {
  const fileId = data.file_id
  const columnId = data.column_id
  if (!fileId || !columnId) {
    return null
  }
  return {
    cell_id: data.cell_id ?? data.cell?.id,
    file_id: fileId,
    column_id: columnId,
    cell_value: data.cell_value ?? data.cell?.cell_value ?? null,
    normalized_value: data.normalized_value ?? undefined,
    verbatim_extract: data.verbatim_extract ?? undefined,
    reasoning: data.reasoning ?? undefined,
    confidence_score: data.confidence_score ?? undefined,
    source_page: data.source_page ?? undefined,
    source_section: data.source_section ?? undefined,
    source_references: data.source_references,
    status: (data.status ?? data.cell?.status ?? 'completed') as TabularCellRealtimeUpdate['status'],
  }
}

function resolveWebSocketHost(): string {
  // In Vite dev, route WS through the dev-server proxy (/ws → backend) for reliable auth + delivery.
  if (import.meta.env.DEV && import.meta.env.VITE_TABULAR_WS_USE_PROXY !== 'false') {
    return window.location.host
  }
  const apiHost = import.meta.env.VITE_API_URL?.replace(/^https?:\/\//, '')
  return apiHost || window.location.host
}

function isBenignWebSocketClose(event: CloseEvent): boolean {
  return event.code === 1000 || event.code === 1001 || event.code === 1006
}

export const useTabularReviewWebSocket = ({
  reviewId,
  enabled = true,
  onCellUpdated,
  onExtractionCellFinished,
  onColumnAdded,
  onColumnDeleted,
  onExtractionProgress,
  onColumnExtractionCompleted,
  onTableCreated,
  onError,
}: UseTabularReviewWebSocketOptions) => {
  const [isConnected, setIsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttempts = useRef(0)
  const connectGenerationRef = useRef(0)
  const intentionalCloseRef = useRef(false)
  const maxReconnectAttempts = 5

  const callbacksRef = useRef({
    onCellUpdated,
    onExtractionCellFinished,
    onColumnAdded,
    onColumnDeleted,
    onExtractionProgress,
    onColumnExtractionCompleted,
    onTableCreated,
    onError,
  })
  callbacksRef.current = {
    onCellUpdated,
    onExtractionCellFinished,
    onColumnAdded,
    onColumnDeleted,
    onExtractionProgress,
    onColumnExtractionCompleted,
    onTableCreated,
    onError,
  }

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
  }, [])

  const closeActiveSocket = useCallback(() => {
    const active = wsRef.current
    if (!active) return
    wsRef.current = null
    active.onopen = null
    active.onmessage = null
    active.onerror = null
    active.onclose = null
    if (active.readyState === WebSocket.CONNECTING || active.readyState === WebSocket.OPEN) {
      active.close(1000, 'client disconnect')
    }
  }, [])

  const connect = useCallback(async () => {
    if (!enabled || !reviewId) return

    clearReconnectTimer()
    closeActiveSocket()

    const generation = ++connectGenerationRef.current
    intentionalCloseRef.current = false

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = resolveWebSocketHost()

    try {
      const { ticket } = await tabularReviewApi.createWebSocketTicket(reviewId)
      if (generation !== connectGenerationRef.current || intentionalCloseRef.current) return
      const wsUrl = `${protocol}//${host}/ws/tabular-review/${reviewId}?ticket=${encodeURIComponent(ticket)}`
      const ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        if (generation !== connectGenerationRef.current) {
          ws.close(1000, 'stale connection')
          return
        }
        setIsConnected(true)
        reconnectAttempts.current = 0
      }

      ws.onmessage = (event) => {
        if (generation !== connectGenerationRef.current) return

        try {
          const data: TabularReviewWebSocketMessage = JSON.parse(event.data)
          const callbacks = callbacksRef.current

          switch (data.type) {
            case 'connected':
              break

            case 'cell_updated': {
              const update = parseCellUpdatedMessage(data)
              if (update && callbacks.onCellUpdated) {
                callbacks.onCellUpdated(update)
              }
              break
            }

            case 'extraction_cell_finished':
              if (callbacks.onExtractionCellFinished && data.column_id && data.file_id) {
                callbacks.onExtractionCellFinished({
                  column_id: data.column_id,
                  file_id: data.file_id,
                  success: Boolean(data.success),
                })
              }
              break

            case 'column_added':
              if (callbacks.onColumnAdded && data.column) {
                callbacks.onColumnAdded(data.column)
              }
              break

            case 'column_deleted':
              if (callbacks.onColumnDeleted && data.column_id) {
                callbacks.onColumnDeleted(data.column_id)
              }
              break

            case 'extraction_progress':
              if (callbacks.onExtractionProgress && data.progress) {
                callbacks.onExtractionProgress(data.progress)
              }
              break

            case 'column_extraction_completed':
              if (callbacks.onColumnExtractionCompleted && data.column_id) {
                callbacks.onColumnExtractionCompleted({
                  column_id: data.column_id,
                  status: data.status ?? 'completed',
                  saved_count: data.saved_count,
                  filled_count: data.filled_count,
                  error_count: data.error_count,
                  total_tasks: data.total_tasks,
                  message: data.message,
                })
              }
              break

            case 'table_created':
              if (callbacks.onTableCreated && data.table) {
                callbacks.onTableCreated(data.table)
              }
              break

            case 'error':
              if (callbacks.onError) {
                callbacks.onError(data.message || 'Ошибка WebSocket')
              }
              break

            default:
              break
          }
        } catch (error) {
          console.error('Error parsing Tabular Review WebSocket message:', error)
          callbacksRef.current.onError?.('Ошибка при обработке сообщения')
        }
      }

      ws.onerror = () => {
        if (generation !== connectGenerationRef.current) return
        setIsConnected(false)
      }

      ws.onclose = (event) => {
        if (generation !== connectGenerationRef.current) return

        setIsConnected(false)
        if (wsRef.current === ws) {
          wsRef.current = null
        }

        if (intentionalCloseRef.current || !enabled || !reviewId) {
          return
        }

        if (isBenignWebSocketClose(event) && reconnectAttempts.current < maxReconnectAttempts) {
          reconnectAttempts.current++
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 10000)
          reconnectTimeoutRef.current = setTimeout(() => {
            void connect()
          }, delay)
          return
        }

        if (reconnectAttempts.current >= maxReconnectAttempts && callbacksRef.current.onError) {
          callbacksRef.current.onError('Не удалось подключиться к обновлениям таблицы')
        }
      }

      wsRef.current = ws
    } catch (error) {
      console.error('Error creating Tabular Review WebSocket:', error)
      callbacksRef.current.onError?.('Ошибка при создании соединения')
    }
  }, [reviewId, enabled, clearReconnectTimer, closeActiveSocket])

  const disconnect = useCallback(() => {
    intentionalCloseRef.current = true
    connectGenerationRef.current++
    clearReconnectTimer()
    closeActiveSocket()
    setIsConnected(false)
  }, [clearReconnectTimer, closeActiveSocket])

  useEffect(() => {
    if (enabled && reviewId) {
      void connect()
    } else {
      disconnect()
    }

    return () => {
      disconnect()
    }
  }, [enabled, reviewId, connect, disconnect])

  return {
    isConnected,
    disconnect,
  }
}
