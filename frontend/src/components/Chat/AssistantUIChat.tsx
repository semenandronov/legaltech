import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { getApiUrl } from '@/services/api'
import { logger } from '@/lib/logger'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
}

interface AssistantUIChatProps {
  caseId?: string
  className?: string
}

export const AssistantUIChat = ({ caseId, className }: AssistantUIChatProps) => {
  const params = useParams<{ caseId: string }>()
  const actualCaseId = caseId || params.caseId || ''
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const abortControllerRef = useRef<AbortController | null>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = useCallback(async (userMessage: string) => {
    if (!userMessage.trim() || !actualCaseId || isLoading) return

    // Add user message
    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: userMessage,
    }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setIsLoading(true)

    // Create assistant message placeholder
    const assistantMsgId = `assistant-${Date.now()}`
    const assistantMsg: Message = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
    }
    setMessages((prev) => [...prev, assistantMsg])

    // Cancel previous request if exists
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    abortControllerRef.current = new AbortController()

    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(getApiUrl('/api/chat'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          case_id: actualCaseId,
          messages: [...messages, userMsg].map((m) => ({
            role: m.role,
            content: m.content,
          })),
        }),
        signal: abortControllerRef.current.signal,
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      if (!reader) {
        throw new Error('No response body')
      }

      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              if (data.textDelta !== undefined) {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? { ...msg, content: msg.content + data.textDelta }
                      : msg
                  )
                )
              }
              if (data.error) {
                throw new Error(data.error)
              }
            } catch (e) {
              logger.error('Error parsing SSE data:', e)
            }
          }
        }
      }
    } catch (error: unknown) {
      if (error instanceof Error && error.name === 'AbortError') {
        logger.info('Request aborted')
        return
      }
      logger.error('Assistant UI chat error:', error)
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMsgId
            ? { ...msg, content: msg.content || 'Ошибка при получении ответа' }
            : msg
        )
      )
    } finally {
      setIsLoading(false)
      abortControllerRef.current = null
    }
  }, [actualCaseId, isLoading, messages])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (input.trim() && !isLoading) {
      sendMessage(input)
    }
  }

  return (
    <div className={`flex flex-col h-full ${className || ''}`}>
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-muted-foreground py-8">
            <p className="text-lg font-semibold mb-2">Начните диалог</p>
            <p className="text-sm">Задайте вопрос о документах дела</p>
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] rounded-lg p-3 ${
                message.role === 'user'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted'
              }`}
            >
              <div className="whitespace-pre-wrap break-words">
                {message.content || (message.role === 'assistant' ? '...' : '')}
              </div>
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-muted rounded-lg p-3">
              <div className="flex space-x-1">
                <div
                  className="w-2 h-2 bg-current rounded-full animate-bounce"
                  style={{ animationDelay: '0ms' }}
                />
                <div
                  className="w-2 h-2 bg-current rounded-full animate-bounce"
                  style={{ animationDelay: '150ms' }}
                />
                <div
                  className="w-2 h-2 bg-current rounded-full animate-bounce"
                  style={{ animationDelay: '300ms' }}
                />
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="border-t p-4">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Задайте вопрос о документах..."
            className="flex-1 px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
            disabled={isLoading || !actualCaseId}
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim() || !actualCaseId}
            className="px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Отправить
          </button>
        </form>
      </div>
    </div>
  )
}

