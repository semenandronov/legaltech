import { useState, useEffect, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import {
  FolderOpen, MessageSquare, FileText, X, Plus,
  AlignJustify, SlidersHorizontal, Sparkles, Search, ChevronDown, Loader2, Download, Clock,
} from 'lucide-react'
import { getApiUrl, getGlobalAssistantSession } from '../services/api'

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

const navItems = [
  { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
  { id: 'assistant', label: 'Ассистент', icon: MessageSquare, path: '/assistant' },
  { id: 'history', label: 'История', icon: Clock, path: '/history' },
]

const WORKFLOWS = [
  {
    id: 1,
    title: 'Сравнение с правовым стандартом',
    description: 'Загрузите документ и проверьте его на соответствие правовому стандарту или регламенту.',
    outputType: 'Output',
    outputLabel: 'Результат',
    steps: 2,
    prompt: 'Сравни этот документ с соответствующим правовым стандартом и выяви несоответствия:',
  },
  {
    id: 2,
    title: 'Анализ договора',
    description: 'Загрузите договор и извлеките ключевые условия, обязательства, риски и рекомендации.',
    outputType: 'Output',
    outputLabel: 'Результат',
    steps: 3,
    prompt: 'Проанализируй этот договор и выдели ключевые условия, обязательства, риски и рекомендации:',
  },
  {
    id: 3,
    title: 'Составление юридического документа',
    description: 'Опишите нужный документ и предоставьте контекст для составления с помощью AI.',
    outputType: 'Draft',
    outputLabel: 'Черновик',
    steps: 2,
    prompt: 'Составь юридический документ на основе следующего описания и контекста:',
  },
  {
    id: 4,
    title: 'Чек-лист Due Diligence',
    description: 'Создайте комплексный чек-лист due diligence для вашего типа сделки и юрисдикции.',
    outputType: 'Output',
    outputLabel: 'Результат',
    steps: 4,
    prompt: 'Составь комплексный чек-лист due diligence для следующей сделки:',
  },
  {
    id: 5,
    title: 'Правовое заключение',
    description: 'Исследуйте правовой вопрос и получите структурированное заключение со ссылками и анализом.',
    outputType: 'Output',
    outputLabel: 'Результат',
    steps: 5,
    prompt: 'Исследуй следующий правовой вопрос и подготовь структурированное заключение со ссылками:',
  },
  {
    id: 6,
    title: 'Краткое изложение документов',
    description: 'Загрузите несколько документов и получите краткие резюме с ключевыми выводами.',
    outputType: 'Output',
    outputLabel: 'Результат',
    steps: 2,
    prompt: 'Сделай краткое изложение следующего документа и выдели ключевые моменты:',
  },
]

const SOURCES = [
  { label: 'Веб-поиск', color: '#22C55E' },
  { label: 'Документы дела', color: '#3B82F6' },
  { label: 'Загруженные файлы', color: '#F97316' },
  { label: 'Шаблоны договоров', color: '#8B5CF6' },
]

// ─────────────────────────────────────────────────────────
// Harvey-style input card
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
  placeholder?: string
}

function HarveyInput({
  value, onChange, onSubmit,
  fileContexts, uploadingFiles, onAddFiles, onRemoveContext,
  isStreaming, isDraftMode, onSetDraftMode,
  placeholder = 'Спросите что угодно...',
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
        {/* Left tools (overflow-hidden to prevent pushing send button) */}
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

        {/* Settings dropdown — outside overflow-hidden so the popup is not clipped */}
        <div ref={settingsRef} className="relative flex-shrink-0">
          <button
            type="button"
            onClick={() => setSettingsOpen((o) => !o)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors whitespace-nowrap"
            style={{
              color: isDraftMode ? '#4F46E5' : '#6B7280',
              backgroundColor: settingsOpen ? '#F3F4F6' : undefined,
            }}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            Настройки
            {isDraftMode && (
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 ml-0.5 flex-shrink-0" />
            )}
          </button>

          {settingsOpen && (
            <div
              className="absolute bottom-full mb-1.5 left-0 bg-white rounded-lg border border-gray-200 overflow-hidden z-50"
              style={{ minWidth: '130px', boxShadow: '0 4px 16px rgba(0,0,0,0.10)' }}
            >
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
                <span
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ backgroundColor: !isDraftMode ? '#111827' : '#D1D5DB' }}
                />
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
                <span
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ backgroundColor: isDraftMode ? '#4F46E5' : '#D1D5DB' }}
                />
                Draft
              </button>
            </div>
          )}
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Send button — always visible */}
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
const GlobalAssistantPage = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const [question, setQuestion] = useState('')
  const [fileContexts, setFileContexts] = useState<FileContext[]>([])
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [isDraftMode, setIsDraftMode] = useState(false)
  const [draftDocument, setDraftDocument] = useState<DraftDocument | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Load session from ?session= URL param
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const sessionParam = params.get('session')
    if (!sessionParam) return
    getGlobalAssistantSession(sessionParam)
      .then((data) => {
        setMessages(data.messages.map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content })))
        setSessionId(sessionParam)
      })
      .catch(() => {})
  }, [location.search])

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
      } finally {
        setUploadingFiles((prev) => prev.filter((n) => n !== file.name))
      }
    }
  }

  const handleRemoveContext = (idx: number) => {
    setFileContexts((prev) => prev.filter((_, i) => i !== idx))
  }

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

    // Show document panel immediately in draft mode
    if (isDraftMode) {
      setDraftDocument((prev) => prev ?? { title: 'Черновик', content: '' })
    }

    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(getApiUrl('/api/v2/assistant/global-chat'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          messages: allMessages.map((m) => ({ role: m.role, content: m.content })),
          session_id: sessionId,
          file_contexts: contextsToSend.map((fc) => ({ filename: fc.filename, text: fc.text })),
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
              // Update document panel live during streaming
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
          { role: 'assistant', content: 'An error occurred. Please try again.' },
        ])
      }
    } finally {
      setIsStreaming(false)
    }
  }

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
    }
  }

  const handleNewChat = () => {
    abortRef.current?.abort()
    setMessages([])
    setQuestion('')
    setFileContexts([])
    setSessionId(null)
    setIsDraftMode(false)
    setDraftDocument(null)
  }

  const chatActive = messages.length > 0

  return (
    <div className="h-screen flex overflow-hidden bg-white">
      <UnifiedSidebar navItems={navItems} title="Legal AI" />

      <div className="flex-1 flex flex-col overflow-hidden">
        {chatActive ? (
          // ── Chat view (with optional split-view document panel) ──
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
                {isDraftMode && (
                  <span
                    className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                    style={{ backgroundColor: '#EEF2FF', color: '#4F46E5', border: '1px solid #C7D2FE' }}
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 inline-block" />
                    Режим черновика
                  </span>
                )}
              </div>
              <button
                onClick={handleNewChat}
                className="flex items-center gap-1.5 text-sm font-medium transition-opacity hover:opacity-70"
                style={{ color: '#6B7280' }}
              >
                <Plus className="w-4 h-4" />
                Новый чат
              </button>
            </div>

            {/* Body: chat + optional document panel */}
            <div className="flex-1 flex overflow-hidden">
              {/* Chat column */}
              <div className="flex flex-col overflow-hidden" style={{ width: draftDocument ? '45%' : '100%', transition: 'width 0.2s ease' }}>
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
                  {/* Panel header */}
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

                  {/* Editable content */}
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
          // ── Harvey-style landing ─────────────────────────
          <div className="flex-1 overflow-y-auto" style={{ backgroundColor: '#FAFAFA' }}>
            <div className="max-w-[960px] mx-auto px-6 pt-12 pb-12">

              {/* Client matter selector */}
              <div className="mb-8">
                <button
                  onClick={() => navigate('/cases')}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-sm transition-colors hover:bg-white"
                  style={{ borderColor: '#E5E7EB', color: '#6B7280', backgroundColor: 'transparent' }}
                >
                  <FolderOpen className="w-3.5 h-3.5" />
                  Выбрать дело
                  <ChevronDown className="w-3 h-3 ml-0.5" style={{ color: '#9CA3AF' }} />
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
              <div className="mb-4">
                {isDraftMode && (
                  <div className="flex items-center gap-2 mb-2">
                    <span
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
                      style={{ backgroundColor: '#EEF2FF', color: '#4F46E5', border: '1px solid #C7D2FE' }}
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 inline-block" />
                      Режим черновика
                    </span>
                    <button
                      type="button"
                      onClick={() => setIsDraftMode(false)}
                      className="text-xs transition-colors hover:text-gray-700"
                      style={{ color: '#9CA3AF' }}
                    >
                      ✕ Отключить
                    </button>
                  </div>
                )}
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
                />
              </div>

              {/* Source pills */}
              <div className="flex flex-wrap justify-center gap-2 mb-10">
                {SOURCES.map((source) => (
                  <button
                    key={source.label}
                    type="button"
                    className="flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs transition-colors hover:bg-white"
                    style={{ borderColor: '#E5E7EB', color: '#6B7280', backgroundColor: 'transparent' }}
                  >
                    <span
                      className="w-2 h-2 rounded-full flex-shrink-0"
                      style={{ backgroundColor: source.color }}
                    />
                    {source.label}
                    <Plus className="w-3 h-3" style={{ color: '#9CA3AF' }} />
                  </button>
                ))}
              </div>

              {/* Recommended workflows */}
              <div>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-medium" style={{ color: '#111827' }}>
                    Рекомендуемые сценарии
                  </h3>
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      className="flex items-center gap-1.5 text-sm transition-colors hover:text-gray-900"
                      style={{ color: '#6B7280' }}
                    >
                      <Search className="w-3.5 h-3.5" />
                      Поиск
                    </button>
                    <button
                      type="button"
                      className="text-sm transition-colors hover:text-gray-900"
                      style={{ color: '#6B7280' }}
                    >
                      Все сценарии
                    </button>
                  </div>
                </div>

                <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
                  {WORKFLOWS.map((w) => (
                    <button
                      key={w.id}
                      type="button"
                      onClick={() => {
                        setQuestion(w.prompt)
                        setIsDraftMode(w.outputType === 'Draft')
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
      </div>
    </div>
  )
}

export default GlobalAssistantPage
