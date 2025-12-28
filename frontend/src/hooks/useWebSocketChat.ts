import { useEffect, useRef, useState, useCallback } from 'react'

interface WebSocketMessage {
  type: 'token' | 'response' | 'error' | 'processing' | 'done'
  content?: string
  answer?: string
  sources?: any[]
  citations?: number[]
  done?: boolean
  message?: string
}

interface UseWebSocketChatOptions {
  caseId: string
  onMessage: (content: string) => void
  onSources: (sources: any[]) => void
  onError: (error: string) => void
  onComplete: () => void
  enabled?: boolean
}

export const useWebSocketChat = ({
  caseId,
  onMessage,
  onSources,
  onError,
  onComplete,
  enabled = true,
}: UseWebSocketChatOptions) => {
  const [isConnected, setIsConnected] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttempts = useRef(0)
  const maxReconnectAttempts = 5

  const connect = useCallback(() => {
    if (!enabled || !caseId) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = import.meta.env.VITE_API_URL?.replace(/^https?:\/\//, '') || window.location.host
    const wsUrl = `${protocol}//${host}/ws/chat/${caseId}`

    try {
      const ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        console.log('WebSocket connected')
        setIsConnected(true)
        reconnectAttempts.current = 0
      }

      ws.onmessage = (event) => {
        try {
          const data: WebSocketMessage = JSON.parse(event.data)
          // #region agent log
          fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'useWebSocketChat.ts:onmessage',message:'WebSocket message received',data:{type:data.type,hasAnswer:!!data.answer,hasContent:!!data.content,answerPreview:data.answer?.substring(0,100)||data.content?.substring(0,100)||'',sourcesCount:data.sources?.length||0},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'H1'})}).catch(()=>{});
          // #endregion

          switch (data.type) {
            case 'processing':
              setIsStreaming(true)
              break

            case 'token':
              if (data.content) {
                onMessage(data.content)
              }
              break

            case 'response':
              if (data.answer) {
                // #region agent log
                fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'useWebSocketChat.ts:onmessage',message:'Response answer received',data:{answerLength:data.answer.length,answerPreview:data.answer.substring(0,200),isStandardResponse:data.answer.includes('иногда генеративные языковые модели')||data.answer.includes('generative language models')},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'H1'})}).catch(()=>{});
                // #endregion
                onMessage(data.answer)
              }
              if (data.sources) {
                onSources(data.sources)
              }
              setIsStreaming(false)
              onComplete()
              break

            case 'done':
              setIsStreaming(false)
              onComplete()
              break

            case 'error':
              setIsStreaming(false)
              onError(data.message || 'Ошибка при генерации ответа')
              break

            default:
              console.warn('Unknown WebSocket message type:', data.type)
          }
        } catch (error) {
          console.error('Error parsing WebSocket message:', error)
          onError('Ошибка при обработке ответа')
        }
      }

      ws.onerror = (error) => {
        console.error('WebSocket error:', error)
        setIsConnected(false)
        setIsStreaming(false)
      }

      ws.onclose = () => {
        console.log('WebSocket disconnected')
        setIsConnected(false)
        setIsStreaming(false)

        // Reconnect logic
        if (reconnectAttempts.current < maxReconnectAttempts) {
          reconnectAttempts.current++
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 10000)
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log(`Reconnecting... (attempt ${reconnectAttempts.current})`)
            connect()
          }, delay)
        } else {
          onError('Не удалось подключиться к серверу')
        }
      }

      wsRef.current = ws
    } catch (error) {
      console.error('Error creating WebSocket:', error)
      onError('Ошибка при создании соединения')
    }
  }, [caseId, enabled, onMessage, onSources, onError, onComplete])

  const sendMessage = useCallback((query: string, history: any[] = [], proSearch: boolean = false, deepThink: boolean = false) => {
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'useWebSocketChat.ts:sendMessage',message:'Sending WebSocket message',data:{query:query.substring(0,100),historyLength:history.length,proSearch,deepThink,wsState:wsRef.current?.readyState},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'H1'})}).catch(()=>{});
    // #endregion
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setIsStreaming(true)
      wsRef.current.send(
        JSON.stringify({
          query,
          history,
          pro_search: proSearch,
          deep_think: deepThink,
        })
      )
    } else {
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'useWebSocketChat.ts:sendMessage',message:'WebSocket not connected',data:{wsState:wsRef.current?.readyState},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'H1'})}).catch(()=>{});
      // #endregion
      onError('Соединение не установлено')
    }
  }, [onError])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setIsConnected(false)
    setIsStreaming(false)
  }, [])

  useEffect(() => {
    if (enabled && caseId) {
      connect()
    }

    return () => {
      disconnect()
    }
  }, [enabled, caseId, connect, disconnect])

  return {
    isConnected,
    isStreaming,
    sendMessage,
    disconnect,
  }
}

