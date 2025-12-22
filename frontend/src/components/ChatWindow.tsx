import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Box, Flex, Text, TextArea, Button, IconButton, Card } from '@radix-ui/themes'
import { Send, Paperclip } from 'lucide-react'
import './ChatWindow.css'
import './Chat/Chat.css'
import { fetchHistory, sendMessage, SourceInfo, HistoryMessage, classifyDocuments, extractEntities, getTimeline, getAnalysisReport } from '../services/api'
import { useWebSocketChat } from '../hooks/useWebSocketChat'
import QuickButtons from './Chat/QuickButtons'
import ConfidenceBadge from './Common/ConfidenceBadge'
import MessageContent from './Chat/MessageContent'
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
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [autocompleteVisible, setAutocompleteVisible] = useState(false)
  const [autocompleteSuggestions, setAutocompleteSuggestions] = useState<string[]>([])
  const [autocompleteSelectedIndex, setAutocompleteSelectedIndex] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [droppedFiles, setDroppedFiles] = useState<File[]>([])
  const [streamingContent, setStreamingContent] = useState('')
  const [streamingSources, setStreamingSources] = useState<SourceInfo[]>([])
  const currentStreamingMessageRef = useRef<number | null>(null)
  
  // Placeholder rotation for Perplexity UX
  const PLACEHOLDERS = [
    'Задайте вопрос...',
    'Объясни как 5-летнему...',
    'Сравни документы...',
    'Найди противоречия...',
    'Что говорит договор о...',
    'Какие сроки важны...',
  ]
  const [currentPlaceholderIndex, setCurrentPlaceholderIndex] = useState(0)
  const [proSearchEnabled, setProSearchEnabled] = useState(false)

  // WebSocket streaming hook
  const { isConnected, isStreaming: isWebSocketStreaming, sendMessage: sendWebSocketMessage } = useWebSocketChat({
    caseId,
    onMessage: (content: string) => {
      setStreamingContent(prev => prev + content)
      // Auto-scroll during streaming
      setTimeout(() => scrollToBottom(), 50)
    },
    onSources: (sources: any[]) => {
      setStreamingSources(sources)
    },
    onError: (errorMsg: string) => {
      setError(errorMsg)
      setIsLoading(false)
      setStreamingContent('')
      setStreamingSources([])
      if (currentStreamingMessageRef.current !== null) {
        // Remove incomplete streaming message
        setMessages(prev => prev.filter((_, idx) => idx !== currentStreamingMessageRef.current))
        currentStreamingMessageRef.current = null
      }
    },
    onComplete: () => {
      // Finalize streaming message
      if (currentStreamingMessageRef.current !== null && streamingContent) {
        setMessages(prev => prev.map((msg, idx) => 
          idx === currentStreamingMessageRef.current 
            ? { ...msg, content: streamingContent, sources: streamingSources }
            : msg
        ))
        currentStreamingMessageRef.current = null
        setStreamingContent('')
        setStreamingSources([])
      }
      setIsLoading(false)
      setTimeout(() => scrollToBottom(), 200)
    },
    enabled: true,
  })

  useEffect(() => {
    loadHistory()
  }, [caseId])

  // Placeholder rotation effect
  useEffect(() => {
    if (inputValue) return // Don't rotate if user is typing
    
    const interval = setInterval(() => {
      setCurrentPlaceholderIndex((prev) => (prev + 1) % PLACEHOLDERS.length)
    }, 3000) // Rotate every 3 seconds
    
    return () => clearInterval(interval)
  }, [inputValue])

  useEffect(() => {
    // Perplexity-style smooth scroll with delay for better UX
    const timer = setTimeout(() => {
    scrollToBottom()
    }, 100)
    return () => clearTimeout(timer)
  }, [messages, isLoading])

  const scrollToBottom = () => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ 
        behavior: 'smooth',
        block: 'end'
      })
    }
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
    if (!messageToSend.trim() || isLoading || isWebSocketStreaming) {
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
    setError(null)

    // Perplexity-style: smooth scroll after user message
    setTimeout(() => {
      scrollToBottom()
    }, 150)
    
    setIsLoading(true)
    setStreamingContent('')
    setStreamingSources([])

    // Use WebSocket streaming if available, fallback to HTTP
    if (isConnected) {
      // Create placeholder assistant message for streaming
      const assistantMessage: Message = {
        role: 'assistant',
        content: '',
        sources: [],
      }
      const messageIndex = messages.length
      setMessages(prev => [...prev, assistantMessage])
      currentStreamingMessageRef.current = messageIndex
      
      // Send via WebSocket
      const history = messages.map(m => ({ role: m.role, content: m.content }))
      sendWebSocketMessage(trimmed, history, proSearchEnabled)
    } else {
      // Fallback to HTTP
    try {
      const response = await sendMessage(caseId, userMessage.content)
      if (response.status === 'success' || response.status === 'task_planned') {
      const assistantMessage: Message = {
        role: 'assistant',
        content: response.answer,
        sources: response.sources || [],
      }
      setMessages((prev) => [...prev, assistantMessage])
      
          // Perplexity-style: smooth scroll after AI response
          setTimeout(() => {
            scrollToBottom()
          }, 200)
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
    
    // Auto-resize textarea - only expand vertically, not horizontally
    const textarea = e.target
    // Reset height to get accurate scrollHeight
    textarea.style.height = '24px'
    const newHeight = Math.min(Math.max(textarea.scrollHeight, 24), 200)
    textarea.style.height = `${newHeight}px`
    
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
    <Box 
      className={`chat-container ${isDragging ? 'dragging' : ''}`}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      style={{ 
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        backgroundColor: 'var(--color-bg)',
        position: 'relative',
        overflow: 'hidden'
      }}
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
      {/* Header removed for Perplexity style */}

      {!hasMessages && !isLoading && !historyError && (
        <QuickButtons
          onClassifyAll={handleClassifyAll}
          onFindPrivilege={handleFindPrivilege}
          onTimeline={handleTimeline}
          onStatistics={handleStatistics}
          onExtractEntities={handleExtractEntities}
        />
      )}

      <Box 
        className="chat-messages"
        style={{
          flex: 1,
          overflowY: 'auto',
          overflowX: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          padding: 0,
          width: '100%',
          backgroundColor: 'var(--color-bg)',
          scrollBehavior: 'smooth',
        }}
      >
        <Box 
          className="chat-messages-wrapper"
          style={{
            width: '100%',
            maxWidth: '768px',
            margin: '0 auto',
            padding: '80px 24px 140px',
          }}
        >
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
          <Box 
            className="empty-state"
            style={{
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center',
              height: '100%',
              padding: '40px 24px',
            }}
          >
            <Card 
              className="empty-card"
              style={{
                maxWidth: '640px',
                width: '100%',
                textAlign: 'center',
                padding: '40px',
              }}
            >
              <Box style={{ fontSize: '48px', marginBottom: '24px', opacity: 0.9 }}>⚖️</Box>
              <Text size="7" weight="bold" style={{ marginBottom: '12px', display: 'block' }}>
                Legal AI
              </Text>
              <Text size="3" color="gray" style={{ marginBottom: '40px', display: 'block', lineHeight: 1.6 }}>
                Задайте вопрос по загруженным документам. AI проанализирует контракты, переписку и таблицы.
              </Text>
              <Box 
                className="empty-questions-grid"
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
                  gap: '12px',
                  maxWidth: '600px',
                  margin: '0 auto',
                }}
              >
                {RECOMMENDED_QUESTIONS.map((q) => (
                  <Button
                    key={q}
                    variant="soft"
                    size="3"
                    onClick={() => handleRecommendedClick(q)}
                    style={{
                      textAlign: 'left',
                      justifyContent: 'flex-start',
                      height: 'auto',
                      padding: '14px 18px',
                      lineHeight: 1.5,
                    }}
                  >
                    {q}
                  </Button>
                ))}
              </Box>
            </Card>
          </Box>
        )}

        {messages.map((message, index) => {
          const confidence = extractConfidence(message.content)
          const statistics = message.role === 'assistant' ? extractStatistics(message.content) : null
          const hasSources = message.sources && message.sources.length > 0
          
          // Check if this is the streaming message
          const isStreamingMessage = currentStreamingMessageRef.current === index && isWebSocketStreaming && !!streamingContent
          const displayContent = isStreamingMessage ? streamingContent : message.content
          const displaySources = isStreamingMessage ? streamingSources : (message.sources || [])

          return (
            <Flex
              key={index}
              className={`message ${message.role === 'user' ? 'message-user' : 'message-assistant'}`}
              role="article"
              aria-label={message.role === 'user' ? 'Сообщение пользователя' : 'Ответ ассистента'}
              align="start"
              gap="3"
              style={{
                width: '100%',
                marginBottom: '24px',
                justifyContent: message.role === 'user' ? 'flex-end' : 'flex-start',
              }}
            >
              {message.role === 'assistant' && (
                <Box 
                  className="message-avatar assistant-avatar"
                  style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '8px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '13px',
                    fontWeight: 600,
                    flexShrink: 0,
                    marginTop: '2px',
                    background: 'linear-gradient(135deg, #00D4FF 0%, #00B8E6 100%)',
                    color: '#0F0F23',
                  }}
                >
                  AI
                </Box>
              )}
              {message.role === 'assistant' ? (
                <Card
                  className={`message-bubble assistant`}
                  style={{
                    maxWidth: '768px',
                    padding: '20px 24px',
                    borderRadius: '16px',
                    backgroundColor: 'var(--color-message-assistant)',
                    boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)',
                  }}
                >
                  <Text className="message-text" style={{ fontSize: '16px', lineHeight: 1.75, color: 'inherit', fontWeight: 400 }}>
                    <MessageContent
                      content={displayContent}
                      sources={displaySources}
                      onCitationClick={handleCitationClick}
                      isStreaming={isStreamingMessage}
                    />
                  </Text>
                  
                  {statistics && (
                    <Box style={{ marginTop: '16px' }}>
                      <StatisticsChart data={statistics} />
                    </Box>
                  )}
                  
                  {confidence !== null && (
                    <Flex align="center" gap="2" style={{ marginTop: '8px' }}>
                      <Text size="1" color="gray">Уверенность: </Text>
                      <ConfidenceBadge confidence={confidence} />
                    </Flex>
                  )}
                </Card>
              ) : (
                <Box
                  className={`message-bubble user`}
                  style={{
                    maxWidth: '85%',
                    padding: '12px 16px',
                    borderRadius: '18px 18px 4px 18px',
                    marginLeft: 'auto',
                    backgroundColor: 'var(--color-message-user)',
                    color: '#0F0F23',
                    fontWeight: 400,
                  }}
                >
                  <Text style={{ fontSize: '16px', lineHeight: 1.75 }}>
                    {message.content}
                  </Text>
                </Box>
              )}
              {message.role === 'user' && (
                <Box 
                  className="message-avatar user-avatar"
                  style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '8px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '13px',
                    fontWeight: 600,
                    flexShrink: 0,
                    marginTop: '2px',
                    backgroundColor: 'var(--color-border)',
                    color: 'var(--color-text)',
                  }}
                >
                  You
                </Box>
              )}
            </Flex>
          )
        })}

        {isLoading && !isWebSocketStreaming && currentStreamingMessageRef.current === null && (
          <Flex
            className="message message-assistant"
            role="status"
            aria-live="polite"
            align="start"
            gap="3"
            style={{
              width: '100%',
              marginBottom: '24px',
              justifyContent: 'flex-start',
            }}
          >
            <Box 
              className="message-avatar assistant-avatar"
              aria-hidden="true"
              style={{
                width: '32px',
                height: '32px',
                borderRadius: '8px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '13px',
                fontWeight: 600,
                flexShrink: 0,
                marginTop: '2px',
                background: 'linear-gradient(135deg, #00D4FF 0%, #00B8E6 100%)',
                color: '#0F0F23',
              }}
            >
              AI
            </Box>
            <Card
              className="message-bubble assistant loading-bubble"
              style={{
                padding: '20px 24px',
                borderRadius: '16px',
                backgroundColor: 'var(--color-message-assistant)',
              }}
            >
              <Box className="typing-indicator" aria-label="Генерация ответа" style={{ display: 'flex', gap: '4px' }}>
                <Box className="typing-dot" style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', animation: 'typingPulse 1.4s ease-in-out infinite' }}></Box>
                <Box className="typing-dot" style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', animation: 'typingPulse 1.4s ease-in-out infinite 0.2s' }}></Box>
                <Box className="typing-dot" style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', animation: 'typingPulse 1.4s ease-in-out infinite 0.4s' }}></Box>
              </Box>
            </Card>
          </Flex>
        )}

        {error && <div className="error-message">{error}</div>}

        <div ref={messagesEndRef} />
        </Box>
      </Box>

      <Box 
        className="chat-input-area"
        style={{
          position: 'fixed',
          bottom: 0,
          left: '260px',
          right: 0,
          backgroundColor: 'var(--color-bg)',
          borderTop: '1px solid var(--color-border)',
          padding: '24px 0',
          zIndex: 100,
          transition: 'left 0.3s ease',
        }}
      >
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
        <Box 
          className="chat-input-wrapper"
          style={{
            maxWidth: '768px',
            width: '100%',
            margin: '0 auto',
            padding: '0 24px',
            boxSizing: 'border-box',
          }}
        >
          <Flex
            className="chat-input-main"
            align="center"
            gap="3"
            style={{
              backgroundColor: 'var(--color-surface)',
              border: '1.5px solid var(--color-border)',
              borderRadius: '26px',
              padding: '12px 16px',
              minHeight: '52px',
              width: '100%',
              boxSizing: 'border-box',
            }}
          >
            <Box 
              className="chat-input-container"
              style={{
                position: 'relative',
                flex: 1,
                minWidth: 0,
                display: 'flex',
                alignItems: 'center',
              }}
            >
              <TextArea
                ref={textareaRef}
                placeholder={PLACEHOLDERS[currentPlaceholderIndex]}
                value={inputValue}
                onChange={handleTextareaChange}
                onKeyDown={handleKeyDown}
                disabled={isLoading}
                resize="none"
                style={{
                  minHeight: '24px',
                  maxHeight: '200px',
                  lineHeight: 1.5,
                  width: '100%',
                  minWidth: 0,
                  border: 'none',
                  background: 'transparent',
                  padding: 0,
                  fontSize: '16px',
                  fontFamily: 'inherit',
                  outline: 'none',
                }}
                aria-label="Введите сообщение"
                aria-describedby="input-help"
              />
              <Autocomplete
                suggestions={autocompleteSuggestions}
                selectedIndex={autocompleteSelectedIndex}
                onSelect={handleAutocompleteSelect}
                visible={autocompleteVisible}
              />
            </Box>
            <Flex className="chat-input-actions" align="center" gap="2" style={{ flexShrink: 0 }}>
              {/* Pro Search Toggle */}
              <Button
                variant="soft"
                size="2"
                onClick={() => setProSearchEnabled(!proSearchEnabled)}
                className={proSearchEnabled ? 'active' : ''}
                title="Глубокий поиск (Pro)"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '6px 12px',
                  backgroundColor: proSearchEnabled ? 'rgba(255, 193, 7, 0.25)' : 'rgba(255, 193, 7, 0.12)',
                  borderColor: proSearchEnabled ? '#FFC107' : 'rgba(255, 193, 7, 0.25)',
                  color: '#FFC107',
                  fontSize: '12px',
                }}
              >
                <Box 
                  className="pro-search-badge"
                  style={{
                    width: '5px',
                    height: '5px',
                    borderRadius: '50%',
                    background: '#FFC107',
                    boxShadow: '0 0 3px rgba(255, 193, 7, 0.6)',
                    flexShrink: 0,
                  }}
                />
                <Text size="2">Pro Search</Text>
              </Button>
              
              <input
                type="file"
                id="chat-file-input"
                multiple
                accept=".pdf,.docx,.txt,.xlsx"
                onChange={handleFileInput}
                style={{ display: 'none' }}
              />
              <IconButton
                asChild
                variant="ghost"
                size="2"
                title="Прикрепить файл"
              >
                <label htmlFor="chat-file-input" style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <Paperclip size={20} />
                </label>
              </IconButton>
              <IconButton
                variant="solid"
                size="2"
                onClick={(e) => {
                  e.preventDefault()
                  handleSend()
                }}
                disabled={isLoading || !inputValue.trim() || isOverLimit}
                title="Отправить (Enter)"
                aria-label="Отправить сообщение"
                style={{
                  backgroundColor: 'var(--color-primary)',
                  color: '#0F0F23',
                  width: '32px',
                  height: '32px',
                }}
              >
                <Send size={16} />
              </IconButton>
            </Flex>
          </Flex>
        </Box>
      </Box>
    </Box>
  )
}

export default ChatWindow

