import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { getApiUrl } from '@/services/api'
import { logger } from '@/lib/logger'
import { Globe, FileText, Search, Database, ArrowUp, ChevronDown } from 'lucide-react'
import { Conversation, ConversationContent, ConversationEmptyState } from '../ai-elements/conversation'
import { UserMessage, AssistantMessage } from '../ai-elements/message'
import { PlanApprovalCard } from './PlanApprovalCard'
import { AgentStep } from './AgentStepsView'
import { EnhancedAgentStepsView } from './EnhancedAgentStepsView'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  planId?: string
  plan?: any
  agentSteps?: AgentStep[]
  reasoning?: string  // для прямых рассуждений
  toolCalls?: Array<{  // для прямых tool calls
    name: string
    input?: any
    output?: any
    status?: 'pending' | 'running' | 'completed' | 'error'
  }>
  response?: string  // для структурированного ответа
  sources?: Array<{  // для источников ответа
    title?: string
    url?: string
    page?: number
  }>
}

interface AssistantUIChatProps {
  caseId?: string
  className?: string
  initialQuery?: string
  onQuerySelected?: () => void
}

export const AssistantUIChat = ({ caseId, className, initialQuery, onQuerySelected }: AssistantUIChatProps) => {
  const params = useParams<{ caseId: string }>()
  const actualCaseId = caseId || params.caseId || ''
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState(initialQuery || '')
  const [isLoading, setIsLoading] = useState(false)
  const [webSearch, setWebSearch] = useState(false)
  const [databaseSearch, setDatabaseSearch] = useState(false)
  const [legalResearch, setLegalResearch] = useState(true)
  const [deepThink, setDeepThink] = useState(false)
  const abortControllerRef = useRef<AbortController | null>(null)
  
  // Prompt suggestions
  const promptSuggestions = [
    'Creating Timeline',
    'Dispute Timeline',
    'Add More Context to Thi...',
    'Anti-dilution protections',
    'Anti-Money Laundering (...',
    'Arbitration case file sum...'
  ]

  // Update input when initialQuery changes
  useEffect(() => {
    if (initialQuery) {
      setInput(initialQuery)
      if (onQuerySelected) {
        onQuerySelected()
      }
    }
  }, [initialQuery, onQuerySelected])

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

  const startPlanExecutionStream = useCallback(async (planId: string, messageId: string) => {
    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(getApiUrl(`/api/plan/${planId}/stream`), {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
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
              
              if (data.type === 'execution_started') {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === messageId
                      ? { ...msg, agentSteps: [], content: msg.content + '\n\n**Выполнение плана начато...**\n\n' }
                      : msg
                  )
                )
              } else if (data.type === 'step_completed' && data.step) {
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id === messageId) {
                      const currentSteps = msg.agentSteps || []
                      const stepIndex = currentSteps.findIndex((s) => s.step_id === data.step.step_id)
                      const updatedSteps =
                        stepIndex >= 0
                          ? currentSteps.map((s, idx) => (idx === stepIndex ? { ...data.step, status: 'completed' } : s))
                          : [...currentSteps, { ...data.step, status: 'completed' }]
                      return { ...msg, agentSteps: updatedSteps }
                    }
                    return msg
                  })
                )
              } else if (data.type === 'execution_completed') {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === messageId
                      ? { ...msg, content: msg.content + '\n\n**✅ Выполнение плана завершено**\n\n' }
                      : msg
                  )
                )
              } else if (data.type === 'execution_failed' || data.type === 'error') {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === messageId
                      ? { ...msg, content: msg.content + `\n\n**❌ Ошибка: ${data.message || 'Неизвестная ошибка'}**\n\n` }
                      : msg
                  )
                )
              }
            } catch (e) {
              logger.error('Error parsing plan execution SSE data:', e)
            }
          }
        }
      }
    } catch (error) {
      logger.error('Error streaming plan execution:', error)
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === messageId
            ? { ...msg, content: msg.content + '\n\n**❌ Ошибка при отслеживании выполнения плана**\n\n' }
            : msg
        )
      )
    }
  }, [])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (input.trim() && !isLoading) {
      sendMessage(input)
    }
  }

  return (
    <div className={`flex flex-col h-full bg-white ${className || ''}`}>
      {/* Header */}
      {messages.length === 0 && (
        <div className="px-6 py-8">
          <h1 className="text-3xl font-semibold text-gray-900 mb-8">How can I assist?</h1>
        </div>
      )}

      {/* Messages area */}
      <Conversation>
        <ConversationContent>
          {messages.length === 0 && <ConversationEmptyState title="" description="" />}

        {messages.map((message) => {
          if (message.role === 'user') {
            return (
              <UserMessage key={message.id} content={message.content} />
            )
          }

          return (
            <AssistantMessage
              key={message.id}
              content={message.content}
              reasoning={message.reasoning}
              toolCalls={message.toolCalls}
              response={message.response}
              sources={message.sources}
              isStreaming={isLoading && message.id === messages[messages.length - 1]?.id}
            >
              {message.planId && message.plan && (
                <PlanApprovalCard
                  planId={message.planId}
                  plan={message.plan}
                  onApproved={() => {
                    // Start streaming execution steps
                    if (message.planId) {
                      startPlanExecutionStream(message.planId, message.id)
                    }
                    setMessages((prev) =>
                      prev.map((msg) =>
                        msg.id === message.id
                          ? { ...msg, planId: undefined, plan: undefined, agentSteps: [] }
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
                <EnhancedAgentStepsView 
                  steps={message.agentSteps.map(step => ({
                    ...step,
                    // Конвертируем старый формат в новый, если нужно
                    tool_calls: undefined,
                    duration: undefined,
                  }))} 
                  isStreaming={isLoading}
                  showReasoning={true}
                  collapsible={true}
                />
              )}
            </AssistantMessage>
          )
        })}

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
        </ConversationContent>
      </Conversation>

      {/* Input area - точно как на скриншоте */}
      {messages.length === 0 ? (
        <div className="border-t border-gray-200 bg-white px-6 py-6">
          {/* Большое поле ввода */}
          <div className="mb-6">
            <form onSubmit={handleSubmit} className="relative">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Type a question or use a prompt"
                className="w-full px-5 py-4 pr-24 text-base border-2 border-gray-300 rounded-xl focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 transition-all disabled:bg-gray-50 disabled:cursor-not-allowed"
                disabled={isLoading || !actualCaseId}
                autoFocus
              />
              <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setDeepThink(!deepThink)}
                  className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
                    deepThink
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                  }`}
                >
                  Deep think
                </button>
                <button
                  type="submit"
                  disabled={isLoading || !input.trim() || !actualCaseId}
                  className="p-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <ArrowUp className="w-4 h-4" />
                </button>
              </div>
            </form>
          </div>

          {/* Три карточки функций */}
          <div className="space-y-3 mb-6">
            <div className="flex items-center justify-between p-4 bg-white border border-gray-200 rounded-lg hover:border-gray-300 transition-colors">
              <div className="flex items-start gap-3">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-gray-900">Legal research</span>
                    <span className="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 rounded">Early</span>
                  </div>
                  <p className="text-sm text-gray-600">Find answers to your questions in curated legal sources</p>
                </div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={legalResearch}
                  onChange={(e) => setLegalResearch(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
              </label>
            </div>

            <div className="flex items-center justify-between p-4 bg-white border border-gray-200 rounded-lg hover:border-gray-300 transition-colors">
              <div className="flex items-start gap-3">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-gray-900">Web search</span>
                  </div>
                  <p className="text-sm text-gray-600">Leverage the web to perform deep research on any topic</p>
                </div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={webSearch}
                  onChange={(e) => setWebSearch(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
              </label>
            </div>

            <div className="flex items-center justify-between p-4 bg-white border border-gray-200 rounded-lg hover:border-gray-300 transition-colors">
              <div className="flex items-start gap-3">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-gray-900">Database search</span>
                  </div>
                  <p className="text-sm text-gray-600">Search your project or organization's databases</p>
                </div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={databaseSearch}
                  onChange={(e) => setDatabaseSearch(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
              </label>
            </div>
          </div>

          {/* Кнопка Explore all prompts */}
          <button className="w-full px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors mb-4">
            Explore all prompts
          </button>

          {/* Горизонтальная полоса с предложениями промптов */}
          <div className="flex items-center gap-2 overflow-x-auto pb-2">
            {promptSuggestions.map((prompt, index) => (
              <button
                key={index}
                onClick={() => setInput(prompt)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg whitespace-nowrap transition-colors"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="border-t border-gray-200 bg-white px-6 py-4">
          <form onSubmit={handleSubmit} className="relative">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type a question or use a prompt"
              className="w-full px-5 py-4 pr-24 text-base border-2 border-gray-300 rounded-xl focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 transition-all disabled:bg-gray-50 disabled:cursor-not-allowed"
              disabled={isLoading || !actualCaseId}
            />
            <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-2">
              <button
                type="button"
                onClick={() => setDeepThink(!deepThink)}
                className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
                  deepThink
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                Deep think
              </button>
              <button
                type="submit"
                disabled={isLoading || !input.trim() || !actualCaseId}
                className="p-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <ArrowUp className="w-4 h-4" />
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}

