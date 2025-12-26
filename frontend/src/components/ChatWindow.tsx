import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Send, Paperclip } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import './ChatWindow.css'
import './Chat/Chat.css'
import { fetchHistory, sendMessage, SourceInfo, HistoryMessage, classifyDocuments, extractEntities, getTimeline, getAnalysisReport } from '../services/api'
import { useWebSocketChat } from '../hooks/useWebSocketChat'
import ConfidenceBadge from './Common/ConfidenceBadge'
import MessageContent from './Chat/MessageContent'
import Autocomplete from './Chat/Autocomplete'
import StatisticsChart from './Chat/StatisticsChart'
import SourceSelector, { DEFAULT_SOURCES } from './Chat/SourceSelector'
import { Button } from '@/components/UI/Button'
import { Card, CardContent } from '@/components/UI/Card'
import { Textarea } from '@/components/UI/Textarea'
import { Avatar, AvatarFallback } from '@/components/UI/avatar'
import { Badge } from '@/components/UI/Badge'
import { Separator } from '@/components/UI/separator'
import { ScrollArea } from '@/components/UI/scroll-area'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/UI/tooltip'
import { Alert, AlertDescription, AlertTitle } from '@/components/UI/alert'
import { Skeleton } from '@/components/UI/Skeleton'
import { cn } from '@/lib/utils'
import { logger } from '@/lib/logger'

interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: SourceInfo[]
}

interface ChatWindowProps {
  caseId: string
  fileNames?: string[]
  onDocumentClick?: (filename: string) => void
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
  
  const PLACEHOLDERS = [
    'Задайте вопрос...',
    'Объясни как 5-летнему...',
    'Сравни документы...',
    'Найди противоречия...',
    'Что говорит договор о...',
    'Какие сроки важны...',
  ]
  const [currentPlaceholderIndex, setCurrentPlaceholderIndex] = useState(0)
  const [proSearchEnabled] = useState(false)
  const [selectedSources, setSelectedSources] = useState<string[]>(['vault'])

  const { isConnected, isStreaming: isWebSocketStreaming, sendMessage: sendWebSocketMessage } = useWebSocketChat({
    caseId,
    onMessage: (content: string) => {
      setStreamingContent(prev => prev + content)
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
        setMessages(prev => prev.filter((_, idx) => idx !== currentStreamingMessageRef.current))
        currentStreamingMessageRef.current = null
      }
    },
    onComplete: () => {
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

  useEffect(() => {
    if (inputValue) return
    const interval = setInterval(() => {
      setCurrentPlaceholderIndex((prev) => (prev + 1) % PLACEHOLDERS.length)
    }, 3000)
    return () => clearInterval(interval)
  }, [inputValue])

  useEffect(() => {
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

  const isSourceInfo = (source: string | SourceInfo): source is SourceInfo => {
    return typeof source === 'object' && source !== null && 'file' in source
  }

  const hasSourceInfo = (sources: (string | SourceInfo)[] | undefined): sources is SourceInfo[] => {
    if (!sources || sources.length === 0) return false
    return sources.every(s => isSourceInfo(s))
  }

  const normalizeSources = (sources: (string | SourceInfo)[] | undefined): SourceInfo[] => {
    if (!sources || sources.length === 0) return []
    if (hasSourceInfo(sources)) {
      return sources
    }
    return sources.map((s): SourceInfo => {
      if (isSourceInfo(s)) {
        return s
      }
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
      logger.error('Ошибка при загрузке истории:', err)
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

    setTimeout(() => {
      scrollToBottom()
    }, 150)
    
    setIsLoading(true)
    setStreamingContent('')
    setStreamingSources([])

    if (isConnected) {
      const assistantMessage: Message = {
        role: 'assistant',
        content: '',
        sources: [],
      }
      const messageIndex = messages.length
      setMessages(prev => [...prev, assistantMessage])
      currentStreamingMessageRef.current = messageIndex
      
      const history = messages.map(m => ({ role: m.role, content: m.content }))
      sendWebSocketMessage(trimmed, history, proSearchEnabled)
    } else {
    try {
      const response = await sendMessage(caseId, userMessage.content)
      if (response.status === 'success' || response.status === 'task_planned') {
      const assistantMessage: Message = {
        role: 'assistant',
        content: response.answer,
        sources: response.sources || [],
      }
      setMessages((prev) => [...prev, assistantMessage])
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
    
    const textarea = e.target
    textarea.style.height = '24px'
    const newHeight = Math.min(Math.max(textarea.scrollHeight, 24), 200)
    textarea.style.height = `${newHeight}px`
    
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

  // Removed unused handlers - QuickButtons component was removed
  // These functions are kept for potential future use
  // @ts-expect-error - Unused but kept for future use
  const _handleClassifyAll = async () => {
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

  // @ts-expect-error - Unused but kept for future use
  const _handleFindPrivilege = async () => {
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

  // @ts-expect-error - Unused but kept for future use
  const _handleTimeline = async () => {
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

  // @ts-expect-error - Unused but kept for future use
  const _handleStatistics = async () => {
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

  // @ts-expect-error - Unused but kept for future use
  const _handleExtractEntities = async () => {
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
      navigate(`/cases/${caseId}/workspace`)
    }
  }

  const extractConfidence = (content: string): number | null => {
    const match = content.match(/(\d+)%?\s*(?:confidence|уверенность|conf)/i)
    if (match) {
      return parseInt(match[1])
    }
    return null
  }

  const extractStatistics = (content: string): { type: 'bar' | 'pie', title?: string, data: Array<{ name: string, value: number }> } | null => {
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

    if (data.length > 0) {
      return {
        type: data.length <= 5 ? 'pie' : 'bar',
        title: 'Статистика',
        data: data.slice(0, 10)
      }
    }

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
    <TooltipProvider>
      <div 
        className={cn("chat-container flex flex-col h-screen relative overflow-hidden", isDragging && "dragging")}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
        style={{ backgroundColor: 'var(--color-bg)' }}
      >
        <AnimatePresence>
      {isDragging && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 z-50 flex items-center justify-center bg-primary/10 border-2 border-dashed border-primary rounded-lg"
            >
              <Card className="p-8 text-center">
                <CardContent className="pt-6">
                  <div className="text-5xl mb-4">📎</div>
                  <h3 className="text-xl font-semibold mb-2">Перетащите файлы сюда</h3>
                  <p className="text-muted-foreground">PDF, DOCX, TXT, XLSX</p>
                </CardContent>
              </Card>
            </motion.div>
          )}
        </AnimatePresence>


        <ScrollArea className="flex-1 w-full">
          <div className="w-full max-w-3xl mx-auto px-6 py-20 pb-40 flex flex-col items-center">
        {historyError && (
              <Alert variant="destructive" className="mb-4">
                <AlertTitle>Ошибка</AlertTitle>
                <AlertDescription className="flex items-center justify-between">
                  <span>{historyError}</span>
                  <Button variant="outline" size="sm" onClick={loadHistory}>
              Обновить
                  </Button>
                </AlertDescription>
              </Alert>
        )}

            {!hasMessages && !isLoading && !historyError && (
              <div className="flex justify-center items-center min-h-[60vh] py-10 w-full">
                <Card className="max-w-2xl w-full mx-auto">
                  <CardContent className="pt-6 text-center px-6">
                    <Avatar className="h-20 w-20 mx-auto mb-6 bg-gradient-to-br from-primary to-primary/60">
                      <AvatarFallback className="text-3xl">⚖️</AvatarFallback>
                    </Avatar>
                    <h2 className="text-3xl font-bold mb-3">Legal AI</h2>
                    <p className="text-muted-foreground mb-8 text-lg leading-relaxed px-4">
                      Задайте вопрос по загруженным документам. AI проанализирует контракты, переписку и таблицы.
                    </p>
                    <Separator className="my-6" />
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-w-2xl mx-auto">
                      {RECOMMENDED_QUESTIONS.map((q, idx) => (
                        <Button
                          key={idx}
                          variant="outline"
                          className="h-auto py-4 px-4 text-left justify-start hover:bg-accent transition-colors break-words whitespace-normal"
                          onClick={() => handleRecommendedClick(q)}
                        >
                          <span className="break-words">{q}</span>
                        </Button>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}

            <AnimatePresence>
        {messages.map((message, index) => {
          const confidence = extractConfidence(message.content)
          const statistics = message.role === 'assistant' ? extractStatistics(message.content) : null
          const isStreamingMessage = currentStreamingMessageRef.current === index && isWebSocketStreaming && !!streamingContent
          const displayContent = isStreamingMessage ? streamingContent : message.content
          const displaySources = isStreamingMessage ? streamingSources : (message.sources || [])
          const isAssistant = message.role === 'assistant'

          return (
                  <motion.div
              key={index}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.3 }}
                    className={cn(
                      "flex items-start gap-3 mb-6 w-full max-w-3xl",
                      message.role === 'user' ? 'justify-end ml-auto' : 'justify-start mr-auto'
                    )}
            >
                    {isAssistant && (
                      <Avatar className="h-8 w-8 shrink-0 bg-gradient-to-br from-primary to-primary/60">
                        <AvatarFallback className="text-xs font-semibold">⚖️</AvatarFallback>
                      </Avatar>
                    )}

              <div className={cn(
                "max-w-[85%] flex-1 sm:max-w-[75%]",
                message.role === 'user' && 'flex items-end gap-3'
              )}>
                {isAssistant ? (
                      <div className="bg-secondary text-foreground rounded-lg p-4 prose prose-sm max-w-none">
                    <MessageContent
                      content={displayContent}
                      sources={displaySources}
                      onCitationClick={handleCitationClick}
                      isStreaming={isStreamingMessage}
                    />
                  
                  {statistics && (
                            <div className="mt-4">
                      <StatisticsChart data={statistics} />
                            </div>
                  )}
                  
                  {confidence !== null && (
                            <div className="flex items-center gap-2 mt-3">
                              <span className="text-xs text-muted-foreground">Уверенность:</span>
                      <ConfidenceBadge confidence={confidence} />
                            </div>
                  )}
                      </div>
                ) : (
                        <div className="bg-primary text-primary-foreground rounded-lg px-4 py-3 shadow-sm">
                          <p className="text-base leading-relaxed whitespace-pre-wrap">{message.content}</p>
                        </div>
                    )}
              </div>

                    {message.role === 'user' && (
                      <Avatar className="h-8 w-8 shrink-0 bg-muted">
                        <AvatarFallback className="text-xs font-semibold">👤</AvatarFallback>
                      </Avatar>
                    )}
                  </motion.div>
                )
              })}
            </AnimatePresence>

        {isLoading && !isWebSocketStreaming && currentStreamingMessageRef.current === null && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-start gap-3 mb-6"
              >
                <Avatar className="h-8 w-8 shrink-0 bg-gradient-to-br from-primary to-primary/60">
                  <AvatarFallback className="text-xs font-semibold">⚖️</AvatarFallback>
                </Avatar>
                <Card className="bg-card border shadow-sm">
                  <CardContent className="p-5">
                    <div className="flex gap-2">
                      <Skeleton className="h-2 w-2 rounded-full" />
                      <Skeleton className="h-2 w-2 rounded-full" />
                      <Skeleton className="h-2 w-2 rounded-full" />
                    </div>
                  </CardContent>
            </Card>
              </motion.div>
            )}

            {error && (
              <Alert variant="destructive" className="mb-4">
                <AlertTitle>Ошибка</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

        <div ref={messagesEndRef} />
          </div>
        </ScrollArea>

        <div 
          className="fixed bottom-0 left-[260px] right-0 bg-background border-t z-50 transition-all duration-300 flex justify-center"
          style={{ backgroundColor: 'var(--color-bg)', borderColor: 'var(--color-border)' }}
        >
          {droppedFiles.length > 0 && (
            <div className="flex flex-wrap gap-2 p-3 border-b bg-muted/50 w-full max-w-3xl mx-auto">
              {droppedFiles.map((file, index) => (
                <Badge key={index} variant="secondary" className="gap-2">
                  <Paperclip className="h-3 w-3" />
                  <span>{file.name}</span>
                  <button
                    type="button"
                    onClick={() => setDroppedFiles(prev => prev.filter((_, i) => i !== index))}
                    className="ml-1 hover:text-destructive"
                    aria-label="Удалить файл"
                  >
                    ×
                  </button>
                </Badge>
              ))}
            </div>
          )}
          
          <div className="w-full max-w-3xl mx-auto px-6 py-6">
            <Card className="border-2 shadow-lg">
              <CardContent className="p-4">
                {/* Source selector above input */}
                <div className="mb-3 pb-3 border-b">
                  <SourceSelector
                    sources={DEFAULT_SOURCES}
                    selectedSources={selectedSources}
                    onSourcesChange={setSelectedSources}
                  />
                </div>
                
                <div className="flex items-end gap-3">
                  <div className="relative flex-1">
                    <Textarea
                ref={textareaRef}
                placeholder={PLACEHOLDERS[currentPlaceholderIndex]}
                value={inputValue}
                onChange={handleTextareaChange}
                onKeyDown={handleKeyDown}
                      disabled={isLoading || isWebSocketStreaming}
                      className="min-h-[24px] max-h-[200px] resize-none border-0 focus-visible:ring-0 focus-visible:ring-offset-0 bg-transparent"
                style={{
                        height: 'auto',
                      }}
              />
              <Autocomplete
                suggestions={autocompleteSuggestions}
                selectedIndex={autocompleteSelectedIndex}
                onSelect={handleAutocompleteSelect}
                visible={autocompleteVisible}
              />
                  </div>
                  
                  <div className="flex items-center gap-2 shrink-0">
              <input
                type="file"
                id="chat-file-input"
                multiple
                accept=".pdf,.docx,.txt,.xlsx"
                onChange={handleFileInput}
                      className="hidden"
              />
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                variant="ghost"
                          size="icon"
                          asChild
              >
                          <label htmlFor="chat-file-input" className="cursor-pointer">
                            <Paperclip className="h-5 w-5" />
                </label>
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Прикрепить файл</TooltipContent>
                    </Tooltip>
                    
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          size="icon"
                          onClick={(e: React.MouseEvent) => {
                  e.preventDefault()
                  handleSend()
                }}
                          disabled={isLoading || !inputValue.trim() || isOverLimit || isWebSocketStreaming}
                          className="bg-primary hover:bg-primary/90"
                        >
                          <Send className="h-4 w-4" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Отправить (Enter)</TooltipContent>
                    </Tooltip>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </TooltipProvider>
  )
}

export default ChatWindow
