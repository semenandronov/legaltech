import { useState, useEffect, useRef, useCallback, forwardRef, useImperativeHandle } from 'react'
import { useParams } from 'react-router-dom'
import { getApiUrl, getDocuments, getDocumentContent } from '@/services/api'
import { logger } from '@/lib/logger'
import { loadChatHistory } from '@/services/chatHistoryService'
import { uploadTemplateFile } from '@/services/documentEditorApi'
import { Conversation, ConversationContent } from '../ai-elements/conversation'
import { UserMessage, AssistantMessage } from '../ai-elements/message'
import { PlanApprovalCard } from './PlanApprovalCard'
import { AgentStep } from './AgentStepsView'
import { EnhancedAgentStepsView } from './EnhancedAgentStepsView'
import { TableCard } from './TableCard'
import { HumanFeedbackRequestCard } from './HumanFeedbackRequestCard'
import { TableClarificationModal } from './TableClarificationModal'
import { DocumentCard } from './DocumentCard'
import { WelcomeScreen } from './WelcomeScreen'
import { SettingsPanel } from './SettingsPanel'
import {
  PromptInputProvider,
  PromptInput,
  PromptInputBody,
  PromptInputTextarea,
  PromptInputSubmit,
} from '../ai-elements/prompt-input'
import { Loader } from '../ai-elements/loader'
import DocumentPreviewSheet from './DocumentPreviewSheet'
import { SourceInfo } from '@/services/api'
import { useOptionalProviderAttachments, useOptionalPromptInputController } from '../ai-elements/prompt-input'
import { Plus, Check, FileText, X } from 'lucide-react'
import type { ExtendedFileUIPart } from '../ai-elements/prompt-input'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  attachments?: ExtendedFileUIPart[]  // Файлы, прикрепленные к сообщению
  planId?: string
  plan?: any
  agentSteps?: AgentStep[]
  reasoning?: string  // для прямых рассуждений
  reasoningSteps?: Array<{  // для структурированных reasoning steps
    phase: string
    step: number
    totalSteps: number
    content: string
  }>
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
    interruptType?: string // 'table_clarification' или другой тип
    threadId?: string // Thread ID для resume
    payload?: any // Дополнительные данные interrupt
    isTableClarification?: boolean // Флаг для table_clarification
    availableDocTypes?: string[] // Доступные типы документов
    questions?: string[] // Список вопросов для table_clarification
  }
  // Режим Draft: карточка созданного документа
  documentCard?: {
    documentId: string
    title: string
    preview?: string
    caseId: string
  }
  // Редактирование документа
  editedContent?: string  // Для применения правок к документу
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
  // Режим редактора документов
  documentEditorMode?: boolean
  currentDocumentId?: string
  currentDocumentContent?: string  // Для передачи контекста документа
  selectedText?: string
  // Callbacks для редактора
  onApplyEdit?: (editedContent: string) => void
  onInsertText?: (text: string) => void
  onReplaceText?: (text: string) => void
  onOpenDocumentInEditor?: (documentId: string) => void
}

// Компонент-обертка для PromptInput с поддержкой drag&drop
interface PromptInputWithDropProps {
  actualCaseId: string
  onDocumentDrop?: (documentFilename: string) => void
  handlePromptSubmit: (message: { text: string; files: any[] }, event: React.FormEvent<HTMLFormElement>) => void | Promise<void>
  isLoading: boolean
}

// Компонент для отображения файла как чипа (chip)
const FileChip = ({ 
  attachment, 
  onRemove 
}: { 
  attachment: ExtendedFileUIPart; 
  onRemove: () => void;
}) => {
  const filename = attachment.filename || "Файл";
  const fileSize = attachment.file?.size || 0;
  const sizeInKB = (fileSize / 1024).toFixed(1);
  const displayFilename = filename.length > 35 ? filename.substring(0, 35) + '...' : filename;

  return (
    <div 
      className="flex items-center gap-3 px-4 py-2.5 rounded-lg border border-gray-200/50 bg-white/80 backdrop-blur-sm shadow-sm hover:shadow-md transition-all"
      style={{
        background: 'linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(249, 250, 251, 0.9) 100%)',
        boxShadow: '0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06)',
      }}
    >
      <div className="flex-shrink-0">
        <FileText className="w-5 h-5 text-gray-600" strokeWidth={1.5} />
      </div>
      <div className="flex-1 min-w-0 flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-gray-900 truncate">
          {displayFilename}
        </span>
        <span className="text-xs text-gray-500 whitespace-nowrap flex-shrink-0">
          {sizeInKB} KB
        </span>
      </div>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        className="flex-shrink-0 p-1 rounded-md hover:bg-gray-200/60 transition-colors"
        aria-label="Удалить файл"
      >
        <X className="w-4 h-4 text-gray-500" />
      </button>
    </div>
  );
};

const PromptInputWithDrop = ({ actualCaseId, onDocumentDrop, handlePromptSubmit, isLoading }: PromptInputWithDropProps) => {
  const attachments = useOptionalProviderAttachments()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [isDraggingOver, setIsDraggingOver] = useState(false)
  const dragCounterRef = useRef(0)
  
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    
    const form = container.querySelector('form')
    if (!form) return
    
    const handleDragEnter = (e: DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      dragCounterRef.current++
      
      // Проверяем, что это drag документа (не обычного файла)
      const hasFiles = e.dataTransfer?.types?.includes('Files')
      const hasText = e.dataTransfer?.types?.includes('text/plain')
      
      if (hasText || (hasFiles && !e.dataTransfer?.files || e.dataTransfer?.files.length === 0)) {
        setIsDraggingOver(true)
      }
    }
    
    const handleDragLeave = (e: DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      dragCounterRef.current--
      
      if (dragCounterRef.current === 0) {
        setIsDraggingOver(false)
      }
    }
    
    const handleDragOver = (e: DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
    }
    
    const handleDrop = async (e: DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      // СБРАСЫВАЕМ СРАЗУ при drop - это важно!
      setIsDraggingOver(false)
      dragCounterRef.current = 0
      
      // Проверяем, есть ли файлы в dataTransfer
      if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
        // Если есть файлы, добавляем их через attachments API
        if (attachments) {
          attachments.add(e.dataTransfer.files)
          logger.info(`Добавлено ${e.dataTransfer.files.length} файлов через drag&drop`)
          // Убеждаемся что индикатор выключен после добавления
          setIsDraggingOver(false)
          dragCounterRef.current = 0
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
              
              // Добавляем файл в attachments с сохранением sourceFileId
              attachments.add([file], [{ sourceFileId: document.id }])
              logger.info(`Файл "${file.name}" добавлен в attachments с sourceFileId: ${document.id}`)
              
              // Убеждаемся что индикатор выключен после добавления
              setIsDraggingOver(false)
              dragCounterRef.current = 0
              
              // Не вызываем onDocumentDrop, так как файл уже виден в attachments
            } else {
              logger.warn(`Документ "${documentFilename}" не найден в списке документов`)
              // Даже если файл не найден, сбрасываем индикатор
              setIsDraggingOver(false)
              dragCounterRef.current = 0
            }
          } catch (error) {
            logger.error('Ошибка при загрузке документа:', error)
            // При ошибке тоже сбрасываем индикатор
            setIsDraggingOver(false)
            dragCounterRef.current = 0
          }
        } else {
          // Если не удалось обработать, все равно сбрасываем индикатор
          setIsDraggingOver(false)
          dragCounterRef.current = 0
        }
      }
    }
    
    form.addEventListener('dragenter', handleDragEnter)
    form.addEventListener('dragleave', handleDragLeave)
    form.addEventListener('dragover', handleDragOver)
    form.addEventListener('drop', handleDrop)
    
    return () => {
      form.removeEventListener('dragenter', handleDragEnter)
      form.removeEventListener('dragleave', handleDragLeave)
      form.removeEventListener('dragover', handleDragOver)
      form.removeEventListener('drop', handleDrop)
    }
  }, [attachments, actualCaseId, onDocumentDrop])
  
  return (
    <div ref={containerRef} className="w-full relative">
      {/* Файлы (чипы) НАД полем ввода - ВНЕ PromptInput, но внутри контейнера */}
      {attachments && attachments.files.length > 0 && (
        <div className="px-4 pt-3 pb-2 space-y-2 mb-2">
          {attachments.files.map((attachment) => (
            <FileChip
              key={attachment.id}
              attachment={attachment}
              onRemove={() => attachments.remove(attachment.id)}
            />
          ))}
        </div>
      )}
      
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
          </div>
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
        </PromptInputBody>
      </PromptInput>
      
      {/* Индикатор drag-and-drop */}
      {isDraggingOver && (
        <div
          className="absolute inset-0 flex items-center justify-center pointer-events-none z-50 rounded-lg"
          style={{
            backgroundColor: 'rgba(34, 197, 94, 0.1)',
            border: '2px dashed rgba(34, 197, 94, 0.5)',
          }}
        >
          <div className="flex flex-col items-center justify-center gap-3">
            <div
              className="flex items-center justify-center w-16 h-16 rounded-full"
              style={{
                backgroundColor: 'rgba(34, 197, 94, 0.2)',
              }}
            >
              <Plus className="w-8 h-8" style={{ color: 'rgb(34, 197, 94)' }} strokeWidth={3} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export const AssistantUIChat = forwardRef<{ clearMessages: () => void; loadHistory: (sessionId?: string) => Promise<void> }, AssistantUIChatProps>(({ 
  caseId, 
  className, 
  initialQuery, 
  onQuerySelected,
  caseTitle,
  documentCount,
  isLoadingCaseInfo = false,
  onDocumentDrop,
  documentEditorMode = false,
  currentDocumentId,
  currentDocumentContent,
  selectedText,
  onApplyEdit,
  onOpenDocumentInEditor
}, ref) => {
  const params = useParams<{ caseId: string }>()
  const actualCaseId = caseId || params.caseId || ''
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingHistory, setIsLoadingHistory] = useState(true)
  // Веб-поиск отключен - всегда передаем false в SettingsPanel
  const [legalResearch, setLegalResearch] = useState(false)
  const [deepThink, setDeepThink] = useState(false)
  const [draftMode, setDraftMode] = useState(false)
  const abortControllerRef = useRef<AbortController | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewSource, setPreviewSource] = useState<SourceInfo | null>(null)
  const [allCurrentSources, setAllCurrentSources] = useState<SourceInfo[]>([])
  
  // Получаем attachments для извлечения template_file_id
  const attachments = useOptionalProviderAttachments()

  // Load chat history on mount
  useEffect(() => {
    // НЕ загружаем историю автоматически в режиме редактора
    if (documentEditorMode) {
      setIsLoadingHistory(false)
      setMessages([])
      return
    }

    if (!actualCaseId) {
      setIsLoadingHistory(false)
      return
    }

    // НЕ загружаем историю автоматически - показываем пустой чат
    // История будет загружаться только при выборе сессии из панели истории
    setIsLoadingHistory(false)
    setMessages([])
  }, [actualCaseId, documentEditorMode])

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

    // Сохраняем файлы из attachments перед очисткой
    const currentAttachments = attachments?.files ? [...attachments.files] : []

    // Add user message с файлами
    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: userMessage,
      attachments: currentAttachments.length > 0 ? currentAttachments : undefined,
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
      const requestBody: any = {
        case_id: actualCaseId,
        messages: [...messages, userMsg].map((m) => ({
          role: m.role,
          content: m.content,
        })),
        web_search: false, // Веб-поиск отключен
        legal_research: legalResearch,
        deep_think: deepThink,
        draft_mode: draftMode,
      }

      // Обработка файлов-шаблонов в draft mode
      if (draftMode) {
        logger.info(`[Draft Mode] Checking attachments: draftMode=${draftMode}, attachments=${!!attachments}, filesCount=${attachments?.files?.length || 0}`)
        if (attachments && attachments.files && attachments.files.length > 0) {
          logger.info(`[Draft Mode] Files found: ${attachments.files.map(f => ({ name: f.filename, hasFile: !!f.file, hasSourceFileId: !!f.sourceFileId }))}`)
          // Ищем файл с sourceFileId (из БД)
          const templateFileFromDb = attachments.files.find(f => f.sourceFileId)
          if (templateFileFromDb?.sourceFileId) {
            // Файл из БД - используем template_file_id
            requestBody.template_file_id = templateFileFromDb.sourceFileId
            logger.info(`[Draft Mode] Using file from DB: ${templateFileFromDb.sourceFileId}`)
          } else {
            // Локальный файл - загружаем и конвертируем
            const localFile = attachments.files.find(f => f.file && !f.sourceFileId)
            if (localFile?.file) {
              try {
                logger.info(`[Draft Mode] Uploading local template file: ${localFile.file.name}`)
                const templateResponse = await uploadTemplateFile(localFile.file)
                requestBody.template_file_content = templateResponse.content
                logger.info(`[Draft Mode] Template file converted to HTML (${templateResponse.content.length} chars)`)
              } catch (error: any) {
                logger.error(`[Draft Mode] Error uploading template file: ${error}`)
                throw new Error(`Ошибка при загрузке файла-шаблона: ${error.message || error}`)
              }
            } else {
              logger.warn(`[Draft Mode] No local file found in attachments`)
            }
          }
        } else {
          logger.warn(`[Draft Mode] No attachments or files found`)
        }
      }

      // Добавляем контекст документа редактора если в режиме редактора
      if (documentEditorMode) {
        if (currentDocumentContent) {
          requestBody.document_context = currentDocumentContent
        }
        if (currentDocumentId) {
          requestBody.document_id = currentDocumentId
        }
        if (selectedText) {
          requestBody.selected_text = selectedText
        }
      }

      // Обработка прикрепленных файлов для обычных сообщений (не draft_mode)
      if (!draftMode && attachments && attachments.files && attachments.files.length > 0) {
        logger.info(`[Chat] Checking attachments: filesCount=${attachments.files.length}`)
        
        // Собираем ID файлов из базы данных
        const fileIdsFromDb = attachments.files
          .filter(f => f.sourceFileId)
          .map(f => f.sourceFileId)
          .filter((id): id is string => !!id)
        
        if (fileIdsFromDb.length > 0) {
          requestBody.attached_file_ids = fileIdsFromDb
          logger.info(`[Chat] Attached file IDs: ${fileIdsFromDb.join(', ')}`)
        }
        
        // Для новых локальных файлов нужно их загрузить в дело
        // Пока что просто логируем - в будущем можно добавить автоматическую загрузку
        const localFiles = attachments.files.filter(f => f.file && !f.sourceFileId)
        if (localFiles.length > 0) {
          logger.warn(`[Chat] Local files detected but not uploaded yet: ${localFiles.map(f => f.filename).join(', ')}`)
          // TODO: Автоматически загружать локальные файлы в дело перед отправкой сообщения
        }
      }

      const response = await fetch(getApiUrl('/api/assistant/chat'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify(requestBody),
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
              // Обработка reasoning events
              if (data.type === 'reasoning' && data.phase && data.content) {
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id === assistantMsgId) {
                      const currentSteps = msg.reasoningSteps || []
                      const newStep = {
                        phase: data.phase,
                        step: data.step || data.stepNumber || currentSteps.length + 1,
                        totalSteps: data.totalSteps || data.totalStepsNumber || 4,
                        content: data.content
                      }
                      // Проверяем, нет ли уже такого шага (по phase и step)
                      const stepIndex = currentSteps.findIndex(
                        (s) => s.phase === newStep.phase && s.step === newStep.step
                      )
                      const updatedSteps =
                        stepIndex >= 0
                          ? currentSteps.map((s, idx) => (idx === stepIndex ? newStep : s))
                          : [...currentSteps, newStep]
                      return { ...msg, reasoningSteps: updatedSteps }
                    }
                    return msg
                  })
                )
              }
              // Фаза 9.3: Обработка human feedback request events
              if (data.type === 'human_feedback_request' || data.type === 'humanFeedbackRequest' || data.event === 'humanFeedbackRequest') {
                const isTableClarification = (data.interruptType || data.interrupt_type) === 'table_clarification'
                const payload = data.payload || {}
                
                const feedbackData: Message['feedbackRequest'] = {
                  requestId: data.request_id || data.requestId,
                  question: data.question || data.message,
                  options: data.options || [],
                  requiresApproval: data.requires_approval || data.requiresApproval || false,
                  context: data.context || {},
                  agentName: data.agent_name || data.agentName,
                  inputSchema: data.input_schema || data.inputSchema,
                  interruptType: data.interruptType || data.interrupt_type,
                  threadId: data.threadId || data.thread_id,
                  payload: payload,
                  ...(isTableClarification && {
                    isTableClarification: true,
                    availableDocTypes: payload.available_doc_types || [],
                    questions: payload.questions || []
                  })
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
              // Обработка создания документа в режиме Draft
              if (data.type === 'document_created' && data.document) {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? {
                          ...msg,
                          documentCard: {
                            documentId: data.document.id,
                            title: data.document.title,
                            preview: data.document.content?.substring(0, 150),
                            caseId: data.document.case_id,
                          },
                          content: msg.content + `\n\n✅ Документ "${data.document.title}" создан!`,
                        }
                      : msg
                  )
                )
              }
              // Обработка edited_content для применения правок к документу
              if (data.type === 'edited_content' && data.edited_content) {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? { ...msg, editedContent: data.edited_content }
                      : msg
                  )
                )
              }
              // Также проверяем edited_content в обычном ответе (если приходит сразу)
              if (data.edited_content && !data.type) {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? { ...msg, editedContent: data.edited_content }
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
  }, [actualCaseId, isLoading, messages, legalResearch, deepThink, draftMode, documentEditorMode, currentDocumentContent, currentDocumentId, selectedText, attachments])

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

  const controller = useOptionalPromptInputController()

  const handlePromptSubmit = useCallback(async (message: { text: string; files: any[] }, _event: React.FormEvent<HTMLFormElement>) => {
    const text = message.text?.trim()
    
    // Валидация: проверяем, что есть текст или файлы
    if (!text && (!message.files || message.files.length === 0)) {
      // Можно показать toast или другое уведомление
      return
    }
    
    if (text && !isLoading && actualCaseId) {
      await sendMessage(text)
      
      // Очищаем поле ввода и attachments после успешной отправки
      if (controller) {
        controller.textInput.clear()
      }
      if (attachments) {
        attachments.clear()
      }
    }
  }, [sendMessage, isLoading, actualCaseId, controller, attachments])

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
    loadHistory: async (sessionId?: string) => {
      if (!actualCaseId) return
      
      // Если sessionId не указан, не загружаем историю (показываем пустой чат)
      if (!sessionId) {
        setMessages([])
        setIsLoadingHistory(false)
        return
      }
      
      setIsLoadingHistory(true)
      try {
        const historyMessages = await loadChatHistory(actualCaseId, sessionId)
        // Фильтруем пустые сообщения
        const validMessages = historyMessages.filter((msg) => msg.content && msg.content.trim() !== '')
        const convertedMessages: Message[] = validMessages.map((msg, index) => {
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
        setMessages([])
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
        {/* Selection-aware quick actions */}
        {documentEditorMode && selectedText && selectedText.trim() && (
          <div className="p-3 border-b border-border bg-bg-elevated shrink-0">
            <div className="text-xs text-text-secondary mb-2" style={{ color: 'var(--color-text-secondary)' }}>
              Выделено: "{selectedText.slice(0, 50)}{selectedText.length > 50 ? '...' : ''}"
            </div>
            <div className="flex gap-2 flex-wrap">
              <button
                onClick={() => sendMessage(`Улучши текст: ${selectedText}`)}
                disabled={isLoading}
                className="px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                style={{ 
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-primary)',
                  backgroundColor: 'var(--color-bg-primary)'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--color-bg-primary)'
                }}
              >
                Улучшить
              </button>
              <button
                onClick={() => sendMessage(`Проверь на риски: ${selectedText}`)}
                disabled={isLoading}
                className="px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                style={{ 
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-primary)',
                  backgroundColor: 'var(--color-bg-primary)'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--color-bg-primary)'
                }}
              >
                Проверить риски
              </button>
              <button
                onClick={() => sendMessage(`Переписать: ${selectedText}`)}
                disabled={isLoading}
                className="px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                style={{ 
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-primary)',
                  backgroundColor: 'var(--color-bg-primary)'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--color-bg-primary)'
                }}
              >
                Переписать
              </button>
            </div>
          </div>
        )}
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
              <div key={message.id}>
                <UserMessage content={message.content} />
                {/* Отображаем файлы под сообщением пользователя */}
                {message.attachments && message.attachments.length > 0 && (
                  <div className="mt-2 space-y-2">
                    {message.attachments.map((attachment) => (
                      <FileChip
                        key={attachment.id}
                        attachment={attachment}
                        onRemove={() => {}} // В отправленном сообщении нельзя удалять
                      />
                    ))}
                  </div>
                )}
              </div>
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
              {/* Отображение созданного документа в режиме Draft */}
              {message.documentCard && (
                <div className="mt-4">
                  <DocumentCard
                    documentId={message.documentCard.documentId}
                    title={message.documentCard.title}
                    preview={message.documentCard.preview}
                    caseId={message.documentCard.caseId}
                    onOpen={onOpenDocumentInEditor 
                      ? () => onOpenDocumentInEditor(message.documentCard!.documentId)
                      : undefined
                    }
                  />
                </div>
              )}
              {/* Фаза 9.3: Human feedback request card */}
              {message.feedbackRequest && (
                message.feedbackRequest.isTableClarification ? (
                  <TableClarificationModal
                    questions={message.feedbackRequest.questions || []}
                    context={message.feedbackRequest.context || {}}
                    availableDocTypes={message.feedbackRequest.availableDocTypes || []}
                    onSubmit={async (answer: { doc_types?: string[], columns_clarification?: string }) => {
                      try {
                        const token = localStorage.getItem('access_token')
                        const response_data = await fetch(getApiUrl('/api/assistant/chat/resume'), {
                          method: 'POST',
                          headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${token}`,
                          },
                          body: JSON.stringify({
                            thread_id: message.feedbackRequest?.threadId,
                            case_id: actualCaseId,
                            answer: answer,
                          }),
                        })

                        if (!response_data.ok) {
                          const errorData = await response_data.json().catch(() => ({}))
                          throw new Error(errorData.detail || 'Ошибка при возобновлении выполнения')
                        }

                        const result = await response_data.json()
                        logger.info('Graph execution resumed:', result)

                        // Clear feedback request from message
                        setMessages((prev) =>
                          prev.map((msg) =>
                            msg.id === message.id
                              ? {
                                  ...msg,
                                  feedbackRequest: undefined,
                                  content: msg.content + `\n\n**Ваш ответ:** ${JSON.stringify(answer)}\n\nПродолжаю выполнение...\n\n`,
                                }
                              : msg
                          )
                        )
                      } catch (error) {
                        logger.error('Error resuming graph execution:', error)
                        throw error
                      }
                    }}
                  />
                ) : (
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
                )
              )}
              {/* Кнопка "Применить изменения" для edited_content */}
              {message.editedContent && documentEditorMode && onApplyEdit && (
                <div className="mt-4 p-3 border rounded-lg bg-green-50 border-green-200">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-green-800">
                      Предложены изменения документа
                    </span>
                    <button
                      onClick={() => onApplyEdit(message.editedContent!)}
                      className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg bg-green-600 text-white hover:bg-green-700 transition-colors"
                    >
                      <Check className="w-4 h-4" />
                      Применить
                    </button>
                  </div>
                </div>
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
              webSearch={false}
              deepThink={deepThink}
              legalResearch={legalResearch}
              draftMode={draftMode}
              onWebSearchChange={() => {}}
              onDeepThinkChange={setDeepThink}
              onLegalResearchChange={setLegalResearch}
              onDraftModeChange={setDraftMode}
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
              webSearch={false}
              deepThink={deepThink}
              legalResearch={legalResearch}
              draftMode={draftMode}
              onWebSearchChange={() => {}}
              onDeepThinkChange={setDeepThink}
              onLegalResearchChange={setLegalResearch}
              onDraftModeChange={setDraftMode}
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

