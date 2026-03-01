import { useState, useEffect, useRef } from 'react'
import { useParams, useLocation } from 'react-router-dom'
import {
  FileText, X, Plus, AlignJustify, SlidersHorizontal, Sparkles,
  Search, Loader2, Download, History,
} from 'lucide-react'
import { getCase, getApiUrl } from '../services/api'
import { ChatHistoryPanel } from '../components/Chat/ChatHistoryPanel'
import { loadChatHistory } from '../services/chatHistoryService'
import {
  consumePendingWorkflowResult,
  createWorkflowResultChatMessage,
  saveWorkflowMessageToHistory,
} from '../services/workflowResultsService'
import { toast } from 'sonner'

// ─────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────
interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface FileContext {
  filename: string
  text: string
  charCount: number
}

interface DraftDocument {
  title: string
  content: string
}

// ─────────────────────────────────────────────────────────
// Case-specific workflows
// ─────────────────────────────────────────────────────────
const WORKFLOWS = [
  {
    id: 1,
    title: 'Ключевые сроки',
    description: 'Извлеките все важные даты и дедлайны из документов дела.',
    outputLabel: 'Результат',
    steps: 1,
    prompt: 'Какие ключевые сроки важны в этом деле?',
  },
  {
    id: 2,
    title: 'Анализ рисков',
    description: 'Выявите риски и уязвимые места в документах дела.',
    outputLabel: 'Результат',
    steps: 2,
    prompt: 'Какие риски есть в документах этого дела?',
  },
  {
    id: 3,
    title: 'Составление документа',
    description: 'Опишите нужный документ, и AI составит его с учётом контекста дела.',
    outputLabel: 'Черновик',
    steps: 2,
    prompt: 'Составь юридический документ на основе следующего описания:',
    isDraft: true,
  },
  {
    id: 4,
    title: 'Суммы и стороны',
    description: 'Извлеките суммы, стороны договора, организации из документов дела.',
    outputLabel: 'Результат',
    steps: 1,
    prompt: 'Какие суммы и стороны упоминаются в документах этого дела?',
  },
  {
    id: 5,
    title: 'Анализ договора',
    description: 'Загрузите договор и получите анализ условий, обязательств и рисков.',
    outputLabel: 'Результат',
    steps: 2,
    prompt: 'Проанализируй условия, обязательства и риски в этом договоре:',
  },
  {
    id: 6,
    title: 'Резюме дела',
    description: 'Получите краткое резюме дела с ключевыми выводами по документам.',
    outputLabel: 'Результат',
    steps: 1,
    prompt: 'Сделай краткое резюме этого дела с ключевыми выводами по документам.',
  },
]

// ─────────────────────────────────────────────────────────
// HarveyInput — input card with case-specific settings
// ─────────────────────────────────────────────────────────
interface HarveyInputProps {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  fileContexts: FileContext[]
  uploadingFiles: string[]
  onAddFiles: (files: File[]) => void
  onRemoveContext: (idx: number) => void
  isStreaming: boolean
  isDraftMode: boolean
  onSetDraftMode: (draft: boolean) => void
  isLegalResearch: boolean
  onSetLegalResearch: (v: boolean) => void
  isDeepThink: boolean
  onSetDeepThink: (v: boolean) => void
  placeholder?: string
}

function HarveyInput({
  value, onChange, onSubmit,
  fileContexts, uploadingFiles, onAddFiles, onRemoveContext,
  isStreaming, isDraftMode, onSetDraftMode,
  isLegalResearch, onSetLegalResearch,
  isDeepThink, onSetDeepThink,
  placeholder = 'Спросите что угодно о деле...',
}: HarveyInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const settingsRef = useRef<HTMLDivElement>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [value])

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) {
        setSettingsOpen(false)
      }
    }
    if (settingsOpen) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [settingsOpen])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (value.trim() && !isStreaming) onSubmit()
    }
  }

  const hasFiles = fileContexts.length > 0 || uploadingFiles.length > 0
  const hasActiveSettings = isDraftMode || isLegalResearch || isDeepThink

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden" style={{ boxShadow: '0 1px 6px rgba(0,0,0,0.06)' }}>
      {/* Textarea */}
      <div className="px-4 pt-4 pb-2">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={3}
          className="w-full resize-none outline-none bg-transparent"
          style={{
            minHeight: '80px',
            fontSize: '15px',
            lineHeight: '1.6',
            color: '#111827',
            fontFamily: 'inherit',
          }}
        />
      </div>

      {/* Attached files */}
      {hasFiles && (
        <div className="px-4 pb-2 flex flex-wrap gap-2">
          {uploadingFiles.map((name) => (
            <div
              key={`uploading-${name}`}
              className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs border border-blue-200 bg-blue-50"
              style={{ color: '#2563EB' }}
            >
              <Loader2 className="w-3 h-3 animate-spin" />
              <span className="max-w-[140px] truncate">{name}</span>
            </div>
          ))}
          {fileContexts.map((fc, i) => (
            <div
              key={`ctx-${i}`}
              className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs border border-gray-200 bg-gray-50"
              style={{ color: '#374151' }}
            >
              <FileText className="w-3 h-3" style={{ color: '#22C55E' }} />
              <span className="max-w-[140px] truncate">{fc.filename}</span>
              <span className="text-gray-400 ml-0.5">{Math.round(fc.charCount / 1000)}k</span>
              <button onClick={() => onRemoveContext(i)} className="ml-0.5 hover:text-red-500 transition-colors">
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center px-3 py-2 border-t border-gray-100" style={{ gap: '2px' }}>
        {/* Left tools */}
        <div className="flex items-center min-w-0 overflow-hidden" style={{ gap: '2px' }}>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors hover:bg-gray-50 flex-shrink-0 whitespace-nowrap"
            style={{ color: '#6B7280' }}
          >
            <Plus className="w-3.5 h-3.5" />
            Файлы
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.csv,.xlsx"
            className="hidden"
            onChange={(e) => {
              if (e.target.files) {
                onAddFiles(Array.from(e.target.files))
                e.target.value = ''
              }
            }}
          />

          <button
            type="button"
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors hover:bg-gray-50 flex-shrink-0 whitespace-nowrap"
            style={{ color: '#6B7280' }}
          >
            <AlignJustify className="w-3.5 h-3.5" />
            Промпты
          </button>

          <button
            type="button"
            disabled
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm opacity-40 cursor-not-allowed flex-shrink-0 whitespace-nowrap"
            style={{ color: '#6B7280' }}
          >
            <Sparkles className="w-3.5 h-3.5" />
            Улучшить
          </button>
        </div>

        {/* Settings dropdown — outside overflow-hidden */}
        <div ref={settingsRef} className="relative flex-shrink-0">
          <button
            type="button"
            onClick={() => setSettingsOpen((o) => !o)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors whitespace-nowrap"
            style={{
              color: hasActiveSettings ? '#4F46E5' : '#6B7280',
              backgroundColor: settingsOpen ? '#F3F4F6' : undefined,
            }}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            Настройки
            {hasActiveSettings && (
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 ml-0.5 flex-shrink-0" />
            )}
          </button>

          {settingsOpen && (
            <div
              className="absolute bottom-full mb-1.5 left-0 bg-white rounded-lg border border-gray-200 overflow-hidden z-50"
              style={{ minWidth: '160px', boxShadow: '0 4px 16px rgba(0,0,0,0.10)' }}
            >
              {/* Mode section */}
              <div className="px-2.5 py-1.5 text-xs font-medium border-b border-gray-100" style={{ color: '#9CA3AF' }}>
                Режим
              </div>
              <button
                type="button"
                onClick={() => { onSetDraftMode(false); setSettingsOpen(false) }}
                className="w-full flex items-center gap-2 px-2.5 py-2 text-sm transition-colors"
                style={{
                  color: !isDraftMode ? '#111827' : '#6B7280',
                  backgroundColor: !isDraftMode ? '#F9FAFB' : 'transparent',
                  fontWeight: !isDraftMode ? 500 : 400,
                }}
              >
                <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: !isDraftMode ? '#111827' : '#D1D5DB' }} />
                Ask
              </button>
              <button
                type="button"
                onClick={() => { onSetDraftMode(true); setSettingsOpen(false) }}
                className="w-full flex items-center gap-2 px-2.5 py-2 text-sm transition-colors"
                style={{
                  color: isDraftMode ? '#4F46E5' : '#6B7280',
                  backgroundColor: isDraftMode ? '#EEF2FF' : 'transparent',
                  fontWeight: isDraftMode ? 500 : 400,
                }}
              >
                <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: isDraftMode ? '#4F46E5' : '#D1D5DB' }} />
                Draft
              </button>

              {/* Tools section */}
              <div className="px-2.5 py-1.5 text-xs font-medium border-t border-b border-gray-100" style={{ color: '#9CA3AF' }}>
                Инструменты
              </div>
              <button
                type="button"
                onClick={() => onSetLegalResearch(!isLegalResearch)}
                className="w-full flex items-center gap-2 px-2.5 py-2 text-sm transition-colors"
                style={{
                  color: isLegalResearch ? '#059669' : '#6B7280',
                  backgroundColor: isLegalResearch ? '#ECFDF5' : 'transparent',
                }}
              >
                <span
                  className="w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0"
                  style={{
                    borderColor: isLegalResearch ? '#059669' : '#D1D5DB',
                    backgroundColor: isLegalResearch ? '#059669' : 'transparent',
                  }}
                >
                  {isLegalResearch && <span className="text-white" style={{ fontSize: '9px' }}>✓</span>}
                </span>
                Legal Research
              </button>
              <button
                type="button"
                onClick={() => onSetDeepThink(!isDeepThink)}
                className="w-full flex items-center gap-2 px-2.5 py-2 text-sm transition-colors"
                style={{
                  color: isDeepThink ? '#7C3AED' : '#6B7280',
                  backgroundColor: isDeepThink ? '#F5F3FF' : 'transparent',
                }}
              >
                <span
                  className="w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0"
                  style={{
                    borderColor: isDeepThink ? '#7C3AED' : '#D1D5DB',
                    backgroundColor: isDeepThink ? '#7C3AED' : 'transparent',
                  }}
                >
                  {isDeepThink && <span className="text-white" style={{ fontSize: '9px' }}>✓</span>}
                </span>
                Deep Think
              </button>
            </div>
          )}
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Send button */}
        <div className="flex-shrink-0">
          <button
            type="button"
            onClick={onSubmit}
            disabled={!value.trim() || isStreaming}
            className="flex items-center justify-center px-4 py-1.5 text-sm font-medium text-white rounded-lg transition-all disabled:opacity-40"
            style={{ backgroundColor: '#111827', minWidth: '80px' }}
          >
            {isStreaming ? (
              <div
                className="w-4 h-4 border-2 rounded-full animate-spin"
                style={{ borderColor: 'rgba(255,255,255,0.3)', borderTopColor: '#fff' }}
              />
            ) : (
              'Отправить'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────
const AssistantChatPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const location = useLocation()

  const [question, setQuestion] = useState('')
  const [fileContexts, setFileContexts] = useState<FileContext[]>([])
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [isDraftMode, setIsDraftMode] = useState(false)
  const [isLegalResearch, setIsLegalResearch] = useState(false)
  const [isDeepThink, setIsDeepThink] = useState(false)
  const [draftDocument, setDraftDocument] = useState<DraftDocument | null>(null)
  const [historyPanelOpen, setHistoryPanelOpen] = useState(false)
  const [caseTitle, setCaseTitle] = useState<string>('')

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const workflowResultProcessed = useRef(false)

  // Load case info
  useEffect(() => {
    if (!caseId) return
    getCase(caseId)
      .then((d) => setCaseTitle(d.title || ''))
      .catch(() => {})
  }, [caseId])

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Handle pending workflow result
  useEffect(() => {
    const timer = setTimeout(async () => {
      if (workflowResultProcessed.current) return
      const pendingResult = consumePendingWorkflowResult()
      if (pendingResult && pendingResult.case_id === caseId) {
        workflowResultProcessed.current = true
        const message = createWorkflowResultChatMessage(pendingResult)
        setMessages([{ role: 'assistant', content: message.content }])
        try {
          await saveWorkflowMessageToHistory(pendingResult)
        } catch {}
        if (pendingResult.status === 'completed') {
          toast.success(`✨ Workflow "${pendingResult.workflow_name}" завершён!`, {
            description: `Обработано ${pendingResult.documents_processed} документов за ${pendingResult.elapsed_time}`,
            duration: 5000,
          })
        } else {
          toast.error(`Workflow "${pendingResult.workflow_name}" завершён с ошибкой`, {
            description: pendingResult.error || 'Неизвестная ошибка',
            duration: 5000,
          })
        }
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [caseId])

  // Handle autoQuery from navigation state (e.g. from GlobalAssistantPage)
  useEffect(() => {
    const autoQuery: string = (location.state as any)?.autoQuery || ''
    if (autoQuery) {
      setQuestion(autoQuery)
    }
  }, [])

  // Auto-load session from ?session= URL param (e.g. from recent actions on case overview)
  useEffect(() => {
    if (!caseId) return
    const params = new URLSearchParams(location.search)
    const sessionParam = params.get('session')
    if (sessionParam) {
      loadChatHistory(caseId, sessionParam)
        .then((history) => {
          setMessages(history.map((m) => ({ role: m.role, content: m.content })))
          setSessionId(sessionParam)
        })
        .catch(() => {})
    }
  }, [caseId, location.search])

  // ── File upload ──
  const handleAddFiles = async (newFiles: File[]) => {
    const token = localStorage.getItem('access_token')
    for (const file of newFiles) {
      setUploadingFiles((prev) => [...prev, file.name])
      try {
        const formData = new FormData()
        formData.append('file', file)
        const res = await fetch(getApiUrl('/api/v2/assistant/upload-file'), {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: formData,
        })
        if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
        const data: FileContext = await res.json()
        setFileContexts((prev) => [...prev, data])
      } catch (err) {
        console.error('File upload error:', err)
        toast.error(`Не удалось загрузить файл ${file.name}`)
      } finally {
        setUploadingFiles((prev) => prev.filter((n) => n !== file.name))
      }
    }
  }

  const handleRemoveContext = (idx: number) => {
    setFileContexts((prev) => prev.filter((_, i) => i !== idx))
  }

  // ── Send message ──
  const handleSubmit = async () => {
    const text = question.trim()
    if (!text || isStreaming) return

    const contextsToSend = [...fileContexts]
    const currentDraft = draftDocument
    setQuestion('')
    setFileContexts([])

    const userMsg: ChatMessage = { role: 'user', content: text }
    const allMessages = [...messages, userMsg]
    setMessages([...allMessages, { role: 'assistant', content: '' }])
    setIsStreaming(true)

    abortRef.current?.abort()
    abortRef.current = new AbortController()

    if (isDraftMode) {
      setDraftDocument((prev) => prev ?? { title: 'Черновик', content: '' })
    }

    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(getApiUrl('/api/v2/assistant/chat'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          case_id: caseId,
          messages: allMessages.map((m) => ({ role: m.role, content: m.content })),
          session_id: sessionId,
          file_contexts: contextsToSend.map((fc) => ({ filename: fc.filename, text: fc.text })),
          web_search: false,
          legal_research: isLegalResearch,
          deep_think: isDeepThink,
          draft_mode: isDraftMode,
          document_context: isDraftMode && currentDraft ? currentDraft.content : undefined,
        }),
        signal: abortRef.current.signal,
      })

      if (!response.ok) throw new Error(`Server error: ${response.status}`)

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let assistantContent = ''
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue
          try {
            const data = JSON.parse(raw)
            if (data.session_id && !sessionId) {
              setSessionId(data.session_id)
            } else if (data.textDelta) {
              assistantContent += data.textDelta
              setMessages((prev) => [
                ...prev.slice(0, -1),
                { role: 'assistant', content: assistantContent },
              ])
              if (isDraftMode) {
                const draftLines = assistantContent.trim().split('\n')
                const firstLine = draftLines[0].trim()
                const boldMatch = firstLine.match(/^\*\*(.+?)\*\*$/)
                const headingMatch = firstLine.match(/^#+\s+(.+)$/)
                if (boldMatch) {
                  setDraftDocument({ title: boldMatch[1], content: draftLines.slice(1).join('\n').trimStart() })
                } else if (headingMatch) {
                  setDraftDocument({ title: headingMatch[1], content: draftLines.slice(1).join('\n').trimStart() })
                } else {
                  setDraftDocument((prev) => ({ title: prev?.title ?? 'Документ', content: assistantContent.trim() }))
                }
              }
            }
          } catch {}
        }
      }
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        setMessages((prev) => [
          ...prev.slice(0, -1),
          { role: 'assistant', content: 'Произошла ошибка. Попробуйте ещё раз.' },
        ])
      }
    } finally {
      setIsStreaming(false)
    }
  }

  // ── DOCX download ──
  const handleDownloadDocx = async () => {
    if (!draftDocument) return
    try {
      const token = localStorage.getItem('access_token')
      const res = await fetch(getApiUrl('/api/v2/assistant/download-docx'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ title: draftDocument.title, content: draftDocument.content }),
      })
      if (!res.ok) throw new Error('Download failed')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${draftDocument.title}.docx`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Download error:', err)
      toast.error('Не удалось скачать документ')
    }
  }

  // ── New chat ──
  const handleNewChat = () => {
    abortRef.current?.abort()
    setMessages([])
    setQuestion('')
    setFileContexts([])
    setSessionId(null)
    setIsDraftMode(false)
    setDraftDocument(null)
  }

  // ── Load history session ──
  const handleLoadHistory = async (histSessionId?: string) => {
    if (!caseId) return
    try {
      const history = await loadChatHistory(caseId, histSessionId)
      setMessages(history.map((m) => ({ role: m.role, content: m.content })))
      if (histSessionId) setSessionId(histSessionId)
    } catch {
      toast.error('Не удалось загрузить историю')
    }
  }

  if (!caseId) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-sm" style={{ color: '#6B7280' }}>Дело не найдено</p>
      </div>
    )
  }

  const chatActive = messages.length > 0

  return (
    <div className="h-full flex flex-col overflow-hidden bg-white">
      {chatActive ? (
        // ── Chat view ──
        <>
          {/* Header */}
          <div
            className="flex items-center justify-between px-6 py-3 border-b shrink-0"
            style={{ borderBottomColor: '#E5E7EB' }}
          >
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium" style={{ color: '#6B7280' }}>
                Ассистент
              </span>
              {caseTitle && (
                <span className="text-sm" style={{ color: '#9CA3AF' }}>
                  · {caseTitle}
                </span>
              )}
              {isDraftMode && (
                <span
                  className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                  style={{ backgroundColor: '#EEF2FF', color: '#4F46E5', border: '1px solid #C7D2FE' }}
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 inline-block" />
                  Draft
                </span>
              )}
              {isLegalResearch && (
                <span
                  className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                  style={{ backgroundColor: '#ECFDF5', color: '#059669', border: '1px solid #A7F3D0' }}
                >
                  Legal Research
                </span>
              )}
              {isDeepThink && (
                <span
                  className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                  style={{ backgroundColor: '#F5F3FF', color: '#7C3AED', border: '1px solid #DDD6FE' }}
                >
                  Deep Think
                </span>
              )}
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setHistoryPanelOpen(true)}
                className="flex items-center gap-1.5 text-sm transition-opacity hover:opacity-70"
                style={{ color: '#6B7280' }}
              >
                <History className="w-4 h-4" />
                История
              </button>
              <button
                onClick={handleNewChat}
                className="flex items-center gap-1.5 text-sm font-medium transition-opacity hover:opacity-70"
                style={{ color: '#6B7280' }}
              >
                <Plus className="w-4 h-4" />
                Новый чат
              </button>
            </div>
          </div>

          {/* Body: chat + optional document panel */}
          <div className="flex-1 flex overflow-hidden">
            {/* Chat column */}
            <div
              className="flex flex-col overflow-hidden"
              style={{ width: draftDocument ? '45%' : '100%', transition: 'width 0.2s ease' }}
            >
              <div className="flex-1 overflow-y-auto">
                <div style={{ maxWidth: '960px', margin: '0 auto' }} className="px-6 py-8 space-y-6">
                  {messages.map((msg, idx) => (
                    <div key={idx} className={msg.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                      {msg.role === 'user' ? (
                        <div
                          className="max-w-[75%] px-4 py-3 rounded-2xl text-sm leading-relaxed"
                          style={{ backgroundColor: '#111827', color: '#fff' }}
                        >
                          {msg.content}
                        </div>
                      ) : (
                        <div
                          className="max-w-[90%] text-sm leading-relaxed whitespace-pre-wrap"
                          style={{ color: '#111827' }}
                        >
                          {msg.content || (
                            <div className="flex gap-1">
                              {[0, 1, 2].map((i) => (
                                <div
                                  key={i}
                                  className="w-1.5 h-1.5 rounded-full animate-bounce"
                                  style={{ backgroundColor: '#9CA3AF', animationDelay: `${i * 150}ms` }}
                                />
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                  <div ref={messagesEndRef} />
                </div>
              </div>

              <div className="shrink-0 px-6 py-4 border-t" style={{ borderTopColor: '#E5E7EB' }}>
                <div style={{ maxWidth: '960px', margin: '0 auto' }}>
                  <HarveyInput
                    value={question}
                    onChange={setQuestion}
                    onSubmit={handleSubmit}
                    fileContexts={fileContexts}
                    uploadingFiles={uploadingFiles}
                    onAddFiles={handleAddFiles}
                    onRemoveContext={handleRemoveContext}
                    isStreaming={isStreaming}
                    isDraftMode={isDraftMode}
                    onSetDraftMode={setIsDraftMode}
                    isLegalResearch={isLegalResearch}
                    onSetLegalResearch={setIsLegalResearch}
                    isDeepThink={isDeepThink}
                    onSetDeepThink={setIsDeepThink}
                  />
                </div>
              </div>
            </div>

            {/* Document panel */}
            {draftDocument && (
              <div
                className="flex flex-col border-l overflow-hidden"
                style={{ width: '55%', borderLeftColor: '#E5E7EB', backgroundColor: '#FAFAFA' }}
              >
                <div
                  className="flex items-center gap-3 px-5 py-3 border-b bg-white shrink-0"
                  style={{ borderBottomColor: '#E5E7EB' }}
                >
                  <input
                    value={draftDocument.title}
                    onChange={(e) => setDraftDocument((prev) => prev ? { ...prev, title: e.target.value } : null)}
                    className="flex-1 text-sm font-semibold outline-none bg-transparent"
                    style={{ color: '#111827' }}
                  />
                  <button
                    onClick={handleDownloadDocx}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors hover:bg-gray-50"
                    style={{ borderColor: '#E5E7EB', color: '#374151' }}
                  >
                    <Download className="w-3.5 h-3.5" />
                    Скачать .docx
                  </button>
                  <button
                    onClick={() => setDraftDocument(null)}
                    className="p-1 rounded-md transition-colors hover:bg-gray-100"
                    style={{ color: '#9CA3AF' }}
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <div className="flex-1 overflow-y-auto p-6">
                  <textarea
                    value={draftDocument.content}
                    onChange={(e) => setDraftDocument((prev) => prev ? { ...prev, content: e.target.value } : null)}
                    className="w-full h-full resize-none outline-none text-sm leading-relaxed bg-transparent"
                    style={{ color: '#111827', fontFamily: 'inherit', minHeight: '400px' }}
                  />
                </div>
              </div>
            )}
          </div>
        </>
      ) : (
        // ── Landing ──
        <div className="flex-1 overflow-y-auto" style={{ backgroundColor: '#FAFAFA' }}>
          <div className="max-w-[960px] mx-auto px-6 pt-12 pb-12">

            {/* Case badge */}
            <div className="mb-8 flex items-center justify-between">
              <div
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-sm"
                style={{ borderColor: '#E5E7EB', color: '#6B7280', backgroundColor: 'white' }}
              >
                <FileText className="w-3.5 h-3.5" />
                {caseTitle || 'Загрузка...'}
              </div>
              <button
                onClick={() => setHistoryPanelOpen(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-sm transition-colors hover:bg-white"
                style={{ borderColor: '#E5E7EB', color: '#6B7280', backgroundColor: 'transparent' }}
              >
                <History className="w-3.5 h-3.5" />
                История
              </button>
            </div>

            {/* Title */}
            <h1
              className="text-center mb-8"
              style={{
                fontSize: '52px',
                fontFamily: 'Georgia, "Times New Roman", serif',
                fontWeight: 400,
                color: '#111827',
                letterSpacing: '-0.5px',
                lineHeight: 1.15,
              }}
            >
              Legal AI
            </h1>

            {/* Input card */}
            <div className="mb-8">
              <HarveyInput
                value={question}
                onChange={setQuestion}
                onSubmit={handleSubmit}
                fileContexts={fileContexts}
                uploadingFiles={uploadingFiles}
                onAddFiles={handleAddFiles}
                onRemoveContext={handleRemoveContext}
                isStreaming={isStreaming}
                isDraftMode={isDraftMode}
                onSetDraftMode={setIsDraftMode}
                isLegalResearch={isLegalResearch}
                onSetLegalResearch={setIsLegalResearch}
                isDeepThink={isDeepThink}
                onSetDeepThink={setIsDeepThink}
              />
            </div>

            {/* Workflows */}
            <div>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium" style={{ color: '#111827' }}>
                  Рекомендуемые сценарии
                </h3>
                <button
                  type="button"
                  className="flex items-center gap-1.5 text-sm transition-colors hover:text-gray-900"
                  style={{ color: '#6B7280' }}
                >
                  <Search className="w-3.5 h-3.5" />
                  Поиск
                </button>
              </div>

              <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
                {WORKFLOWS.map((w) => (
                  <button
                    key={w.id}
                    type="button"
                    onClick={() => {
                      setQuestion(w.prompt)
                      if (w.isDraft) setIsDraftMode(true)
                    }}
                    className="text-left p-4 rounded-xl border bg-white transition-all duration-150 hover:shadow-md hover:border-gray-300"
                    style={{ borderColor: '#E5E7EB' }}
                  >
                    <h4 className="text-sm font-medium mb-2 leading-snug" style={{ color: '#111827' }}>
                      {w.title}
                    </h4>
                    <p
                      className="text-xs leading-relaxed mb-4"
                      style={{
                        color: '#6B7280',
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical' as const,
                        overflow: 'hidden',
                      }}
                    >
                      {w.description}
                    </p>
                    <div className="flex items-center justify-between">
                      <span className="text-xs" style={{ color: '#9CA3AF' }}>
                        {w.outputLabel} · {w.steps} шагов
                      </span>
                      <div
                        className="w-6 h-6 rounded flex items-center justify-center flex-shrink-0"
                        style={{ backgroundColor: '#111827' }}
                      >
                        <span className="text-white font-bold" style={{ fontSize: '11px' }}>L</span>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>

          </div>
        </div>
      )}

      {/* History drawer */}
      <ChatHistoryPanel
        isOpen={historyPanelOpen}
        onClose={() => setHistoryPanelOpen(false)}
        currentCaseId={caseId}
        onSelectQuery={(query, sId) => {
          setQuestion(query)
          setHistoryPanelOpen(false)
        }}
        onLoadHistory={handleLoadHistory}
      />
    </div>
  )
}

export default AssistantChatPage
