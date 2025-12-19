import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import './ChatWindow.css'
import './Chat/Chat.css'
import { fetchHistory, sendMessage, SourceInfo, HistoryMessage, classifyDocuments, extractEntities, getTimeline, getAnalysisReport } from '../services/api'
import ReactMarkdown from 'react-markdown'
import QuickButtons from './Chat/QuickButtons'
import ConfidenceBadge from './Common/ConfidenceBadge'
import CitationLink from './Chat/CitationLink'

interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: SourceInfo[]
}

interface ChatWindowProps {
  caseId: string
  fileNames?: string[]
  onDocumentClick?: (filename: string) => void  // Callback для открытия документа в viewer
}

const MAX_INPUT_CHARS = 5000

const RECOMMENDED_QUESTIONS: string[] = [
  'Сформулируй краткий обзор этого дела.',
  'Какие ключевые сроки и даты важны в этом деле?',
  'Есть ли нарушения условий контракта со стороны другой стороны?',
  'Каковы мои шансы выиграть спор в суде исходя из документов?',
]

const ChatWindow = ({ caseId, onDocumentClick }: ChatWindowProps) => {
  const navigate = useNavigate()
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadHistory()
  }, [caseId])

  useEffect(() => {
    scrollToBottom()
  }, [messages, isLoading])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  // Type guard to check if source is SourceInfo
  const isSourceInfo = (source: string | SourceInfo): source is SourceInfo => {
    return typeof source === 'object' && source !== null && 'file' in source
  }

  // Type guard to check if sources array contains SourceInfo
  const hasSourceInfo = (sources: (string | SourceInfo)[] | undefined): sources is SourceInfo[] => {
    if (!sources || sources.length === 0) return false
    return sources.every(s => isSourceInfo(s))
  }

  const normalizeSources = (sources: (string | SourceInfo)[] | undefined): SourceInfo[] => {
    if (!sources || sources.length === 0) return []
    
    // If all sources are already SourceInfo, return as is
    if (hasSourceInfo(sources)) {
      return sources
    }
    
    // Convert string sources to SourceInfo
    return sources.map((s): SourceInfo => {
      if (isSourceInfo(s)) {
        return s
      }
      // It's a string
      return { file: s as string }
    })
  }

  const loadHistory = async () => {
    try {
      setHistoryError(null)
      const history = await fetchHistory(caseId)
      setMessages(
        history.map((msg: HistoryMessage) => ({
          role: msg.role,
          content: msg.content,
          sources: normalizeSources(msg.sources),
        })),
      )
    } catch (err: any) {
      console.error('Ошибка при загрузке истории:', err)
      setHistoryError(err.response?.data?.detail || 'Ошибка при загрузке истории сообщений')
    }
  }

  const handleSend = async (customMessage?: string) => {
    const messageToSend = customMessage || inputValue
    if (!messageToSend.trim() || isLoading) {
      return
    }

    const trimmed = messageToSend.slice(0, MAX_INPUT_CHARS).trim()
    const userMessage: Message = {
      role: 'user',
      content: trimmed,
    }

    setMessages((prev) => [...prev, userMessage])
    if (!customMessage) {
      setInputValue('')
    }
    setIsLoading(true)
    setError(null)

    try {
      const response = await sendMessage(caseId, userMessage.content)
      if (response.status === 'success' || response.status === 'task_planned') {
        const assistantMessage: Message = {
          role: 'assistant',
          content: response.answer,
          sources: response.sources || [],
        }
        setMessages((prev) => [...prev, assistantMessage])
      } else {
        setError('Ошибка при получении ответа')
      }
    } catch (err: any) {
      setError(
        err.response?.data?.detail ||
          'Ошибка при отправке вопроса. Проверьте, что backend запущен.',
      )
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputValue(e.target.value)
    // Auto-resize textarea
    const textarea = e.target
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`
  }

  const handleRecommendedClick = (question: string) => {
    setInputValue(question)
  }

  const remainingChars = MAX_INPUT_CHARS - inputValue.length
  const isOverLimit = remainingChars < 0

  const hasMessages = messages.length > 0

  const handleClassifyAll = async () => {
    try {
      setIsLoading(true)
      await classifyDocuments(caseId)
      const response = await sendMessage(caseId, 'Классифицируй все документы в деле')
      const assistantMessage: Message = {
        role: 'assistant',
        content: response.answer,
        sources: response.sources || []
      }
      setMessages((prev) => [...prev, assistantMessage])
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка при классификации документов')
    } finally {
      setIsLoading(false)
    }
  }

  const handleFindPrivilege = async () => {
    try {
      setIsLoading(true)
      const response = await sendMessage(caseId, 'Найди все привилегированные документы')
      const assistantMessage: Message = {
        role: 'assistant',
        content: response.answer,
        sources: response.sources || []
      }
      setMessages((prev) => [...prev, assistantMessage])
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка при поиске привилегированных документов')
    } finally {
      setIsLoading(false)
    }
  }

  const handleTimeline = async () => {
    try {
      setIsLoading(true)
      const timeline = await getTimeline(caseId)
      const response = await sendMessage(caseId, 'Покажи таймлайн событий из документов')
      const assistantMessage: Message = {
        role: 'assistant',
        content: response.answer || `Найдено ${timeline.total} событий в таймлайне`,
        sources: response.sources || []
      }
      setMessages((prev) => [...prev, assistantMessage])
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка при загрузке таймлайна')
    } finally {
      setIsLoading(false)
    }
  }

  const handleStatistics = async () => {
    try {
      setIsLoading(true)
      const report = await getAnalysisReport(caseId)
      const statsText = `Статистика по делу:\n- Всего файлов: ${report.total_files}\n- Высокая релевантность: ${report.summary.high_relevance_count}\n- Привилегированных: ${report.summary.privileged_count}\n- Низкая релевантность: ${report.summary.low_relevance_count}`
      const assistantMessage: Message = {
        role: 'assistant',
        content: statsText,
        sources: []
      }
      setMessages((prev) => [...prev, assistantMessage])
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка при загрузке статистики')
    } finally {
      setIsLoading(false)
    }
  }

  const handleExtractEntities = async () => {
    try {
      setIsLoading(true)
      await extractEntities(caseId)
      const response = await sendMessage(caseId, 'Извлеки все сущности из документов')
      const assistantMessage: Message = {
        role: 'assistant',
        content: response.answer,
        sources: response.sources || []
      }
      setMessages((prev) => [...prev, assistantMessage])
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка при извлечении сущностей')
    } finally {
      setIsLoading(false)
    }
  }

  const handleCitationClick = (source: SourceInfo) => {
    if (onDocumentClick) {
      onDocumentClick(source.file)
    } else {
      // Fallback: навигация к анализу
      navigate(`/cases/${caseId}/workspace`)
    }
  }

  // Извлекаем confidence из ответа (если есть)
  const extractConfidence = (content: string): number | null => {
    const match = content.match(/(\d+)%?\s*(?:confidence|уверенность|conf)/i)
    if (match) {
      return parseInt(match[1])
    }
    return null
  }

  return (
    <div className="chat-container">
      <div className="chat-header">
        <h3 className="chat-header-title">🤖 E-Discovery Assistant</h3>
      </div>

      {!hasMessages && !isLoading && !historyError && (
        <QuickButtons
          onClassifyAll={handleClassifyAll}
          onFindPrivilege={handleFindPrivilege}
          onTimeline={handleTimeline}
          onStatistics={handleStatistics}
          onExtractEntities={handleExtractEntities}
        />
      )}

      <div className="chat-messages">
        <div className="chat-messages-wrapper">
        {historyError && (
          <div className="error-message" style={{ padding: '12px', margin: '16px', background: '#fee2e2', color: '#ef4444', borderRadius: '6px' }}>
            ⚠️ {historyError}
            <button
              onClick={loadHistory}
              style={{
                marginLeft: '12px',
                padding: '4px 12px',
                background: '#4299e1',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '12px',
              }}
            >
              Обновить
            </button>
          </div>
        )}
        {!hasMessages && !isLoading && !historyError && (
          <div className="empty-state">
            <div className="empty-card">
              <div className="empty-icon">⚖️</div>
              <h3 className="empty-title">Legal AI</h3>
              <p className="empty-subtitle">
                Задайте вопрос по загруженным документам. AI проанализирует контракты, переписку и таблицы.
              </p>
              <div className="empty-questions-grid">
                {RECOMMENDED_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    className="empty-question-btn"
                    onClick={() => handleRecommendedClick(q)}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {messages.map((message, index) => {
          const confidence = extractConfidence(message.content)
          const hasSources = message.sources && message.sources.length > 0
          const hasMultipleSources = hasSources && message.sources.length > 1

          return (
            <div
              key={index}
              className={`message ${message.role === 'user' ? 'message-user' : 'message-assistant'}`}
              role="article"
              aria-label={message.role === 'user' ? 'Сообщение пользователя' : 'Ответ ассистента'}
            >
              {message.role === 'assistant' && (
                <div className="message-avatar assistant-avatar">AI</div>
              )}
              {message.role === 'user' && (
                <div className="message-avatar user-avatar">You</div>
              )}
              <div className={`message-bubble ${message.role}`}>
                <div className="message-text">
                  <ReactMarkdown>{message.content}</ReactMarkdown>
                </div>
                
                {message.role === 'assistant' && confidence !== null && (
                  <div style={{ marginTop: '8px' }}>
                    <span style={{ fontSize: '12px', color: '#6b7280' }}>Уверенность: </span>
                    <ConfidenceBadge confidence={confidence} />
                  </div>
                )}

                {hasSources && message.sources && (
                  <div className="chat-message-sources">
                    <div className="chat-message-sources-title">Источники:</div>
                    <div className="chat-message-sources-list">
                      {message.sources.map((source, idx) => (
                        <CitationLink
                          key={idx}
                          source={source}
                          onClick={handleCitationClick}
                        />
                      ))}
                    </div>
                    {hasMultipleSources && message.sources && (
                      <div className="chat-batch-actions">
                        <button
                          className="chat-batch-action-btn"
                          onClick={() => {
                            // TODO: Реализовать batch withhold для найденных документов
                            console.log('Withhold these', message.sources?.map(s => s.file))
                          }}
                        >
                          🔒 Withhold эти {message.sources.length}
                        </button>
                        <button
                          className="chat-batch-action-btn secondary"
                          onClick={() => {
                            // TODO: Реализовать export списка
                            console.log('Export list', message.sources?.map(s => s.file))
                          }}
                        >
                          📋 Экспорт список
                        </button>
                        <button
                          className="chat-batch-action-btn secondary"
                          onClick={() => {
                            // TODO: Показать статистику
                            handleStatistics()
                          }}
                        >
                          📊 Статистика по типам
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )
        })}

        {isLoading && (
          <div className="message message-assistant" role="status" aria-live="polite">
            <div className="message-avatar assistant-avatar" aria-hidden="true">AI</div>
            <div className="message-bubble assistant loading-bubble">
              <div className="typing-indicator" aria-label="Генерация ответа">
                <div className="typing-dot"></div>
                <div className="typing-dot"></div>
                <div className="typing-dot"></div>
              </div>
            </div>
          </div>
        )}

        {error && <div className="error-message">{error}</div>}

        <div ref={messagesEndRef} />
        </div>
      </div>

      <div className="chat-input-area">
        <div className="chat-input-wrapper">
          <div className="chat-input-main">
            <textarea
              className="chat-input-textarea"
              placeholder="Сообщение Legal AI..."
              value={inputValue}
              onChange={handleTextareaChange}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
              rows={1}
              aria-label="Введите сообщение"
              aria-describedby="input-help"
            />
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault()
                handleSend()
              }}
              disabled={isLoading || !inputValue.trim() || isOverLimit}
              className="send-button"
              title="Отправить (Enter)"
              aria-label="Отправить сообщение"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M.5 1.163L1.847.5l13.5 7.5-13.5 7.5L.5 14.837V8.837l8.5-1.674L.5 5.837V1.163z" fill="currentColor"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default ChatWindow

