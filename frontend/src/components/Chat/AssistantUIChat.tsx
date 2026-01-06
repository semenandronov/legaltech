import { useState, useEffect, useRef, useCallback, forwardRef, useImperativeHandle } from 'react'
import { useParams } from 'react-router-dom'
import { getApiUrl, getDocuments, getDocumentContent } from '@/services/api'
import { logger } from '@/lib/logger'
import { loadChatHistory } from '@/services/chatHistoryService'
import { Conversation, ConversationContent } from '../ai-elements/conversation'
import { UserMessage, AssistantMessage } from '../ai-elements/message'
import { PlanApprovalCard } from './PlanApprovalCard'
import { AgentStep } from './AgentStepsView'
import { EnhancedAgentStepsView } from './EnhancedAgentStepsView'
import { TableCard } from './TableCard'
import { HumanFeedbackRequestCard } from './HumanFeedbackRequestCard'
import { WelcomeScreen } from './WelcomeScreen'
import { SettingsPanel } from './SettingsPanel'
import {
  PromptInputProvider,
  PromptInput,
  PromptInputBody,
  PromptInputTextarea,
  PromptInputSubmit,
  PromptInputAttachments,
  PromptInputAttachment,
} from '../ai-elements/prompt-input'
import { Loader } from '../ai-elements/loader'
import DocumentPreviewSheet from './DocumentPreviewSheet'
import { SourceInfo } from '@/services/api'
import { useOptionalProviderAttachments } from '../ai-elements/prompt-input'

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
    file?: string
    text_preview?: string
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
  // Фаза 9.3: Human feedback request
  feedbackRequest?: {
    requestId: string
    question: string
    options?: Array<{ id: string; label: string }> | string[]
    requiresApproval?: boolean
    context?: any
    agentName?: string
    inputSchema?: any // JSON Schema for structured input
  }
}

interface AssistantUIChatProps {
  caseId?: string
  className?: string
  initialQuery?: string
  onQuerySelected?: () => void
  caseTitle?: string
  documentCount?: number
  isLoadingCaseInfo?: boolean
  onDocumentDrop?: (documentFilename: string) => void
}

// Компонент-обертка для PromptInput с поддержкой drag&drop
interface PromptInputWithDropProps {
  actualCaseId: string
  onDocumentDrop?: (documentFilename: string) => void
  handlePromptSubmit: (message: { text: string; files: any[] }, event: React.FormEvent<HTMLFormElement>) => void | Promise<void>
  isLoading: boolean
}

const PromptInputWithDrop = ({ actualCaseId, onDocumentDrop, handlePromptSubmit, isLoading }: PromptInputWithDropProps) => {
  const attachments = useOptionalProviderAttachments()
  const containerRef = useRef<HTMLDivElement | null>(null)
  
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    
    const form = container.querySelector('form')
    if (!form) return
    
    const handleDragOver = (e: DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
    }
    
    const handleDrop = async (e: DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      
      // Проверяем, есть ли файлы в dataTransfer
      if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
        // Если есть файлы, добавляем их через attachments API
        if (attachments) {
          attachments.add(e.dataTransfer.files)
          logger.info(`Добавлено ${e.dataTransfer.files.length} файлов через drag&drop`)
        }
      } else {
        // Если это drag из панели документов (только имя файла)
        const documentFilename = e.dataTransfer?.getData('text/plain')
        logger.info(`Drag&drop документа: "${documentFilename}", attachments доступен: ${!!attachments}, caseId: ${actualCaseId}`)
        
        if (documentFilename && actualCaseId && attachments) {
          try {
            // Получаем список документов
            const documentsData = await getDocuments(actualCaseId)
            const document = documentsData.documents?.find(
              (doc: any) => doc.filename === documentFilename
            )
            
            if (document && document.id) {
              logger.info(`Найден документ: ${document.id}, загружаю файл...`)
              // Загружаем файл с сервера
              const blob = await getDocumentContent(actualCaseId, document.id)
              logger.info(`Файл загружен, размер: ${blob.size} байт, тип: ${blob.type}`)
              
              // Создаем File объект из Blob
              const file = new File(
                [blob],
                document.filename || documentFilename,
                { type: blob.type || 'application/octet-stream' }
              )
              
              // Добавляем файл в attachments
              attachments.add([file])
              logger.info(`Файл "${file.name}" добавлен в attachments`)
              
              if (onDocumentDrop) {
                onDocumentDrop(documentFilename)
              }
            } else {
              logger.warn(`Документ "${documentFilename}" не найден в списке документов`)
              if (onDocumentDrop) {
                onDocumentDrop(documentFilename)
              }
            }
          } catch (error) {
            logger.error('Ошибка при загрузке документа:', error)
            if (onDocumentDrop) {
              onDocumentDrop(documentFilename)
            }
          }
        } else if (documentFilename && onDocumentDrop) {
          logger.warn(`Не удалось добавить документ: attachments=${!!attachments}, caseId=${actualCaseId}`)
          onDocumentDrop(documentFilename)
        }
      }
    }
    
    form.addEventListener('dragover', handleDragOver)
    form.addEventListener('drop', handleDrop)
    
    return () => {
      form.removeEventListener('dragover', handleDragOver)
      form.removeEventListener('drop', handleDrop)
    }
  }, [attachments, actualCaseId, onDocumentDrop])
  
  return (
    <div ref={containerRef} className="w-full">
      <PromptInput
        onSubmit={(message, event) => handlePromptSubmit(message, event)}
        className="w-full [&_form_input-group]:border [&_form_input-group]:border-border [&_form_input-group]:rounded-lg [&_form_input-group]:bg-bg-elevated [&_form_input-group]:focus-within:border-border-strong [&_form_input-group]:transition-all [&_form_input-group]:hover:border-border-strong"
        style={{
          '--input-border': 'var(--color-border)',
          '--input-bg': 'var(--color-bg-elevated)',
          '--input-focus-border': 'var(--color-border-strong)',
        } as React.CSSProperties}
      >
        <PromptInputBody>
          <div className="flex items-end gap-2 w-full">
            <div className="flex-1 relative">
              <PromptInputTextarea 
                placeholder="Введите вопрос или используйте промпт..."
                className="w-full min-h-[120px] max-h-[300px] text-base py-4 px-4 resize-none focus:outline-none leading-relaxed overflow-y-auto"
                style={{
                  color: 'var(--color-text-primary)',
                  backgroundColor: 'transparent',
                  padding: 'var(--space-4)',
                }}
              />
            </div>
            <div className="flex-shrink-0 pb-3">
              <PromptInputSubmit 
                variant="default"
                className="rounded-md h-10 w-10 p-0 flex items-center justify-center shrink-0 transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
                style={{
                  backgroundColor: 'var(--color-accent)',
                  color: 'var(--color-bg-primary)',
                }}
                disabled={isLoading || !actualCaseId}
                status={isLoading ? "submitted" : undefined}
                aria-label="Отправить сообщение"
              />
            </div>
          </div>
        </PromptInputBody>
        
        {/* Вложения под полем ввода - внутри формы, но не влияют на layout SettingsPanel */}
        <div style={{ padding: '0 var(--space-4) var(--space-2)', minHeight: 0 }}>
          <PromptInputAttachments>
            {(attachment) => (
              <PromptInputAttachment data={attachment} />
            )}
          </PromptInputAttachments>
        </div>
      </PromptInput>
    </div>
  )
}

export const AssistantUIChat = forwardRef<{ clearMessages: () => void; loadHistory: () => Promise<void> }, AssistantUIChatProps>(({ 
  caseId, 
  className, 
  initialQuery, 
  onQuerySelected,
  caseTitle,
  documentCount,
  isLoadingCaseInfo = false,
  onDocumentDrop
}, ref) => {
  const params = useParams<{ caseId: string }>()
  const actualCaseId = caseId || params.caseId || ''
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingHistory, setIsLoadingHistory] = useState(true)
  const [webSearch, setWebSearch] = useState(false)
  const [legalResearch, setLegalResearch] = useState(true)
  const [deepThink, setDeepThink] = useState(false)
  const abortControllerRef = useRef<AbortController | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewSource, setPreviewSource] = useState<SourceInfo | null>(null)
  const [allCurrentSources, setAllCurrentSources] = useState<SourceInfo[]>([])

  // Load chat history on mount
  useEffect(() => {
    if (!actualCaseId) {
      setIsLoadingHistory(false)
      return
    }

    const loadHistory = async () => {
      setIsLoadingHistory(true)
      try {
        const historyMessages = await loadChatHistory(actualCaseId)
        
        // Convert HistoryMessage to Message format
        const convertedMessages: Message[] = historyMessages.map((msg, index) => {
          // Обрабатываем источники - они могут быть в разных форматах
          let sources: Array<{ title?: string; url?: string; page?: number; file?: string }> = []
          
          if (msg.sources && Array.isArray(msg.sources)) {
            sources = msg.sources.map((source: any) => {
              // Если источник - строка (старый формат)
              if (typeof source === 'string') {
                return { title: source, file: source }
              }
              // Если источник - объект
              return {
                title: source.title || source.file || 'Источник',
                url: source.url,
                page: source.page,
                file: source.file,
              }
            })
          }
          
          return {
            id: `msg-${msg.created_at || Date.now()}-${index}`,
            role: msg.role,
            content: msg.content || '',
            sources: sources.length > 0 ? sources : undefined,
          }
        })
        
        setMessages(convertedMessages)
      } catch (error) {
        logger.error('Error loading chat history:', error)
        // Continue with empty messages
      } finally {
        setIsLoadingHistory(false)
      }
    }

    loadHistory()
  }, [actualCaseId])

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
              // Обработка источников из SSE
              if (data.type === 'sources' && data.sources) {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? {
                          ...msg,
                          sources: data.sources.map((source: any) => ({
                            title: source.title || source.file,
                            url: source.url,
                            page: source.page,
                          })),
                        }
                      : msg
                  )
                )
              }
              // Фаза 9.3: Обработка human feedback request events
              if (data.type === 'human_feedback_request' || data.type === 'humanFeedbackRequest' || data.event === 'humanFeedbackRequest') {
                const feedbackData = {
                  requestId: data.request_id || data.requestId,
                  question: data.question || data.message,
                  options: data.options || [],
                  requiresApproval: data.requires_approval || data.requiresApproval || false,
                  context: data.context || {},
                  agentName: data.agent_name || data.agentName,
                  inputSchema: data.input_schema || data.inputSchema
                }
                
                // Сохраняем feedback request в сообщении
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? { ...msg, feedbackRequest: feedbackData }
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

  const handlePromptSubmit = useCallback(async (message: { text: string; files: any[] }, _event: React.FormEvent<HTMLFormElement>) => {
    const { text } = message
    if (text.trim() && !isLoading && actualCaseId) {
      await sendMessage(text)
    }
  }, [sendMessage, isLoading, actualCaseId])

  // Expose sendMessage for WelcomeScreen
  const handleQuickAction = useCallback((prompt: string) => {
    if (prompt.trim() && !isLoading && actualCaseId) {
      sendMessage(prompt)
    }
  }, [sendMessage, isLoading, actualCaseId])

  // Expose clearMessages and loadHistory for parent component
  useImperativeHandle(ref, () => ({
    clearMessages: () => {
      setMessages([])
    },
    loadHistory: async () => {
      if (!actualCaseId) return
      setIsLoadingHistory(true)
      try {
        const historyMessages = await loadChatHistory(actualCaseId)
        const convertedMessages: Message[] = historyMessages.map((msg, index) => {
          let sources: Array<{ title?: string; url?: string; page?: number; file?: string }> = []
          if (msg.sources && Array.isArray(msg.sources)) {
            sources = msg.sources.map((source: any) => {
              if (typeof source === 'string') {
                return { title: source, file: source }
              }
              return {
                title: source.title || source.file || 'Источник',
                url: source.url,
                page: source.page,
                file: source.file,
              }
            })
          }
          return {
            id: `msg-${msg.created_at || Date.now()}-${index}`,
            role: msg.role,
            content: msg.content || '',
            sources: sources.length > 0 ? sources : undefined,
          }
        })
        setMessages(convertedMessages)
      } catch (error) {
        logger.error('Error loading chat history:', error)
      } finally {
        setIsLoadingHistory(false)
      }
    },
  }))

  return (
    <PromptInputProvider initialInput={initialQuery || ''}>
    <div 
      className={`flex flex-col h-full ${className || ''}`}
      style={{ backgroundColor: 'var(--color-bg-primary)' }}
    >
      {/* Messages area */}
      <div className="flex-1 min-h-0 flex flex-col">
        <Conversation className="flex-1 min-h-0 flex flex-col">
          <ConversationContent className="flex-1 overflow-y-auto">
              {isLoadingHistory ? (
                <div className="flex items-center justify-center py-8">
                  <Loader size={24} style={{ color: 'var(--color-text-muted)' }} />
                  <span 
                    className="ml-3 text-sm"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    Загрузка истории...
                  </span>
                </div>
              ) : messages.length === 0 && !isLoadingHistory ? (
                <div className="h-full flex items-start justify-center pt-8 pb-4 overflow-y-auto">
                  <WelcomeScreen
                    onQuickAction={handleQuickAction}
                    caseTitle={caseTitle}
                    documentCount={documentCount}
                    isLoading={isLoadingCaseInfo}
                  />
                </div>
              ) : null}

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
              onSourceClick={(source) => {
                if (source.file) {
                  // Открываем документ справа в панели предпросмотра
                  const sourceInfo: SourceInfo = {
                    file: source.file || source.title || '',
                    page: source.page,
                    text_preview: (source as any).text_preview,
                  }
                  setPreviewSource(sourceInfo)
                  setPreviewOpen(true)
                  // Собираем все источники из текущего сообщения для навигации
                  if (message.sources) {
                    setAllCurrentSources(message.sources.map(s => ({
                      file: s.file || s.title || '',
                      page: s.page,
                      text_preview: s.text_preview,
                    })))
                  }
                }
              }}
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
              {/* Фаза 9.3: Human feedback request card */}
              {message.feedbackRequest && (
                <HumanFeedbackRequestCard
                  requestId={message.feedbackRequest.requestId}
                  message={message.feedbackRequest.question}
                  options={message.feedbackRequest.options?.map((opt: any) => 
                    typeof opt === 'string' ? { id: opt, label: opt } : opt
                  )}
                  agentName={message.feedbackRequest.agentName}
                  onResponse={async (response: string) => {
                    try {
                      const token = localStorage.getItem('access_token')
                      const response_data = await fetch(getApiUrl('/api/assistant/chat/human-feedback'), {
                        method: 'POST',
                        headers: {
                          'Content-Type': 'application/json',
                          'Authorization': `Bearer ${token}`,
                        },
                        body: JSON.stringify({
                          request_id: message.feedbackRequest?.requestId,
                          response: response,
                          case_id: actualCaseId,
                        }),
                      })

                      if (!response_data.ok) {
                        const errorData = await response_data.json().catch(() => ({}))
                        throw new Error(errorData.detail || 'Ошибка при отправке ответа')
                      }

                      const result = await response_data.json()
                      logger.info('Human feedback response submitted:', result)

                      // Clear feedback request from message
                      setMessages((prev) =>
                        prev.map((msg) =>
                          msg.id === message.id
                            ? {
                                ...msg,
                                feedbackRequest: undefined,
                                content: msg.content + `\n\n**Ваш ответ:** ${response}\n\n`,
                              }
                            : msg
                        )
                      )
                    } catch (error) {
                      logger.error('Error submitting human feedback response:', error)
                      throw error // Re-throw to let HumanFeedbackRequestCard handle it
                    }
                  }}
                />
              )}
            </AssistantMessage>
          )
        })}

            {isLoading && (
              <div className="flex justify-start">
                <div 
                  className="rounded-lg px-4 py-3 border border-border"
                  style={{ 
                    backgroundColor: 'var(--color-bg-secondary)',
                    borderColor: 'var(--color-border)'
                  }}
                >
                  <Loader size={20} style={{ color: 'var(--color-text-secondary)' }} />
                </div>
              </div>
            )}
          </ConversationContent>
        </Conversation>
      </div>

      {/* Input area - когда нет сообщений, поле ввода внизу, Welcome Screen выше */}
      {messages.length === 0 ? (
        <div 
          className="flex-shrink-0 border-t"
          style={{ 
            backgroundColor: 'var(--color-bg-primary)',
            borderTopColor: 'var(--color-border)'
          }}
        >
          <div 
            className="w-full max-w-4xl mx-auto space-y-4"
            style={{ padding: 'var(--space-4) var(--space-6)' }}
          >
            {/* PromptInput с готовыми компонентами из @ai */}
            <PromptInputProvider>
              <PromptInputWithDrop
                actualCaseId={actualCaseId}
                onDocumentDrop={onDocumentDrop}
                handlePromptSubmit={handlePromptSubmit}
                isLoading={isLoading}
              />
            </PromptInputProvider>

            {/* Компактная панель настроек */}
            <SettingsPanel
              webSearch={webSearch}
              deepThink={deepThink}
              legalResearch={legalResearch}
              onWebSearchChange={setWebSearch}
              onDeepThinkChange={setDeepThink}
              onLegalResearchChange={setLegalResearch}
            />

          </div>
        </div>
      ) : (
        <div 
          style={{ 
            backgroundColor: 'var(--color-bg-primary)',
            padding: 'var(--space-8) var(--space-6) var(--space-4)'
          }}
        >
          <div 
            className="w-full max-w-4xl mx-auto"
            style={{ 
              display: 'flex', 
              flexDirection: 'column', 
              gap: 'var(--space-4)' 
            }}
          >
            <PromptInputProvider>
              <PromptInputWithDrop
                actualCaseId={actualCaseId}
                onDocumentDrop={onDocumentDrop}
                handlePromptSubmit={handlePromptSubmit}
                isLoading={isLoading}
              />
            </PromptInputProvider>

            {/* Компактная панель настроек - всегда под полем ввода */}
            <SettingsPanel
              webSearch={webSearch}
              deepThink={deepThink}
              legalResearch={legalResearch}
              onWebSearchChange={setWebSearch}
              onDeepThinkChange={setDeepThink}
              onLegalResearchChange={setLegalResearch}
            />

          </div>
        </div>
      )}
      </div>

      {/* Document Preview Sheet */}
      <DocumentPreviewSheet
        isOpen={previewOpen}
        onClose={() => setPreviewOpen(false)}
        source={previewSource}
        caseId={actualCaseId}
        allSources={allCurrentSources}
        onNavigate={(source: SourceInfo) => setPreviewSource(source)}
      />
    </PromptInputProvider>
  )
})

