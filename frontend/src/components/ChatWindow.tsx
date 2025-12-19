import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import './ChatWindow.css'
import './Chat/Chat.css'
import { fetchHistory, sendMessage, SourceInfo, HistoryMessage, classifyDocuments, extractEntities, getTimeline, getAnalysisReport } from '../services/api'
import ReactMarkdown from 'react-markdown'
import QuickButtons from './Chat/QuickButtons'
import ConfidenceBadge from './Common/ConfidenceBadge'
import CitationLink from './Chat/CitationLink'
import Autocomplete from './Chat/Autocomplete'
import StatisticsChart from './Chat/StatisticsChart'

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

const COMMANDS = [
  { command: 'Классифицируй', full: 'Классифицируй все документы в деле' },
  { command: 'Найди привилегии', full: 'Найди все привилегированные документы' },
  { command: 'Таймлайн', full: 'Покажи таймлайн событий из документов' },
  { command: 'Статистика', full: 'Покажи статистику по делу' },
  { command: 'Извлеки сущности', full: 'Извлеки все сущности из документов' },
]

const ChatWindow = ({ caseId, onDocumentClick }: ChatWindowProps) => {
  const navigate = useNavigate()
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [autocompleteVisible, setAutocompleteVisible] = useState(false)
  const [autocompleteSuggestions, setAutocompleteSuggestions] = useState<string[]>([])
  const [autocompleteSelectedIndex, setAutocompleteSelectedIndex] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [droppedFiles, setDroppedFiles] = useState<File[]>([])
  const [actionHistory, setActionHistory] = useState<Array<{
    type: 'batch_withhold' | 'batch_confirm' | 'batch_reject' | 'message'
    data: any
    timestamp: number
  }>>([])

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
      
      // Save user message to history for undo (not assistant response)
      setActionHistory(prev => [...prev, {
        type: 'message',
        data: { message: userMessage },
        timestamp: Date.now()
      }])
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
    if (autocompleteVisible && autocompleteSuggestions.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setAutocompleteSelectedIndex(prev => 
          prev < autocompleteSuggestions.length - 1 ? prev + 1 : prev
        )
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setAutocompleteSelectedIndex(prev => prev > 0 ? prev - 1 : 0)
        return
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        const selected = autocompleteSuggestions[autocompleteSelectedIndex]
        if (selected) {
          const fullCommand = COMMANDS.find(c => c.command === selected)?.full || selected
          handleSend(fullCommand)
          setAutocompleteVisible(false)
        }
        return
      }
      if (e.key === 'Escape') {
        setAutocompleteVisible(false)
        return
      }
    }
    
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value
    setInputValue(value)
    
    // Auto-resize textarea
    const textarea = e.target
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`
    
    // Show autocomplete if user types "/" or starts typing a command
    if (value.startsWith('/') || value.length > 0) {
      const query = value.startsWith('/') ? value.slice(1).toLowerCase() : value.toLowerCase()
      const suggestions = COMMANDS
        .filter(c => c.command.toLowerCase().includes(query) || c.full.toLowerCase().includes(query))
        .map(c => c.command)
        .slice(0, 5)
      
      if (suggestions.length > 0 && query.length > 0) {
        setAutocompleteSuggestions(suggestions)
        setAutocompleteSelectedIndex(0)
        setAutocompleteVisible(true)
      } else {
        setAutocompleteVisible(false)
      }
    } else {
      setAutocompleteVisible(false)
    }
  }
  
  const handleAutocompleteSelect = (suggestion: string) => {
    const fullCommand = COMMANDS.find(c => c.command === suggestion)?.full || suggestion
    setInputValue(fullCommand)
    setAutocompleteVisible(false)
  }

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)

    const files = Array.from(e.dataTransfer.files)
    if (files.length === 0) return

    // Filter allowed file types
    const allowedTypes = ['.pdf', '.docx', '.txt', '.xlsx']
    const validFiles = files.filter(file => {
      const ext = '.' + file.name.split('.').pop()?.toLowerCase()
      return allowedTypes.includes(ext)
    })

    if (validFiles.length === 0) {
      setError('Поддерживаются только файлы: PDF, DOCX, TXT, XLSX')
      return
    }

    setDroppedFiles(validFiles)
    
    // Automatically send message to analyze the file
    try {
      setIsLoading(true)
      const fileNames = validFiles.map(f => f.name).join(', ')
      const message = `Проанализируй эти файлы: ${fileNames}`
      await handleSend(message)
      setDroppedFiles([])
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка при обработке файлов')
    } finally {
      setIsLoading(false)
    }
  }

  const handleFileInput = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    if (files.length === 0) return

    const allowedTypes = ['.pdf', '.docx', '.txt', '.xlsx']
    const validFiles = files.filter(file => {
      const ext = '.' + file.name.split('.').pop()?.toLowerCase()
      return allowedTypes.includes(ext)
    })

    if (validFiles.length === 0) {
      setError('Поддерживаются только файлы: PDF, DOCX, TXT, XLSX')
      return
    }

    setDroppedFiles(validFiles)
    
    try {
      setIsLoading(true)
      const fileNames = validFiles.map(f => f.name).join(', ')
      const message = `Проанализируй эти файлы: ${fileNames}`
      await handleSend(message)
      setDroppedFiles([])
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка при обработке файлов')
    } finally {
      setIsLoading(false)
    }
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

  const handleUndo = async () => {
    if (actionHistory.length === 0) return

    const lastAction = actionHistory[actionHistory.length - 1]
    
    try {
      setIsLoading(true)
      
      // Revert the last action
      switch (lastAction.type) {
        case 'batch_withhold':
          // TODO: Implement undo for batch withhold
          // This would require an API endpoint to revert the action
          console.log('Undo batch withhold:', lastAction.data)
          // For now, just remove from history
          break
        case 'batch_confirm':
          // TODO: Implement undo for batch confirm
          console.log('Undo batch confirm:', lastAction.data)
          break
        case 'batch_reject':
          // TODO: Implement undo for batch reject
          console.log('Undo batch reject:', lastAction.data)
          break
        case 'message':
          // Remove the last message
          setMessages((prev) => prev.slice(0, -1))
          break
      }
      
      // Remove action from history
      setActionHistory((prev) => prev.slice(0, -1))
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка при отмене действия')
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

  // Извлекаем статистику из ответа для отображения в chart
  const extractStatistics = (content: string): { type: 'bar' | 'pie', title?: string, data: Array<{ name: string, value: number }> } | null => {
    // Попробуем найти числовые данные в ответе
    // Примеры: "3 контракта", "28 документов", "5.0млн", "23.7млн"
    const numberMatches = content.matchAll(/(\d+(?:\.\d+)?)\s*(?:млн|тыс|контракт|документ|файл|сумма|руб)/gi)
    const data: Array<{ name: string, value: number }> = []
    
    for (const match of numberMatches) {
      const value = parseFloat(match[1])
      const unit = match[2] || ''
      if (!isNaN(value) && value > 0) {
        data.push({
          name: `${value} ${unit}`.trim(),
          value: value
        })
      }
    }

    // Если нашли данные, создаем chart
    if (data.length > 0) {
      return {
        type: data.length <= 5 ? 'pie' : 'bar',
        title: 'Статистика',
        data: data.slice(0, 10) // Ограничиваем до 10 элементов
      }
    }

    // Попробуем найти структурированные данные (списки с числами)
    const listMatches = content.match(/(?:•|[-*])\s*([^:]+):\s*(\d+(?:\.\d+)?)/gi)
    if (listMatches && listMatches.length > 0) {
      const chartData: Array<{ name: string, value: number }> = []
      for (const match of listMatches.slice(0, 10)) {
        const parts = match.match(/(?:•|[-*])\s*([^:]+):\s*(\d+(?:\.\d+)?)/i)
        if (parts && parts.length >= 3) {
          const name = parts[1].trim()
          const value = parseFloat(parts[2])
          if (!isNaN(value)) {
            chartData.push({ name, value })
          }
        }
      }
      if (chartData.length > 0) {
        return {
          type: chartData.length <= 5 ? 'pie' : 'bar',
          title: 'Статистика',
          data: chartData
        }
      }
    }

    return null
  }

  return (
    <div 
      className={`chat-container ${isDragging ? 'dragging' : ''}`}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {isDragging && (
        <div className="chat-drag-overlay">
          <div className="chat-drag-overlay-content">
            <div className="chat-drag-overlay-icon">📎</div>
            <div className="chat-drag-overlay-text">Перетащите файлы сюда</div>
            <div className="chat-drag-overlay-hint">PDF, DOCX, TXT, XLSX</div>
          </div>
        </div>
      )}
      <div className="chat-header">
        <h3 className="chat-header-title">🤖 E-Discovery Assistant</h3>
        {actionHistory.length > 0 && (
          <button
            className="chat-undo-button"
            onClick={handleUndo}
            title="Отменить последнее действие"
            aria-label="Отменить последнее действие"
          >
            ↶ Undo
          </button>
        )}
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
          const statistics = message.role === 'assistant' ? extractStatistics(message.content) : null
          const hasSources = message.sources && message.sources.length > 0
          const hasMultipleSources = hasSources && message.sources && message.sources.length > 1

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
                
                {statistics && (
                  <div style={{ marginTop: '16px' }}>
                    <StatisticsChart data={statistics} />
                  </div>
                )}
                
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
                          onClick={async () => {
                            try {
                              const fileIds = message.sources?.map(s => {
                                // Extract file ID from filename if needed
                                // This is a placeholder - actual implementation depends on your data structure
                                return s.file
                              }) || []
                              
                              // Save action to history for undo
                              setActionHistory(prev => [...prev, {
                                type: 'batch_withhold',
                                data: { fileIds, sources: message.sources },
                                timestamp: Date.now()
                              }])
                              
                              // TODO: Call batch withhold API
                              console.log('Withhold these', fileIds)
                            } catch (err) {
                              console.error('Error withholding documents:', err)
                            }
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
        {droppedFiles.length > 0 && (
          <div className="chat-dropped-files">
            {droppedFiles.map((file, index) => (
              <div key={index} className="chat-dropped-file">
                <span className="chat-dropped-file-name">📎 {file.name}</span>
                <button
                  type="button"
                  className="chat-dropped-file-remove"
                  onClick={() => setDroppedFiles(prev => prev.filter((_, i) => i !== index))}
                  aria-label="Удалить файл"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="chat-input-wrapper">
          <div className="chat-input-main">
            <div className="chat-input-container">
              <textarea
                className="chat-input-textarea"
                placeholder="Сообщение Legal AI... (начните с / для команд или перетащите файлы)"
                value={inputValue}
                onChange={handleTextareaChange}
                onKeyDown={handleKeyDown}
                disabled={isLoading}
                rows={1}
                aria-label="Введите сообщение"
                aria-describedby="input-help"
              />
              <Autocomplete
                suggestions={autocompleteSuggestions}
                selectedIndex={autocompleteSelectedIndex}
                onSelect={handleAutocompleteSelect}
                visible={autocompleteVisible}
              />
            </div>
            <div className="chat-input-actions">
              <input
                type="file"
                id="chat-file-input"
                multiple
                accept=".pdf,.docx,.txt,.xlsx"
                onChange={handleFileInput}
                style={{ display: 'none' }}
              />
              <label htmlFor="chat-file-input" className="chat-file-button" title="Прикрепить файл">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M8 2a2 2 0 00-2 2v12a2 2 0 002 2h4a2 2 0 002-2V7.414A2 2 0 0013.414 6L9 .586A2 2 0 008 2z" stroke="currentColor" strokeWidth="2" fill="none"/>
                </svg>
              </label>
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
    </div>
  )
}

export default ChatWindow

