import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { getApiUrl } from '@/services/api'
import { logger } from '@/lib/logger'
import { Globe, FileText } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { PlanApprovalCard } from './PlanApprovalCard'
import { AgentStepsView, AgentStep } from './AgentStepsView'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  planId?: string
  plan?: any
  agentSteps?: AgentStep[]
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
  const [webSearch, setWebSearch] = useState(false)
  const [deepThink, setDeepThink] = useState(false)
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
      const response = await fetch(getApiUrl('/api/assistant/chat'), {
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
              // Обработка плана для одобрения
              if (data.type === 'plan_ready' && data.planId && data.plan) {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? { ...msg, planId: data.planId, plan: data.plan }
                      : msg
                  )
                )
              }
              // Обработка шагов выполнения агентов
              if (data.type === 'agent_step' && data.step) {
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id === assistantMsgId) {
                      const currentSteps = msg.agentSteps || []
                      const stepIndex = currentSteps.findIndex((s) => s.step_id === data.step.step_id)
                      const updatedSteps =
                        stepIndex >= 0
                          ? currentSteps.map((s, idx) => (idx === stepIndex ? data.step : s))
                          : [...currentSteps, data.step]
                      return { ...msg, agentSteps: updatedSteps }
                    }
                    return msg
                  })
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
    <div className={`flex flex-col h-full bg-white ${className || ''}`}>
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-6 py-8 space-y-6">
        {messages.length === 0 && (
          <div className="text-center py-16">
            <p className="text-2xl font-semibold text-gray-800 mb-2">Начните диалог</p>
            <p className="text-gray-500">Задайте вопрос о документах дела</p>
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[75%] rounded-2xl px-4 py-3 ${
                message.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-800'
              }`}
            >
              {message.role === 'assistant' ? (
                <div className="text-sm leading-relaxed prose prose-sm max-w-none">
                  <ReactMarkdown
                    components={{
                      p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
                      h1: ({ children }) => <h1 className="text-xl font-bold mb-3 mt-4 first:mt-0">{children}</h1>,
                      h2: ({ children }) => <h2 className="text-lg font-semibold mb-2 mt-3 first:mt-0">{children}</h2>,
                      h3: ({ children }) => <h3 className="text-base font-semibold mb-2 mt-3 first:mt-0">{children}</h3>,
                      ul: ({ children }) => <ul className="list-disc list-inside mb-3 space-y-1">{children}</ul>,
                      ol: ({ children }) => <ol className="list-decimal list-inside mb-3 space-y-1">{children}</ol>,
                      li: ({ children }) => <li className="ml-2">{children}</li>,
                      code: ({ children, className }) => {
                        const isInline = !className
                        return isInline ? (
                          <code className="bg-gray-200 dark:bg-gray-700 px-1.5 py-0.5 rounded text-xs font-mono">
                            {children}
                          </code>
                        ) : (
                          <code className="block bg-gray-200 dark:bg-gray-700 p-3 rounded text-xs font-mono overflow-x-auto mb-3">
                            {children}
                          </code>
                        )
                      },
                      pre: ({ children }) => (
                        <pre className="bg-gray-200 dark:bg-gray-700 p-3 rounded text-xs font-mono overflow-x-auto mb-3">
                          {children}
                        </pre>
                      ),
                      strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                      em: ({ children }) => <em className="italic">{children}</em>,
                      table: ({ children }) => (
                        <div className="overflow-x-auto mb-3">
                          <table className="min-w-full border-collapse border border-gray-300">
                            {children}
                          </table>
                        </div>
                      ),
                      thead: ({ children }) => <thead className="bg-gray-200">{children}</thead>,
                      tbody: ({ children }) => <tbody>{children}</tbody>,
                      tr: ({ children }) => <tr className="border-b border-gray-200">{children}</tr>,
                      th: ({ children }) => (
                        <th className="border border-gray-300 px-3 py-2 text-left font-semibold">
                          {children}
                        </th>
                      ),
                      td: ({ children }) => (
                        <td className="border border-gray-300 px-3 py-2">{children}</td>
                      ),
                      blockquote: ({ children }) => (
                        <blockquote className="border-l-4 border-gray-400 pl-4 italic my-3">
                          {children}
                        </blockquote>
                      ),
                    }}
                  >
                    {message.content || '...'}
                  </ReactMarkdown>
                  {message.planId && message.plan && (
                    <PlanApprovalCard
                      planId={message.planId}
                      plan={message.plan}
                      onApproved={() => {
                        setMessages((prev) =>
                          prev.map((msg) =>
                            msg.id === message.id
                              ? { ...msg, planId: undefined, plan: undefined }
                              : msg
                          )
                        )
                      }}
                      onRejected={() => {
                        setMessages((prev) =>
                          prev.map((msg) =>
                            msg.id === message.id
                              ? { ...msg, planId: undefined, plan: undefined }
                              : msg
                          )
                        )
                      }}
                      onModified={(modifications) => {
                        // Отправляем изменения в чат
                        sendMessage(`Измени план: ${modifications}`)
                      }}
                    />
                  )}
                  {message.agentSteps && message.agentSteps.length > 0 && (
                    <AgentStepsView steps={message.agentSteps} isStreaming={isLoading} />
                  )}
                </div>
              ) : (
                <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
                  {message.content}
                </div>
              )}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-2xl px-4 py-3">
              <div className="flex space-x-1.5">
                <div
                  className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                  style={{ animationDelay: '0ms' }}
                />
                <div
                  className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                  style={{ animationDelay: '150ms' }}
                />
                <div
                  className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                  style={{ animationDelay: '300ms' }}
                />
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area - красивое большое поле как на скриншоте */}
      <div className="border-t border-gray-200 bg-white px-6 py-4">
        {/* Кнопки сверху */}
        <div className="flex items-center gap-3 mb-3">
          <button
            type="button"
            onClick={() => setWebSearch(!webSearch)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              webSearch
                ? 'bg-gray-900 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            <Globe size={16} />
            Web search
          </button>
          <button
            type="button"
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
          >
            <FileText size={16} />
            Prompt library
          </button>
        </div>

        {/* Большое поле ввода */}
        <form onSubmit={handleSubmit} className="relative">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Search the web"
            className="w-full px-5 py-4 pr-12 text-base border-2 border-gray-300 rounded-xl focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 transition-all disabled:bg-gray-50 disabled:cursor-not-allowed"
            disabled={isLoading || !actualCaseId}
            autoFocus
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim() || !actualCaseId}
            className="absolute right-3 top-1/2 -translate-y-1/2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm font-medium"
          >
            Отправить
          </button>
        </form>

        {/* Переключатель Deep think */}
        <div className="flex items-center gap-2 mt-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={deepThink}
              onChange={(e) => setDeepThink(e.target.checked)}
              className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
            />
            <span className="text-sm text-gray-600">Deep think</span>
          </label>
        </div>
      </div>
    </div>
  )
}

