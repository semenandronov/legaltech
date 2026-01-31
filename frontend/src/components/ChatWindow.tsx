import { useState, useEffect, useRef } from 'react'
import {
  Box,
  TextField,
  IconButton,
  Button,
  Avatar,
  Chip,
  Paper,
  Typography,
  Alert,
  AlertTitle,
  Divider,
  Tooltip,
  Fade,
  Skeleton,
  Stack,
  Grid,
  Card,
  CardContent,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material'
import {
  Send as SendIcon,
  AttachFile as PaperclipIcon,
  AutoAwesome as SparklesIcon,
  Settings as SettingsIcon,
  MenuBook as BookOpenIcon,
  AutoFixHigh as WandIcon,
  Search as SearchIcon,
  ChevronRight as ChevronRightIcon,
  Close as CloseIcon,
  History as HistoryIcon,
} from '@mui/icons-material'
import { FormControlLabel, Switch, Stepper, Step, StepLabel } from '@mui/material'
import './ChatWindow.css'
import './Chat/Chat.css'
import { fetchHistory, sendMessage, SourceInfo, HistoryMessage, classifyDocuments, extractEntities, getTimeline, getAnalysisReport } from '../services/api'
import { useWebSocketChat } from '../hooks/useWebSocketChat'
import ConfidenceBadge from './Common/ConfidenceBadge'
import MessageContent from './Chat/MessageContent'
import Autocomplete from './Chat/Autocomplete'
import StatisticsChart from './Chat/StatisticsChart'
import SourceSelector, { DEFAULT_SOURCES } from './Chat/SourceSelector'
import DocumentPreviewSheet from './Chat/DocumentPreviewSheet'
import { ChatHistoryPanel } from './Chat/ChatHistoryPanel'
import { WelcomeScreen } from './Chat/WelcomeScreen'
import { PromptLibrary } from './Chat/PromptLibrary'
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

const QUICK_PROMPTS: Array<{ id: string; label: string; prompt: string }> = [
  { id: 'summarize', label: 'Краткое изложение', prompt: 'Сформулируй краткий обзор этого дела' },
  { id: 'timeline', label: 'Хронология', prompt: 'Создай хронологию событий из документов' },
  { id: 'nda-review', label: 'NDA Review', prompt: 'Проведи обзор NDA и выдели ключевые условия' },
  { id: 'contradictions', label: 'Противоречия', prompt: 'Найди противоречия между документами' },
  { id: 'risks', label: 'Риски', prompt: 'Проанализируй риски в документах' },
  { id: 'entities', label: 'Сущности', prompt: 'Извлеки все важные сущности из документов' },
]

const COMMANDS = [
  { command: 'Классифицируй', full: 'Классифицируй все документы в деле' },
  { command: 'Найди привилегии', full: 'Найди все привилегированные документы' },
  { command: 'Таймлайн', full: 'Покажи таймлайн событий из документов' },
  { command: 'Статистика', full: 'Покажи статистику по делу' },
  { command: 'Извлеки сущности', full: 'Извлеки все сущности из документов' },
]

const PLACEHOLDERS = [
  'Спросите что угодно...',
  'Сравни документы...',
  'Найди противоречия...',
  'Что говорит договор о...',
  'Какие сроки важны...',
]

const ChatWindow = ({ caseId, onDocumentClick }: ChatWindowProps) => {
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
  const [currentPlaceholderIndex, setCurrentPlaceholderIndex] = useState(0)
  const [proSearchEnabled] = useState(false)
  const [selectedSources, setSelectedSources] = useState<string[]>(['vault'])
  const [deepThinkEnabled, setDeepThinkEnabled] = useState(false)
  const [searchPlanSteps] = useState<Array<{ label: string; completed: boolean }>>([])
  const [historyPanelOpen, setHistoryPanelOpen] = useState(false)
  const [promptLibraryOpen, setPromptLibraryOpen] = useState(false)
  const [responseSettingsOpen, setResponseSettingsOpen] = useState(false)
  
  // Document preview state
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewSource, setPreviewSource] = useState<SourceInfo | null>(null)
  const [allCurrentSources, setAllCurrentSources] = useState<SourceInfo[]>([])
  
  // Recommended workflows (Harvey style)
  const WORKFLOWS = [
    { id: 'timeline', icon: '📅', title: 'Хронология событий', description: 'Извлечь ключевые даты', steps: 2 },
    { id: 'summary', icon: '📋', title: 'Краткое изложение', description: 'Сводка по делу', steps: 3 },
    { id: 'risks', icon: '⚠️', title: 'Анализ рисков', description: 'Найти проблемы', steps: 4 },
    { id: 'compare', icon: '🔄', title: 'Сравнить документы', description: 'Найти расхождения', steps: 2 },
  ]

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
    setInputValue('')
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
      sendWebSocketMessage(trimmed, history, proSearchEnabled, deepThinkEnabled)
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


  const handleTextareaChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const value = e.target.value
    setInputValue(value)
    
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

    setDroppedFiles(files)
    
    try {
      setIsLoading(true)
      const fileNames = files.map(f => f.name).join(', ')
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

    setDroppedFiles(files)
    
    try {
      setIsLoading(true)
      const fileNames = files.map(f => f.name).join(', ')
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

  // REMOVED: 5 неиспользуемых функций-обработчиков (95 строк) - QuickButtons component был удален

  const handleCitationClick = (source: SourceInfo) => {
    // Open document preview sheet
    setPreviewSource(source)
    // Collect all sources from messages for navigation
    const allSources: SourceInfo[] = messages
      .filter(m => m.role === 'assistant' && m.sources)
      .flatMap(m => (m.sources || []) as SourceInfo[])
    setAllCurrentSources(allSources)
    setPreviewOpen(true)
    
    // Also call external handler if provided
    if (onDocumentClick) {
      onDocumentClick(source.file)
    }
  }
  
  const handleWorkflowClick = (workflowId: string) => {
    const workflowQuestions: Record<string, string> = {
      'timeline': 'Построй хронологию всех ключевых событий из документов дела',
      'summary': 'Сделай краткое изложение дела на основе всех документов',
      'risks': 'Проанализируй риски и найди потенциальные проблемы в документах',
      'compare': 'Сравни все документы и найди расхождения или противоречия',
    }
    const question = workflowQuestions[workflowId]
    if (question) {
      handleSend(question)
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
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        position: 'relative',
        overflow: 'hidden',
        bgcolor: 'background.default',
      }}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {isDragging && (
        <Fade in={isDragging}>
          <Box
            sx={{
              position: 'absolute',
              inset: 0,
              zIndex: 1300,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              bgcolor: 'primary.main',
              opacity: 0.1,
              border: '2px dashed',
              borderColor: 'primary.main',
              borderRadius: 2,
            }}
          >
            <Card sx={{ p: 4, textAlign: 'center' }}>
              <CardContent>
                <Typography variant="h2" sx={{ mb: 2 }}>
                  📎
                </Typography>
                <Typography variant="h6" sx={{ mb: 1, fontWeight: 600 }}>
                  Перетащите файлы сюда
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  PDF, DOCX, TXT, XLSX
                </Typography>
              </CardContent>
            </Card>
          </Box>
        </Fade>
      )}


      <Box
        sx={{
          flex: 1,
          overflow: 'auto',
          width: '100%',
        }}
      >
        <Box
          sx={{
            width: '100%',
            maxWidth: '900px',
            mx: 'auto',
            px: 3,
            py: 5,
            pb: 10,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
          }}
        >
          {historyError && (
            <Alert 
              severity="error" 
              sx={{ mb: 2, width: '100%' }}
              action={
                <Button color="inherit" size="small" onClick={loadHistory}>
                  Обновить
                </Button>
              }
            >
              <AlertTitle>Ошибка</AlertTitle>
              {historyError}
            </Alert>
          )}

          {!hasMessages && !isLoading && !historyError && (
            <WelcomeScreen
              onQuickAction={(prompt) => {
                setInputValue(prompt)
                handleSend(prompt)
              }}
            />
          )}

          {/* Legacy welcome screen - keeping for reference but replaced by WelcomeScreen */}
          {false && !hasMessages && !isLoading && !historyError && (
            <Box
              sx={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                minHeight: '50vh',
                py: 4,
                width: '100%',
              }}
            >
              {/* Harvey-style welcome */}
              <Box sx={{ textAlign: 'center', mb: 5 }}>
                <Typography
                  variant="h2"
                  sx={{
                    mb: 2,
                    fontWeight: 700,
                    background: 'linear-gradient(135deg, #3B82F6 0%, #8B5CF6 50%, #EC4899 100%)',
                    backgroundClip: 'text',
                    WebkitBackgroundClip: 'text',
                    WebkitTextFillColor: 'transparent',
                  }}
                >
                  Legal AI Assistant
                </Typography>
                <Typography variant="body1" color="text.secondary">
                  Ваш интеллектуальный помощник для работы с документами
                </Typography>
              </Box>

              {/* Recommended workflows - Harvey style */}
              <Box sx={{ width: '100%', maxWidth: '900px', mb: 4 }}>
                <Box
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    mb: 2,
                  }}
                >
                  <Typography variant="body2" fontWeight={500} color="text.secondary">
                    Рекомендуемые процессы
                  </Typography>
                  <Button
                    variant="text"
                    size="small"
                    endIcon={<ChevronRightIcon fontSize="small" />}
                    sx={{ textTransform: 'none', fontSize: '0.75rem' }}
                  >
                    Все
                  </Button>
                </Box>
                <Grid container spacing={2}>
                  {WORKFLOWS.map((workflow) => (
                    <Grid item xs={6} sm={3} key={workflow.id}>
                      <Card
                        component="button"
                        onClick={() => handleWorkflowClick(workflow.id)}
                        sx={{
                          p: 2,
                          textAlign: 'left',
                          cursor: 'pointer',
                          border: '1px solid',
                          borderColor: 'divider',
                          '&:hover': {
                            borderColor: 'primary.main',
                            boxShadow: 2,
                            bgcolor: 'action.hover',
                          },
                        }}
                      >
                        <Typography variant="h4" sx={{ mb: 1 }}>
                          {workflow.icon}
                        </Typography>
                        <Typography variant="body2" fontWeight={500} sx={{ mb: 0.5 }}>
                          {workflow.title}
                        </Typography>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <SearchIcon sx={{ fontSize: 12, opacity: 0.6 }} />
                          <Typography variant="caption" color="text.secondary">
                            {workflow.steps} шага
                          </Typography>
                        </Box>
                      </Card>
                    </Grid>
                  ))}
                </Grid>
              </Box>

              {/* Quick questions */}
              <Box sx={{ width: '100%', maxWidth: '900px' }}>
                <Typography variant="body2" fontWeight={500} color="text.secondary" sx={{ mb: 2 }}>
                  Быстрые вопросы
                </Typography>
                <Grid container spacing={1}>
                  {RECOMMENDED_QUESTIONS.map((q, idx) => (
                    <Grid item xs={12} md={6} key={idx}>
                      <Button
                        variant="outlined"
                        fullWidth
                        onClick={() => handleRecommendedClick(q)}
                        sx={{
                          textAlign: 'left',
                          justifyContent: 'flex-start',
                          textTransform: 'none',
                          py: 1.5,
                          px: 2,
                          whiteSpace: 'normal',
                          '&:hover': {
                            borderColor: 'primary.main',
                            bgcolor: 'action.hover',
                          },
                        }}
                      >
                        {q}
                      </Button>
                    </Grid>
                  ))}
                </Grid>
              </Box>
            </Box>
          )}

          {messages.map((message, index) => {
            const confidence = extractConfidence(message.content)
            const statistics = message.role === 'assistant' ? extractStatistics(message.content) : null
            const isStreamingMessage = currentStreamingMessageRef.current === index && isWebSocketStreaming && !!streamingContent
            const displayContent = isStreamingMessage ? streamingContent : message.content
            const displaySources = isStreamingMessage ? streamingSources : (message.sources || [])
            const isAssistant = message.role === 'assistant'

            return (
              <Fade in timeout={300} key={index}>
                <Box
                  sx={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 1.5,
                    mb: 3,
                    width: '100%',
                    justifyContent: message.role === 'user' ? 'flex-end' : 'flex-start',
                  }}
                >
                  {isAssistant && (
                    <Avatar
                      sx={{
                        width: 32,
                        height: 32,
                        bgcolor: 'primary.main',
                        flexShrink: 0,
                      }}
                    >
                      ⚖️
                    </Avatar>
                  )}

                  <Box
                    sx={{
                      maxWidth: { xs: '85%', sm: '75%' },
                      display: 'flex',
                      flexDirection: message.role === 'user' ? 'row' : 'column',
                      alignItems: message.role === 'user' ? 'flex-end' : 'flex-start',
                      gap: message.role === 'user' ? 1.5 : 0,
                    }}
                  >
                    {isAssistant ? (
                      <Paper
                        elevation={0}
                        sx={{
                          p: 2,
                          bgcolor: 'background.paper',
                          borderRadius: 2,
                          maxWidth: '100%',
                        }}
                      >
                        <MessageContent
                          content={displayContent}
                          sources={displaySources}
                          onCitationClick={handleCitationClick}
                          isStreaming={isStreamingMessage}
                        />

                        {statistics && (
                          <Box sx={{ mt: 2 }}>
                            <StatisticsChart data={statistics} />
                          </Box>
                        )}

                        {confidence !== null && (
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 2 }}>
                            <Typography variant="caption" color="text.secondary">
                              Уверенность:
                            </Typography>
                            <ConfidenceBadge confidence={confidence} />
                          </Box>
                        )}
                      </Paper>
                    ) : (
                      <Paper
                        elevation={0}
                        sx={{
                          px: 2,
                          py: 1.5,
                          bgcolor: 'primary.main',
                          color: 'primary.contrastText',
                          borderRadius: 2,
                        }}
                      >
                        <Typography
                          variant="body1"
                          sx={{
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                          }}
                        >
                          {message.content}
                        </Typography>
                      </Paper>
                    )}
                  </Box>

                  {message.role === 'user' && (
                    <Avatar
                      sx={{
                        width: 32,
                        height: 32,
                        bgcolor: 'grey.300',
                        flexShrink: 0,
                      }}
                    >
                      👤
                    </Avatar>
                  )}
                </Box>
              </Fade>
            )
          })}

          {isLoading && !isWebSocketStreaming && currentStreamingMessageRef.current === null && (
            <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5, mb: 3 }}>
              <Avatar
                sx={{
                  width: 32,
                  height: 32,
                  bgcolor: 'primary.main',
                  flexShrink: 0,
                }}
              >
                ⚖️
              </Avatar>
              <Card sx={{ bgcolor: 'background.paper' }}>
                <CardContent sx={{ p: 3 }}>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Skeleton variant="circular" width={8} height={8} />
                    <Skeleton variant="circular" width={8} height={8} />
                    <Skeleton variant="circular" width={8} height={8} />
                  </Box>
                </CardContent>
              </Card>
            </Box>
          )}

          {error && (
            <Alert severity="error" sx={{ mb: 2, width: '100%' }}>
              <AlertTitle>Ошибка</AlertTitle>
              {error}
            </Alert>
          )}

          <div ref={messagesEndRef} />
        </Box>
      </Box>

      <Box
        sx={{
          position: 'fixed',
          bottom: 0,
          left: { xs: 0, md: '280px' },
          right: 0,
          bgcolor: 'background.default',
          borderTop: '1px solid',
          borderColor: 'divider',
          zIndex: 1000,
          display: 'flex',
          justifyContent: 'center',
          transition: 'all 0.3s',
        }}
      >
        {droppedFiles.length > 0 && (
          <Box
            sx={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 1,
              p: 1.5,
              borderBottom: '1px solid',
              borderColor: 'divider',
              bgcolor: 'action.hover',
              width: '100%',
              maxWidth: '900px',
            }}
          >
            {droppedFiles.map((file, index) => (
              <Chip
                key={index}
                icon={<PaperclipIcon />}
                label={file.name}
                onDelete={() => setDroppedFiles(prev => prev.filter((_, i) => i !== index))}
                deleteIcon={<CloseIcon />}
                variant="outlined"
                size="small"
              />
            ))}
          </Box>
        )}

        <Box
          sx={{
            width: '100%',
            maxWidth: '900px',
            px: 2,
            py: 2,
          }}
        >
          {/* Harvey-style input card */}
          <Card
            elevation={4}
            sx={{
              bgcolor: 'background.paper',
              backdropFilter: 'blur(10px)',
            }}
          >
            <CardContent sx={{ p: 0 }}>
              {/* Main input area */}
              <Box sx={{ p: 2 }}>
                <TextField
                  inputRef={textareaRef}
                  placeholder={PLACEHOLDERS[currentPlaceholderIndex]}
                  value={inputValue}
                  onChange={handleTextareaChange}
                  onKeyDown={(e) => {
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
                  }}
                  disabled={isLoading || isWebSocketStreaming}
                  multiline
                  maxRows={8}
                  fullWidth
                  variant="standard"
                  InputProps={{
                    disableUnderline: true,
                    sx: {
                      fontSize: '1rem',
                      minHeight: '60px',
                    },
                  }}
                  sx={{
                    '& .MuiInputBase-root': {
                      bgcolor: 'transparent',
                    },
                  }}
                />
                {autocompleteVisible && (
                  <Autocomplete
                    suggestions={autocompleteSuggestions}
                    selectedIndex={autocompleteSelectedIndex}
                    onSelect={handleAutocompleteSelect}
                    visible={autocompleteVisible}
                  />
                )}
              </Box>

              {/* Harvey-style toolbar */}
              <Divider />
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  px: 2,
                  py: 1.5,
                  bgcolor: 'action.hover',
                }}
              >
                {/* Left side - feature buttons */}
                <Stack direction="row" spacing={0.5} alignItems="center">
                  <input
                    type="file"
                    id="chat-file-input"
                    multiple
                    onChange={handleFileInput}
                    style={{ display: 'none' }}
                  />
                  <Tooltip title="Прикрепить файлы">
                    <label htmlFor="chat-file-input">
                      <IconButton
                        component="span"
                        size="small"
                        sx={{ textTransform: 'none' }}
                      >
                        <PaperclipIcon fontSize="small" />
                      </IconButton>
                    </label>
                  </Tooltip>

                  <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

                  <Tooltip title="История чатов">
                    <IconButton size="small" onClick={() => setHistoryPanelOpen(true)}>
                      <HistoryIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>

                  <Tooltip title="Библиотека промптов">
                    <IconButton size="small" onClick={() => setPromptLibraryOpen(true)}>
                      <BookOpenIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>

                  <Tooltip title="Настройки ответа">
                    <IconButton size="small" onClick={() => setResponseSettingsOpen(true)}>
                      <SettingsIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>

                  <Tooltip title="Улучшить промпт с AI">
                    <IconButton 
                      size="small" 
                      onClick={async () => {
                        if (!inputValue.trim()) return
                        try {
                          const apiModule = await import('@/services/api')
                          const apiClient = apiModule.default
                          const { getApiUrl } = apiModule
                          const response = await apiClient.post(getApiUrl('/api/chat/improve-prompt'), {
                            prompt: inputValue,
                          })
                          if (response.data?.improved) {
                            setInputValue(response.data.improved)
                          }
                        } catch (err: any) {
                          console.error('Error improving prompt:', err)
                        }
                      }}
                      disabled={!inputValue.trim()}
                    >
                      <WandIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>

                  <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

                  {/* Source selector inline */}
                  <SourceSelector
                    sources={DEFAULT_SOURCES}
                    selectedSources={selectedSources}
                    onSourcesChange={setSelectedSources}
                  />
                </Stack>

                {/* Right side - Deep Think toggle and send button */}
                <Stack direction="row" spacing={1} alignItems="center">
                  <FormControlLabel
                    control={
                      <Switch
                        size="small"
                        checked={deepThinkEnabled}
                        onChange={(e) => setDeepThinkEnabled(e.target.checked)}
                        icon={<SparklesIcon fontSize="small" />}
                        checkedIcon={<SparklesIcon fontSize="small" />}
                      />
                    }
                    label="Deep Think"
                    sx={{ mr: 1 }}
                  />

                  <Button
                    variant="contained"
                    onClick={(e) => {
                      e.preventDefault()
                      handleSend()
                    }}
                    disabled={isLoading || !inputValue.trim() || isOverLimit || isWebSocketStreaming}
                    startIcon={<SendIcon />}
                    sx={{ textTransform: 'none' }}
                  >
                    Спросить
                  </Button>
                </Stack>
              </Box>
            </CardContent>
          </Card>

          {/* Quick Prompts Carousel */}
          {!hasMessages && (
            <Box sx={{ px: 2, pb: 2 }}>
              <Box
                sx={{
                  display: 'flex',
                  gap: 1,
                  overflowX: 'auto',
                  scrollbarWidth: 'thin',
                  '&::-webkit-scrollbar': {
                    height: 6,
                  },
                  '&::-webkit-scrollbar-thumb': {
                    backgroundColor: 'action.disabled',
                    borderRadius: 3,
                  },
                  pb: 1,
                }}
              >
                {QUICK_PROMPTS.map((prompt) => (
                  <Chip
                    key={prompt.id}
                    label={prompt.label}
                    onClick={() => {
                      setInputValue(prompt.prompt)
                      handleSend(prompt.prompt)
                    }}
                    sx={{
                      cursor: 'pointer',
                      '&:hover': {
                        bgcolor: 'action.hover',
                      },
                    }}
                    size="small"
                  />
                ))}
              </Box>
            </Box>
          )}

          {/* Search Plan Visualization */}
          {searchPlanSteps.length > 0 && (
            <Box sx={{ px: 2, pb: 2 }}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  План поиска
                </Typography>
                <Stepper activeStep={searchPlanSteps.findIndex(s => !s.completed)} orientation="horizontal">
                  {searchPlanSteps.map((step, index) => (
                    <Step key={index} completed={step.completed}>
                      <StepLabel>{step.label}</StepLabel>
                    </Step>
                  ))}
                </Stepper>
              </Paper>
            </Box>
          )}
        </Box>
      </Box>

      {/* Document Preview Sheet */}
      <DocumentPreviewSheet
        isOpen={previewOpen}
        onClose={() => setPreviewOpen(false)}
        source={previewSource}
        caseId={caseId}
        allSources={allCurrentSources}
        onNavigate={(source: SourceInfo) => setPreviewSource(source)}
      />

      {/* Chat History Panel */}
      <ChatHistoryPanel
        isOpen={historyPanelOpen}
        onClose={() => setHistoryPanelOpen(false)}
        currentCaseId={caseId}
        onSelectQuery={(query: string) => {
          // Set the selected query in the input field
          setInputValue(query)
          setHistoryPanelOpen(false)
        }}
      />

      {/* Prompt Library */}
      <PromptLibrary
        isOpen={promptLibraryOpen}
        onClose={() => setPromptLibraryOpen(false)}
        onSelectPrompt={(prompt) => {
          setInputValue(prompt)
          setPromptLibraryOpen(false)
        }}
      />

      {/* Response Settings Dialog */}
      <Dialog open={responseSettingsOpen} onClose={() => setResponseSettingsOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Настройки ответа</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <FormControlLabel
              control={
                <Switch
                  checked={deepThinkEnabled}
                  onChange={(e) => setDeepThinkEnabled(e.target.checked)}
                />
              }
              label="Deep Think (глубокий анализ)"
            />
            <Typography variant="body2" color="text.secondary">
              Включите для более детального анализа запросов с использованием расширенного поиска и рассуждений.
            </Typography>
            <Divider />
            <Typography variant="subtitle2">Источники поиска:</Typography>
            <SourceSelector
              sources={DEFAULT_SOURCES}
              selectedSources={selectedSources}
              onSourcesChange={setSelectedSources}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResponseSettingsOpen(false)}>Закрыть</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

export default ChatWindow
