import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import './ChatWindow.css'
import { fetchHistory, sendMessage, SourceInfo, HistoryMessage } from '../services/api'
import ReactMarkdown from 'react-markdown'

interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: SourceInfo[]
}

interface ChatWindowProps {
  caseId: string
  fileNames?: string[]  // Optional, not currently used
}

const MAX_INPUT_CHARS = 5000

const RECOMMENDED_QUESTIONS: string[] = [
  'Сформулируй краткий обзор этого дела.',
  'Какие ключевые сроки и даты важны в этом деле?',
  'Есть ли нарушения условий контракта со стороны другой стороны?',
  'Каковы мои шансы выиграть спор в суде исходя из документов?',
]

const formatSourceReference = (source: SourceInfo): string => {
  let ref = `[Документ: ${source.file}`
  if (source.page) {
    ref += `, стр. ${source.page}`
  }
  if (source.start_line) {
    ref += `, строки ${source.start_line}`
    if (source.end_line && source.end_line !== source.start_line) {
      ref += `-${source.end_line}`
    }
  }
  ref += ']'
  return ref
}

const ChatWindow = ({ caseId }: ChatWindowProps) => {
  const navigate = useNavigate()
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
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
      const history = await fetchHistory(caseId)
      setMessages(
        history.map((msg: HistoryMessage) => ({
          role: msg.role,
          content: msg.content,
          sources: normalizeSources(msg.sources),
        })),
      )
    } catch (err) {
      console.error('Ошибка при загрузке истории:', err)
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

  const handleNavigateToAnalysis = () => {
    navigate(`/cases/${caseId}/analysis`)
  }

  const handleNavigateToTimeline = () => {
    navigate(`/cases/${caseId}/analysis`)
    // Timeline будет открыт по умолчанию или можно добавить hash
  }

  return (
    <div className="chat-container">
      {/* Navigation bar for quick access to analysis */}
      <div className="chat-nav-bar">
        <div className="chat-nav-buttons">
          <button
            type="button"
            className="chat-nav-button"
            onClick={handleNavigateToAnalysis}
            title="Перейти к анализу дела"
          >
            <span className="chat-nav-icon">📊</span>
            <span className="chat-nav-text">Анализ</span>
          </button>
          <button
            type="button"
            className="chat-nav-button"
            onClick={handleNavigateToTimeline}
            title="Показать таймлайн событий"
          >
            <span className="chat-nav-icon">📅</span>
            <span className="chat-nav-text">Таймлайн</span>
          </button>
        </div>
      </div>
      <div className="chat-messages">
        <div className="chat-messages-wrapper">
        {!hasMessages && !isLoading && (
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
                {/* Quick actions panel */}
                <div className="quick-actions-panel">
                  <div className="quick-actions-title">Быстрые действия:</div>
                  <div className="quick-actions-buttons">
                    <button
                      type="button"
                      className="quick-action-btn"
                      onClick={(e) => {
                        e.preventDefault()
                        handleSend('Проанализируй документы и найди все важные даты и события')
                      }}
                    >
                      📅 Извлечь таймлайн
                    </button>
                    <button
                      type="button"
                      className="quick-action-btn"
                      onClick={(e) => {
                        e.preventDefault()
                        handleSend('Проанализируй документы и найди все противоречия и несоответствия')
                      }}
                    >
                      ⚠️ Найти противоречия
                    </button>
                    <button
                      type="button"
                      className="quick-action-btn"
                      onClick={(e) => {
                        e.preventDefault()
                        handleSend('Извлеки ключевые факты из документов')
                      }}
                    >
                      🎯 Ключевые факты
                    </button>
                    <button
                      type="button"
                      className="quick-action-btn"
                      onClick={(e) => {
                        e.preventDefault()
                        handleSend('Проведи анализ рисков по этому делу')
                      }}
                    >
                      📈 Анализ рисков
                    </button>
                  </div>
                </div>
              </div>
          </div>
        )}

        {messages.map((message, index) => (
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
              {message.sources && message.sources.length > 0 && (
                <div className="sources">
                  <div className="sources-title">Источники:</div>
                  <div className="sources-list">
                    {message.sources.map((source, idx) => {
                      const sourceRef = formatSourceReference(source)
                      return (
                        <div key={idx} className="source-item" title={source.text_preview || sourceRef}>
                          <span className="source-ref">{sourceRef}</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}

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
              onClick={handleSend}
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

