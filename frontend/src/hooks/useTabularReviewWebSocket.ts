import { useEffect, useRef, useState, useCallback } from 'react'
import type { TabularCellRealtimeUpdate } from '../utils/tabularTableState'

interface TabularReviewWebSocketMessage {
  type:
    | 'connected'
    | 'cell_updated'
    | 'column_added'
    | 'column_deleted'
    | 'extraction_progress'
    | 'extraction_cell_finished'
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

export const useTabularReviewWebSocket = ({
  reviewId,
  enabled = true,
  onCellUpdated,
  onExtractionCellFinished,
  onColumnAdded,
  onColumnDeleted,
  onExtractionProgress,
  onTableCreated,
  onError,
}: UseTabularReviewWebSocketOptions) => {
  const [isConnected, setIsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttempts = useRef(0)
  const maxReconnectAttempts = 5

  const connect = useCallback(() => {
    if (!enabled || !reviewId) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = import.meta.env.VITE_API_URL?.replace(/^https?:\/\//, '') || window.location.host
    const token = localStorage.getItem('access_token')
    const tokenQuery = token ? `?token=${encodeURIComponent(token)}` : ''
    const wsUrl = `${protocol}//${host}/ws/tabular-review/${reviewId}${tokenQuery}`

    try {
      const ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        setIsConnected(true)
        reconnectAttempts.current = 0
      }

      ws.onmessage = (event) => {
        try {
          const data: TabularReviewWebSocketMessage = JSON.parse(event.data)

          switch (data.type) {
            case 'connected':
              break

            case 'cell_updated': {
              const update = parseCellUpdatedMessage(data)
              if (update && onCellUpdated) {
                onCellUpdated(update)
              }
              break
            }

            case 'extraction_cell_finished':
              if (onExtractionCellFinished && data.column_id && data.file_id) {
                onExtractionCellFinished({
                  column_id: data.column_id,
                  file_id: data.file_id,
                  success: Boolean(data.success),
                })
              }
              break

            case 'column_added':
              if (onColumnAdded && data.column) {
                onColumnAdded(data.column)
              }
              break

            case 'column_deleted':
              if (onColumnDeleted && data.column_id) {
                onColumnDeleted(data.column_id)
              }
              break

            case 'extraction_progress':
              if (onExtractionProgress && data.progress) {
                onExtractionProgress(data.progress)
              }
              break

            case 'table_created':
              if (onTableCreated && data.table) {
                onTableCreated(data.table)
              }
              break

            case 'error':
              if (onError) {
                onError(data.message || 'Ошибка WebSocket')
              }
              break

            default:
              break
          }
        } catch (error) {
          console.error('Error parsing Tabular Review WebSocket message:', error)
          if (onError) {
            onError('Ошибка при обработке сообщения')
          }
        }
      }

      ws.onerror = () => {
        setIsConnected(false)
      }

      ws.onclose = () => {
        setIsConnected(false)

        if (reconnectAttempts.current < maxReconnectAttempts && enabled && reviewId) {
          reconnectAttempts.current++
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 10000)
          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, delay)
        } else if (reconnectAttempts.current >= maxReconnectAttempts) {
          if (onError) {
            onError('Не удалось подключиться к обновлениям таблицы')
          }
        }
      }

      wsRef.current = ws
    } catch (error) {
      console.error('Error creating Tabular Review WebSocket:', error)
      if (onError) {
        onError('Ошибка при создании соединения')
      }
    }
  }, [
    reviewId,
    enabled,
    onCellUpdated,
    onExtractionCellFinished,
    onColumnAdded,
    onColumnDeleted,
    onExtractionProgress,
    onTableCreated,
    onError,
  ])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setIsConnected(false)
  }, [])

  useEffect(() => {
    if (enabled && reviewId) {
      connect()
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
