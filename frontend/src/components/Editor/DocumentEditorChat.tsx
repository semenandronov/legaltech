import { useState, useEffect, useRef, useCallback } from 'react'
import { logger } from '@/lib/logger'
import { Conversation, ConversationContent } from '../ai-elements/conversation'
import { UserMessage, AssistantMessage } from '../ai-elements/message'
import { SettingsPanel } from '../Chat/SettingsPanel'
import {
  PromptInputProvider,
  PromptInput,
  PromptInputBody,
  PromptInputTextarea,
  PromptInputSubmit,
} from '../ai-elements/prompt-input'
import { Loader } from '../ai-elements/loader'
import { chatOverDocument, aiAssist, type StructuredEdit } from '@/services/documentEditorApi'
import { Button } from '@/components/UI/Button'
import { Check, Wand2, AlertTriangle, FileText, Sparkles, MessageCircleQuestion, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import { EditSuggestionsList } from './EditSuggestionCard'

// Ключевые слова для определения типа сообщения
const EDIT_KEYWORDS = [
  'изменить', 'редактировать', 'исправить', 'добавить', 'удалить',
  'переписать', 'улучшить', 'заменить', 'вставить', 'убрать',
  'поменять', 'обновить', 'дополнить', 'сократить', 'расширить'
]

type MessageType = 'question' | 'edit'

function detectMessageType(content: string): MessageType {
  const lowerContent = content.toLowerCase()
  return EDIT_KEYWORDS.some(keyword => lowerContent.includes(keyword)) ? 'edit' : 'question'
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  messageType?: MessageType  // Тип сообщения пользователя
  editedContent?: string  // Для применения правок (обратная совместимость)
  structuredEdits?: StructuredEdit[]  // Структурированные изменения
  citations?: Array<{ file: string; file_id: string }>
  suggestions?: string[]
}

interface DocumentEditorChatProps {
  documentId: string
  documentTitle?: string
  selectedText: string
  onApplyEdit?: (editedContent: string) => void
  onInsertText?: (text: string) => void
  onReplaceText?: (text: string) => void
  onScrollToText?: (text: string) => boolean
  onReplaceTextInDocument?: (originalText: string, newText: string) => boolean
}

export const DocumentEditorChat: React.FC<DocumentEditorChatProps> = ({
  documentId,
  documentTitle,
  selectedText,
  onApplyEdit,
  onInsertText,
  onReplaceText,
  onScrollToText,
  onReplaceTextInDocument,
}) => {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [legalResearch, setLegalResearch] = useState(false)
  const [deepThink, setDeepThink] = useState(false)
  const [quickActionLoading, setQuickActionLoading] = useState<string | null>(null)
  
  // Состояние для отслеживания примененных/пропущенных изменений
  const [appliedEdits, setAppliedEdits] = useState<Set<string>>(new Set())
  const [skippedEdits, setSkippedEdits] = useState<Set<string>>(new Set())

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = useCallback(async (userMessage: string) => {
    if (!userMessage.trim() || !documentId || isLoading) {
      if (!documentId) {
        toast.error('Сначала сохраните документ или создайте его из шаблона')
      }
      return
    }

    // Add user message with detected type
    const messageType = detectMessageType(userMessage)
    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: userMessage,
      messageType,
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

    try {
      const response = await chatOverDocument(documentId, userMessage.trim())
      
      // Update assistant message with response
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMsgId
            ? {
                ...msg,
                content: response.answer,
                editedContent: response.edited_content,
                structuredEdits: response.structured_edits,
                citations: response.citations,
                suggestions: response.suggestions,
              }
            : msg
        )
      )
    } catch (error: unknown) {
      logger.error('Document chat error:', error)
      const errorMessage = error instanceof Error ? error.message : 'Ошибка при получении ответа'
      toast.error(errorMessage)
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMsgId
            ? { ...msg, content: `Извините, произошла ошибка: ${errorMessage}` }
            : msg
        )
      )
    } finally {
      setIsLoading(false)
    }
  }, [documentId, isLoading])

  const handlePromptSubmit = useCallback(async (message: { text: string; files: any[] }, _event: React.FormEvent<HTMLFormElement>) => {
    const text = message.text?.trim()
    
    if (!text) return
    
    if (text && !isLoading && documentId) {
      await sendMessage(text)
    }
  }, [sendMessage, isLoading, documentId])

  // Expose sendMessage for quick actions (questions)
  const handleQuickQuestion = useCallback((prompt: string) => {
    if (prompt.trim() && !isLoading && documentId) {
      sendMessage(prompt)
    }
  }, [sendMessage, isLoading, documentId])

  const handleApplyEdit = useCallback((editedContent: string) => {
    if (onApplyEdit && editedContent) {
      onApplyEdit(editedContent)
      toast.success('Изменения применены к документу')
    }
  }, [onApplyEdit])
  
  // Обработчик применения одного структурированного изменения
  const handleApplyStructuredEdit = useCallback((edit: StructuredEdit) => {
    if (onReplaceTextInDocument) {
      const success = onReplaceTextInDocument(edit.original_text, edit.new_text)
      if (success) {
        setAppliedEdits(prev => new Set(prev).add(edit.id))
        toast.success('Изменение применено')
      } else {
        toast.error('Не удалось применить изменение. Текст не найден в документе.')
      }
    }
  }, [onReplaceTextInDocument])
  
  // Обработчик пропуска изменения
  const handleSkipEdit = useCallback((edit: StructuredEdit) => {
    setSkippedEdits(prev => new Set(prev).add(edit.id))
    toast.info('Изменение пропущено')
  }, [])
  
  // Обработчик навигации к тексту в документе
  const handleNavigateToText = useCallback((text: string) => {
    if (onScrollToText) {
      const success = onScrollToText(text)
      if (!success) {
        toast.error('Текст не найден в документе')
      }
    }
  }, [onScrollToText])
  
  // Применить все изменения
  const handleApplyAllEdits = useCallback((edits: StructuredEdit[]) => {
    if (!onReplaceTextInDocument) return
    
    let appliedCount = 0
    edits.forEach(edit => {
      if (!appliedEdits.has(edit.id) && !skippedEdits.has(edit.id) && edit.found_in_document) {
        const success = onReplaceTextInDocument(edit.original_text, edit.new_text)
        if (success) {
          setAppliedEdits(prev => new Set(prev).add(edit.id))
          appliedCount++
        }
      }
    })
    
    if (appliedCount > 0) {
      toast.success(`Применено изменений: ${appliedCount}`)
    }
  }, [onReplaceTextInDocument, appliedEdits, skippedEdits])
  
  // Пропустить все изменения
  const handleSkipAllEdits = useCallback((edits: StructuredEdit[]) => {
    const newSkipped = new Set(skippedEdits)
    edits.forEach(edit => {
      if (!appliedEdits.has(edit.id) && !skippedEdits.has(edit.id)) {
        newSkipped.add(edit.id)
      }
    })
    setSkippedEdits(newSkipped)
    toast.info('Все изменения пропущены')
  }, [appliedEdits, skippedEdits])

  const handleQuickAction = useCallback(async (command: string, label: string) => {
    if (!documentId || quickActionLoading) return

    setQuickActionLoading(command)
    try {
      const result = await aiAssist(documentId, command, selectedText, '')
      
      if (result.result) {
        // Если есть выделенный текст, заменяем его, иначе вставляем
        if (selectedText && onReplaceText) {
          onReplaceText(result.result)
          toast.success(`${label} применено к выделенному тексту`)
        } else if (onInsertText) {
          onInsertText(result.result)
          toast.success(`${label} добавлено в документ`)
        }
        
        // Также добавляем результат в чат как сообщение
        const userMsg: Message = {
          id: `user-${Date.now()}`,
          role: 'user',
          content: label,
        }
        const assistantMsg: Message = {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: `Выполнено действие "${label}". Результат применен к документу.\n\n${result.result}`,
          suggestions: result.suggestions,
        }
        setMessages((prev) => [...prev, userMsg, assistantMsg])
      }
    } catch (error: any) {
      toast.error(error.message || `Ошибка при выполнении "${label}"`)
    } finally {
      setQuickActionLoading(null)
    }
  }, [documentId, selectedText, onReplaceText, onInsertText, quickActionLoading])

  const quickActions = [
    {
      id: 'improve',
      label: 'Улучшить текст',
      icon: Wand2,
      command: 'improve',
      description: 'Улучшить текст профессионально'
    },
    {
      id: 'check_risks',
      label: 'Проверить на риски',
      icon: AlertTriangle,
      command: 'check_risks',
      description: 'Проверить текст на юридические риски'
    },
    {
      id: 'rewrite',
      label: 'Переписать',
      icon: FileText,
      command: 'rewrite',
      description: 'Переписать текст'
    },
  ]

  return (
    <PromptInputProvider>
      <div 
        className="flex flex-col h-full"
        style={{ backgroundColor: 'var(--color-bg-primary)' }}
      >
        {/* Messages area */}
        <div className="flex-1 min-h-0 flex flex-col">
          <Conversation className="flex-1 min-h-0 flex flex-col">
            <ConversationContent className="flex-1 overflow-y-auto">
              {messages.length === 0 && !isLoading ? (
                <div className="h-full flex items-start justify-center pt-8 pb-4 overflow-y-auto">
                  <div className="w-full max-w-2xl px-4">
                    <div className="text-center mb-6">
                      <div className="inline-flex items-center justify-center w-16 h-16 rounded-full mb-4" style={{ backgroundColor: 'var(--color-accent)', opacity: 0.1 }}>
                        <Sparkles className="w-8 h-8" style={{ color: 'var(--color-accent)' }} />
                      </div>
                      <h2 className="text-2xl font-semibold mb-2" style={{ color: 'var(--color-text-primary)' }}>
                        Чем могу помочь?
                      </h2>
                      <p className="text-sm mb-4" style={{ color: 'var(--color-text-secondary)' }}>
                        Задайте вопрос о документе или используйте быстрые действия
                      </p>
                      {documentTitle && (
                        <div className="inline-block px-3 py-1 rounded-full text-sm mb-4" style={{ 
                          backgroundColor: 'var(--color-bg-elevated)',
                          color: 'var(--color-text-secondary)'
                        }}>
                          {documentTitle}
                        </div>
                      )}
                    </div>

                    {/* Быстрые действия для документа */}
                    <div className="mb-6">
                      <p className="text-xs font-medium mb-3 text-center" style={{ color: 'var(--color-text-secondary)' }}>
                        Быстрые действия:
                      </p>
                      <div className="flex flex-wrap gap-2 justify-center">
                        {quickActions.map(action => (
                          <button
                            key={action.id}
                            onClick={() => handleQuickAction(action.command, action.label)}
                            disabled={quickActionLoading === action.command || !documentId}
                            className="px-4 py-2 text-sm border rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
                            style={{ 
                              borderColor: 'var(--color-border)',
                              color: 'var(--color-text-primary)'
                            }}
                            title={action.description}
                          >
                            {quickActionLoading === action.command ? (
                              <Loader size={16} style={{ color: 'var(--color-text-secondary)' }} />
                            ) : (
                              <action.icon className="w-4 h-4" />
                            )}
                            {action.label}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Быстрые действия для выделенного текста */}
                    {selectedText && (
                      <div className="mb-6 p-4 border rounded-lg" style={{ 
                        borderColor: 'var(--color-border)',
                        backgroundColor: 'var(--color-bg-elevated)'
                      }}>
                        <p className="text-xs font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                          Выделенный текст:
                        </p>
                        <p className="text-sm mb-3 line-clamp-2" style={{ color: 'var(--color-text-primary)' }}>
                          {selectedText.slice(0, 150)}{selectedText.length > 150 ? '...' : ''}
                        </p>
                        <div className="flex flex-wrap gap-2">
                          <button
                            onClick={() => handleQuickAction('improve', 'Улучшить выделенное')}
                            disabled={quickActionLoading === 'improve' || !documentId}
                            className="px-3 py-1.5 text-xs border rounded hover:bg-gray-100 disabled:opacity-50 transition-colors"
                            style={{ 
                              borderColor: 'var(--color-border)',
                              color: 'var(--color-text-primary)'
                            }}
                          >
                            Улучшить
                          </button>
                          <button
                            onClick={() => handleQuickAction('rewrite', 'Переписать выделенное')}
                            disabled={quickActionLoading === 'rewrite' || !documentId}
                            className="px-3 py-1.5 text-xs border rounded hover:bg-gray-100 disabled:opacity-50 transition-colors"
                            style={{ 
                              borderColor: 'var(--color-border)',
                              color: 'var(--color-text-primary)'
                            }}
                          >
                            Переписать
                          </button>
                          <button
                            onClick={() => handleQuickAction('check_risks', 'Проверить выделенное')}
                            disabled={quickActionLoading === 'check_risks' || !documentId}
                            className="px-3 py-1.5 text-xs border rounded hover:bg-gray-100 disabled:opacity-50 transition-colors"
                            style={{ 
                              borderColor: 'var(--color-border)',
                              color: 'var(--color-text-primary)'
                            }}
                          >
                            Проверить на риски
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Примеры вопросов */}
                    <div className="text-center">
                      <p className="text-xs font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                        Примеры вопросов:
                      </p>
                      <div className="flex flex-wrap gap-2 justify-center">
                        {[
                          'Проверь документ на риски',
                          'Улучши формулировки',
                          'Исправь ошибки',
                          'Что можно улучшить?'
                        ].map((question, idx) => (
                          <button
                            key={idx}
                            onClick={() => handleQuickQuestion(question)}
                            className="px-3 py-1 text-xs border rounded-full hover:bg-gray-100 transition-colors"
                            style={{ 
                              borderColor: 'var(--color-border)',
                              color: 'var(--color-text-primary)'
                            }}
                          >
                            {question}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              ) : null}

              {messages.map((message) => {
                if (message.role === 'user') {
                  const msgType = message.messageType || detectMessageType(message.content)
                  return (
                    <div key={message.id} className="mb-2">
                      {/* Бейдж типа сообщения */}
                      <div className="flex justify-end mb-1">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                          msgType === 'edit' 
                            ? 'bg-amber-100 text-amber-700' 
                            : 'bg-blue-100 text-blue-700'
                        }`}>
                          {msgType === 'edit' ? (
                            <>
                              <Pencil className="w-3 h-3" />
                              Редактирование
                            </>
                          ) : (
                            <>
                              <MessageCircleQuestion className="w-3 h-3" />
                              Вопрос
                            </>
                          )}
                        </span>
                      </div>
                      <UserMessage content={message.content} />
                    </div>
                  )
                }

                return (
                  <AssistantMessage
                    key={message.id}
                    content={message.content}
                    sources={message.citations?.map(c => ({
                      title: c.file,
                      file: c.file,
                    }))}
                    isStreaming={isLoading && message.id === messages[messages.length - 1]?.id}
                  >
                    {/* Карточки структурированных изменений */}
                    {message.structuredEdits && message.structuredEdits.length > 0 && (
                      <EditSuggestionsList
                        edits={message.structuredEdits}
                        onApply={handleApplyStructuredEdit}
                        onSkip={handleSkipEdit}
                        onNavigate={handleNavigateToText}
                        onApplyAll={() => handleApplyAllEdits(message.structuredEdits!)}
                        onSkipAll={() => handleSkipAllEdits(message.structuredEdits!)}
                        appliedIds={appliedEdits}
                        skippedIds={skippedEdits}
                      />
                    )}
                    
                    {/* Fallback: старая карточка для применения правок (если нет structured_edits) */}
                    {message.editedContent && (!message.structuredEdits || message.structuredEdits.length === 0) && (
                      <div className="mt-4 p-4 border rounded-lg" style={{ 
                        borderColor: 'var(--color-border)',
                        backgroundColor: 'var(--color-bg-elevated)'
                      }}>
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1">
                            <p className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                              Предложены изменения документа
                            </p>
                            <p className="text-xs mb-3" style={{ color: 'var(--color-text-secondary)' }}>
                              ИИ предложил правки к документу. Нажмите кнопку, чтобы применить их.
                            </p>
                          </div>
                          <Button
                            onClick={() => handleApplyEdit(message.editedContent!)}
                            size="sm"
                            className="shrink-0"
                          >
                            <Check className="w-4 h-4 mr-2" />
                            Применить
                          </Button>
                        </div>
                      </div>
                    )}

                    {/* Предложения как быстрые действия */}
                    {message.suggestions && message.suggestions.length > 0 && !message.suggestions.includes('Применить изменения') && (
                      <div className="mt-4 p-4 border rounded-lg" style={{ 
                        borderColor: 'var(--color-border)',
                        backgroundColor: 'var(--color-bg-elevated)'
                      }}>
                        <p className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                          Предложения:
                        </p>
                        <div className="flex flex-wrap gap-2">
                          {message.suggestions.filter(s => s !== 'Применить изменения').map((suggestion, idx) => (
                            <button
                              key={idx}
                              onClick={() => handleQuickAction(suggestion, suggestion)}
                              className="px-3 py-1.5 text-xs border rounded hover:bg-gray-100 transition-colors"
                              style={{ 
                                borderColor: 'var(--color-border)',
                                color: 'var(--color-text-primary)'
                              }}
                            >
                              {suggestion}
                            </button>
                          ))}
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

        {/* Input area */}
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
                        placeholder="Задайте вопрос о документе..."
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
                    disabled={isLoading || !documentId}
                    status={isLoading ? "submitted" : undefined}
                    aria-label="Отправить сообщение"
                  />
                </PromptInputBody>
              </PromptInput>

              {/* Компактная панель настроек */}
              <SettingsPanel
                webSearch={false}
                deepThink={deepThink}
                legalResearch={legalResearch}
                draftMode={false}
                onWebSearchChange={() => {}}
                onDeepThinkChange={setDeepThink}
                onLegalResearchChange={setLegalResearch}
                onDraftModeChange={() => {}}
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
                        placeholder="Задайте вопрос о документе..."
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
                    disabled={isLoading || !documentId}
                    status={isLoading ? "submitted" : undefined}
                    aria-label="Отправить сообщение"
                  />
                </PromptInputBody>
              </PromptInput>

              {/* Компактная панель настроек */}
              <SettingsPanel
                webSearch={false}
                deepThink={deepThink}
                legalResearch={legalResearch}
                draftMode={false}
                onWebSearchChange={() => {}}
                onDeepThinkChange={setDeepThink}
                onLegalResearchChange={setLegalResearch}
                onDraftModeChange={() => {}}
              />
            </div>
          </div>
        )}
      </div>
    </PromptInputProvider>
  )
}

