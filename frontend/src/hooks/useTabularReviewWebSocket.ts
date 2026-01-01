import { useEffect, useRef, useState, useCallback } from 'react'

interface TabularReviewWebSocketMessage {
  type: 'connected' | 'cell_updated' | 'column_added' | 'extraction_progress' | 'error' | 'table_created'
  cell_id?: string
  file_id?: string
  column_id?: string
  cell_value?: string | null
  reasoning?: string | null
  source_references?: Array<{ page?: number | null; section?: string | null; text: string }>
  status?: string
  confidence_score?: number | null
  column?: {
    id: string
    column_label: string
    column_type: string
    prompt: string
    column_config?: any
    order_index: number
  }
  progress?: {
    column_id: string
    progress: number
    total: number
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
  onCellUpdated?: (data: {
    cell_id: string
    file_id: string
    column_id: string
    cell_value: string | null
    reasoning: string | null
    source_references: any[]
    status: string
    confidence_score: number | null
  }) => void
  onColumnAdded?: (column: any) => void
  onExtractionProgress?: (progress: { column_id: string; progress: number; total: number }) => void
  onTableCreated?: (table: { id: string; name: string; description?: string; columns_count?: number; rows_count?: number }) => void
  onError?: (error: string) => void
}

export const useTabularReviewWebSocket = ({
  reviewId,
  enabled = true,
  onCellUpdated,
  onColumnAdded,
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
    const wsUrl = `${protocol}//${host}/ws/tabular-review/${reviewId}`

    try {
      const ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        console.log('Tabular Review WebSocket connected')
        setIsConnected(true)
        reconnectAttempts.current = 0
      }

      ws.onmessage = (event) => {
        try {
          const data: TabularReviewWebSocketMessage = JSON.parse(event.data)

          switch (data.type) {
            case 'connected':
              console.log('Tabular Review WebSocket connected:', data.message)
              break

            case 'cell_updated':
              if (onCellUpdated && data.cell_id && data.file_id && data.column_id) {
                onCellUpdated({
                  cell_id: data.cell_id,
                  file_id: data.file_id,
                  column_id: data.column_id,
                  cell_value: data.cell_value || null,
                  reasoning: data.reasoning || null,
                  source_references: data.source_references || [],
                  status: data.status || 'completed',
                  confidence_score: data.confidence_score || null,
                })
              }
              break

            case 'column_added':
              if (onColumnAdded && data.column) {
                onColumnAdded(data.column)
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
              console.warn('Unknown Tabular Review WebSocket message type:', data.type)
          }
        } catch (error) {
          console.error('Error parsing Tabular Review WebSocket message:', error)
          if (onError) {
            onError('Ошибка при обработке сообщения')
          }
        }
      }

      ws.onerror = (error) => {
        console.error('Tabular Review WebSocket error:', error)
        setIsConnected(false)
      }

      ws.onclose = () => {
        console.log('Tabular Review WebSocket disconnected')
        setIsConnected(false)

        // Reconnect logic
        if (reconnectAttempts.current < maxReconnectAttempts && enabled && reviewId) {
          reconnectAttempts.current++
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 10000)
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log(`Reconnecting Tabular Review WebSocket... (attempt ${reconnectAttempts.current})`)
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
  }, [reviewId, enabled, onCellUpdated, onColumnAdded, onExtractionProgress, onTableCreated, onError])

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



