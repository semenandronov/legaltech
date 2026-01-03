import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { getApiUrl } from '@/services/api'
import { logger } from '@/lib/logger'
import { Conversation, ConversationContent, ConversationEmptyState } from '../ai-elements/conversation'
import { UserMessage, AssistantMessage } from '../ai-elements/message'
import { PlanApprovalCard } from './PlanApprovalCard'
import { AgentStep } from './AgentStepsView'
import { EnhancedAgentStepsView } from './EnhancedAgentStepsView'
import { TableCard } from './TableCard'
import {
  PromptInputProvider,
  PromptInput,
  PromptInputBody,
  PromptInputTextarea,
  PromptInputSubmit,
  PromptInputAttachments,
  PromptInputAttachment,
} from '../ai-elements/prompt-input'
import { Switch } from '../UI/switch'
import { Loader } from '../ai-elements/loader'

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
  tableCard?: {  // для отображения карточки таблицы (одна таблица)
    reviewId: string
    caseId: string
    tableData: {
      id: string
      name: string
      description?: string
      columns_count?: number
      rows_count?: number
      preview?: {
        columns: string[]
        rows: Array<Record<string, string>>
      }
    }
  }
  tableCards?: Array<{  // для отображения множественных таблиц
    reviewId: string
    caseId: string
    tableData: {
      id: string
      name: string
      description?: string
      columns_count?: number
      rows_count?: number
      preview?: {
        columns: string[]
        rows: Array<Record<string, string>>
      }
    }
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
  const [isLoading, setIsLoading] = useState(false)
  const [webSearch, setWebSearch] = useState(false)
  const [legalResearch, setLegalResearch] = useState(true)
  const [deepThink, setDeepThink] = useState(false)
  const abortControllerRef = useRef<AbortController | null>(null)
  

  // Update input when initialQuery changes
  useEffect(() => {
    if (initialQuery && onQuerySelected) {
      onQuerySelected()
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
          web_search: webSearch,
          legal_research: legalResearch,
          deep_think: deepThink,
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
              // Обработка создания таблицы
              if (data.type === 'table_created' && data.table_id && data.table_data) {
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id === assistantMsgId) {
                      const existingTableCards = msg.tableCards || (msg.tableCard ? [msg.tableCard] : [])
                      const newTableCard = {
                        reviewId: data.table_id,
                        caseId: data.case_id || actualCaseId,
                        tableData: data.table_data
                      }
                      // Проверяем, нет ли уже такой таблицы
                      const tableExists = existingTableCards.some(tc => tc.reviewId === data.table_id)
                      if (!tableExists) {
                        return {
                          ...msg,
                          tableCards: [...existingTableCards, newTableCard],
                          // Для обратной совместимости также устанавливаем tableCard (последняя таблица)
                          tableCard: newTableCard
                        }
                      }
                      return msg
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
  }, [actualCaseId, isLoading, messages, webSearch, legalResearch, deepThink])

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
              } else if (data.type === 'table_created' && data.table_id && data.table_data) {
                // Обработка создания таблицы из plan execution stream
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id === messageId) {
                      const existingTableCards = msg.tableCards || (msg.tableCard ? [msg.tableCard] : [])
                      const newTableCard = {
                        reviewId: data.table_id,
                        caseId: data.case_id || actualCaseId,
                        tableData: data.table_data
                      }
                      // Проверяем, нет ли уже такой таблицы
                      const tableExists = existingTableCards.some(tc => tc.reviewId === data.table_id)
                      if (!tableExists) {
                        return {
                          ...msg,
                          tableCards: [...existingTableCards, newTableCard],
                          // Для обратной совместимости также устанавливаем tableCard (последняя таблица)
                          tableCard: newTableCard
                        }
                      }
                      return msg
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

  const handlePromptSubmit = useCallback(async ({ text }: { text: string; files: any[] }) => {
    if (text.trim() && !isLoading && actualCaseId) {
      await sendMessage(text)
    }
  }, [sendMessage, isLoading, actualCaseId])

  return (
    <PromptInputProvider initialInput={initialQuery || ''}>
    <div className={`flex flex-col h-full bg-white ${className || ''}`}>
        {/* Header */}
        {messages.length === 0 && (
          <div className="flex items-center justify-center px-6 py-8">
            <h1 className="text-3xl font-semibold text-gray-900">Чем могу помочь?</h1>
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
              {/* Отображаем множественные таблицы, если есть, иначе одну */}
              {message.tableCards && message.tableCards.length > 0 ? (
                <div className="mt-4 space-y-4">
                  {message.tableCards.map((tableCard, index) => (
                    <TableCard
                      key={tableCard.reviewId || index}
                      reviewId={tableCard.reviewId}
                      caseId={tableCard.caseId}
                      tableData={tableCard.tableData}
                    />
                  ))}
                </div>
              ) : message.tableCard ? (
                <div className="mt-4">
                  <TableCard
                    reviewId={message.tableCard.reviewId}
                    caseId={message.tableCard.caseId}
                    tableData={message.tableCard.tableData}
                  />
                </div>
              ) : null}
            </AssistantMessage>
          )
        })}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-2xl px-4 py-3">
              <Loader size={20} className="text-gray-600" />
            </div>
          </div>
        )}
        </ConversationContent>
      </Conversation>

      {/* Input area - точно как на скриншоте Legora - ПО ЦЕНТРУ */}
      {messages.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center px-6 pt-16 pb-8 bg-white">
          {/* Центрированный контейнер */}
          <div className="w-full max-w-4xl mx-auto space-y-6">
            {/* PromptInput с готовыми компонентами из @ai */}
            <div className="relative">
              <PromptInput
                onSubmit={handlePromptSubmit}
                className="w-full"
              >
              <PromptInputBody>
                <div className="relative w-full">
                  <PromptInputTextarea 
                    placeholder="Введите вопрос или используйте промпт"
                    className="min-h-[60px] text-base pr-12"
                  />
                  <div className="absolute bottom-2 right-2">
                    <PromptInputSubmit 
                      variant="default"
                      className="bg-black text-white hover:bg-gray-800 rounded-lg"
                      disabled={isLoading || !actualCaseId}
                    />
                  </div>
                </div>
              </PromptInputBody>
              
              {/* Вложения под полем ввода */}
              <PromptInputAttachments>
                {(attachment) => (
                  <PromptInputAttachment data={attachment} />
                )}
              </PromptInputAttachments>
            </PromptInput>
            </div>

            {/* Три карточки функций ГОРИЗОНТАЛЬНО */}
            <div className="grid grid-cols-3 gap-4">
              {/* Web search */}
              <div className="flex flex-col p-4 bg-white border border-gray-200 rounded-lg hover:border-gray-300 transition-colors">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-gray-900">Веб-поиск</span>
                  <Switch 
                    checked={webSearch} 
                    onCheckedChange={setWebSearch}
                  />
                </div>
                <p className="text-sm text-gray-600">Используйте веб для глубокого исследования любой темы</p>
              </div>

              {/* Deep Think */}
              <div className="flex flex-col p-4 bg-white border border-gray-200 rounded-lg hover:border-gray-300 transition-colors">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-gray-900">Глубокое размышление</span>
                  <Switch 
                    checked={deepThink} 
                    onCheckedChange={setDeepThink}
                    className="data-[state=checked]:bg-blue-600"
                  />
                </div>
                <p className="text-sm text-gray-600">Используйте более глубокий анализ для сложных вопросов</p>
              </div>

              {/* Legal research */}
              <div className="flex flex-col p-4 bg-white border border-gray-200 rounded-lg hover:border-gray-300 transition-colors">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-900">Юридическое исследование</span>
                    <span className="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 rounded">Early</span>
                  </div>
                  <Switch 
                    checked={legalResearch} 
                    onCheckedChange={setLegalResearch}
                    className="data-[state=checked]:bg-blue-600"
                  />
                </div>
                <p className="text-sm text-gray-600">Найдите ответы на свои вопросы в курируемых юридических источниках</p>
              </div>
            </div>

          </div>
        </div>
      ) : (
        <div className="bg-white px-6 pt-8 pb-4">
          <div className="w-full max-w-4xl mx-auto space-y-4">
            <div className="relative">
              <PromptInput
                onSubmit={handlePromptSubmit}
                className="w-full"
              >
              <PromptInputBody>
                <div className="relative w-full">
                  <PromptInputTextarea 
                    placeholder="Введите вопрос или используйте промпт"
                    className="min-h-[60px] text-base pr-12"
                  />
                  <div className="absolute bottom-2 right-2">
                    <PromptInputSubmit 
                      variant="default"
                      className="bg-black text-white hover:bg-gray-800 rounded-lg"
                      disabled={isLoading || !actualCaseId}
                    />
                  </div>
                </div>
              </PromptInputBody>
              </PromptInput>
            </div>

            {/* Три карточки функций ГОРИЗОНТАЛЬНО - показываем и когда есть сообщения */}
            <div className="grid grid-cols-3 gap-4">
              {/* Web search */}
              <div className="flex flex-col p-4 bg-white border border-gray-200 rounded-lg hover:border-gray-300 transition-colors">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-gray-900">Веб-поиск</span>
                  <Switch 
                    checked={webSearch} 
                    onCheckedChange={setWebSearch}
                    className="data-[state=checked]:bg-blue-600"
                  />
                </div>
                <p className="text-sm text-gray-600">Используйте веб для глубокого исследования любой темы</p>
              </div>

              {/* Deep Think */}
              <div className="flex flex-col p-4 bg-white border border-gray-200 rounded-lg hover:border-gray-300 transition-colors">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-gray-900">Глубокое размышление</span>
                  <Switch 
                    checked={deepThink} 
                    onCheckedChange={setDeepThink}
                    className="data-[state=checked]:bg-blue-600"
                  />
                </div>
                <p className="text-sm text-gray-600">Используйте более глубокий анализ для сложных вопросов</p>
              </div>

              {/* Legal research */}
              <div className="flex flex-col p-4 bg-white border border-gray-200 rounded-lg hover:border-gray-300 transition-colors">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-900">Юридическое исследование</span>
                    <span className="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 rounded">Early</span>
                  </div>
                  <Switch 
                    checked={legalResearch} 
                    onCheckedChange={setLegalResearch}
                    className="data-[state=checked]:bg-blue-600"
                  />
                </div>
                <p className="text-sm text-gray-600">Найдите ответы на свои вопросы в курируемых юридических источниках</p>
              </div>
            </div>

          </div>
        </div>
      )}
      </div>
    </PromptInputProvider>
  )
}

