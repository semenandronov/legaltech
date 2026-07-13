import { useState, useEffect, useRef } from 'react'
import { useParams, useLocation, useNavigate } from 'react-router-dom'
import {
  Loader2, ExternalLink,
} from 'lucide-react'
import { getCase, getApiUrl, SourceInfo, getCaseFiles } from '../services/api'
import { ChatHistoryPanel } from '../components/Chat/ChatHistoryPanel'
import { HarveyInput } from '../components/Chat/HarveyInput'
import { CaseFilePickerModal, type CaseFileItem } from '../components/Chat/CaseFilePickerModal'
import { loadChatHistory, mapAssistantHistoryMessage, citationRecordToSourceInfo } from '../services/chatHistoryService'
import MessageContent from '../components/Chat/MessageContent'
import {
  caseAssistantLegacyCitationsEnabled,
  resolveCaseCitationSource,
} from '../utils/caseAssistantCitations'
import { AnswerBlocks, sourceInfosToAnswerBlockCitations } from '../components/Chat/AnswerBlocks'
import {
  ThinkingBlock,
  type ThinkingStep,
  type ToolCallInfo,
} from '../components/Chat/ThinkingBlock'
import { CitationDocumentPanel } from '../components/Documents/CitationDocumentPanel'
import { CaseAssistantPageHeader } from '../components/CaseOverview/CaseAssistantPageHeader'
import { MikeAssistantDisclaimer, MikeAssistantGreeting } from '../components/assistant/MikeAssistantGreeting'
import { MikeUserMessage } from '../components/assistant/MikeUserMessage'
import { toast } from 'sonner'
import { productFeatures } from '../lib/productFeatures'
import { useChatInstrumentSettings } from '../hooks/useChatInstrumentSettings'
import {
  applyAssistantActivityEvent,
  applyReasoningEvent,
} from '../lib/assistantActivity'

// ─────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────
interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: SourceInfo[]
  reasoningSteps?: ThinkingStep[]
  toolCalls?: ToolCallInfo[]
  agentTodos?: Array<{ content: string; status: string }>
  /** Структурированные блоки ответа (SSE answer_blocks / история). */
  answerBlocks?: Array<{ block_id: string; markdown_text: string; citation_ids: string[] }>
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
// Main component
// ─────────────────────────────────────────────────────────
const AssistantChatPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const location = useLocation()
  const navigate = useNavigate()

  const [question, setQuestion] = useState('')
  const [fileContexts, setFileContexts] = useState<FileContext[]>([])
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const sessionIdRef = useRef<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const {
    legalResearch: isLegalResearch,
    courtPractice: isCourtPractice,
    draftMode: isDraftMode,
    setLegalResearch: setIsLegalResearch,
    setCourtPractice: setIsCourtPractice,
    setDraftMode: setIsDraftMode,
    reset: resetChatInstruments,
  } = useChatInstrumentSettings()
  const [draftDocument, setDraftDocument] = useState<DraftDocument | null>(null)
  const [draftDocId, setDraftDocId] = useState<string | null>(null)

  const [historyPanelOpen, setHistoryPanelOpen] = useState(false)
  const [caseTitle, setCaseTitle] = useState<string>('')
  const [loadingSession, setLoadingSession] = useState(false)

  // Case file picker
  const [selectedCaseFileIds, setSelectedCaseFileIds] = useState<string[]>([])
  const [availableCaseFiles, setAvailableCaseFiles] = useState<CaseFileItem[]>([])
  const [caseFilesLoaded, setCaseFilesLoaded] = useState(false)
  const [showCaseFilePicker, setShowCaseFilePicker] = useState(false)
  const [loadingCaseFiles, setLoadingCaseFiles] = useState(false)
  const [viewerSource, setViewerSource] = useState<SourceInfo | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Сброс тумблеров при входе в чат другого дела (или повторном открытии маршрута).
  useEffect(() => {
    resetChatInstruments()
  }, [caseId, resetChatInstruments])

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

  // Handle autoQuery from navigation state (e.g. from GlobalAssistantPage)
  useEffect(() => {
    const autoQuery: string = (location.state as any)?.autoQuery || ''
    if (autoQuery) {
      setQuestion(autoQuery)
    }
  }, [])

  // Client-owned session: mint UUID before first API call so backend never attaches to stale case session.
  useEffect(() => {
    if (!caseId) return
    const params = new URLSearchParams(location.search)
    if (params.get('session')) return
    if (sessionIdRef.current) return
    const newSid = crypto.randomUUID()
    sessionIdRef.current = newSid
    setSessionId(newSid)
  }, [caseId, location.search])

  // Auto-load session from ?session= URL param (e.g. from recent actions on case overview)
  useEffect(() => {
    if (!caseId) return
    const params = new URLSearchParams(location.search)
    const sessionParam = params.get('session')
    if (sessionParam) {
      setLoadingSession(true)
      loadChatHistory(caseId, sessionParam)
        .then((history) => {
          setMessages(history.map((m) => mapAssistantHistoryMessage(m)))
          sessionIdRef.current = sessionParam
          setSessionId(sessionParam)
        })
        .catch(() => {})
        .finally(() => setLoadingSession(false))
    }
  }, [caseId, location.search])

  // Прогрев графа/чекпоинта при открытии чата по делу (меньше задержка первого сообщения)
  useEffect(() => {
    if (!caseId) return
    const token = localStorage.getItem('access_token')
    if (!token) return

    const params = new URLSearchParams(location.search)
    const sessionFromUrl = params.get('session')
    const sid = sessionFromUrl || sessionId || undefined

    let cancelled = false
    const t = window.setTimeout(async () => {
      if (cancelled) return
      try {
        const res = await fetch(getApiUrl('/api/v2/assistant/chat/warmup'), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Access-Token': token,
          },
          body: JSON.stringify({
            case_id: caseId,
            ...(sid ? { session_id: sid } : {}),
          }),
        })
        if (cancelled || !res.ok) return
        const data = (await res.json()) as { session_id?: string }
        // Не перетираем session_id после «Новый чат» (уже задан в state)
        if (data.session_id && !sessionFromUrl && !sessionIdRef.current) {
          sessionIdRef.current = data.session_id
          setSessionId((prev) => prev ?? data.session_id!)
        }
      } catch {
        /* ignore */
      }
    }, 250)

    return () => {
      cancelled = true
      window.clearTimeout(t)
    }
  }, [caseId, location.search, sessionId])

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
          headers: { 'X-Access-Token': token || '' },
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

  // ── Case file picker ──
  const handleOpenCaseFilePicker = async () => {
    setShowCaseFilePicker(true)
    if (!caseFilesLoaded && caseId) {
      setLoadingCaseFiles(true)
      try {
        const result = await getCaseFiles(caseId)
        setAvailableCaseFiles(
          result.files.map((f) => ({
            id: f.id,
            filename: f.filename,
            file_type: f.file_type || '',
          }))
        )
        setCaseFilesLoaded(true)
      } catch {}
      setLoadingCaseFiles(false)
    }
  }

  const selectedCaseFiles: CaseFileItem[] = availableCaseFiles.filter((f) =>
    selectedCaseFileIds.includes(f.id)
  )

  const resolveConversationMode = (): 'research' | 'case_advice' | 'drafting' | 'review' | 'comparison' | 'clarify' => {
    if (isDraftMode) return 'drafting'
    if (isLegalResearch) return 'research'
    return 'case_advice'
  }

  // ── Send message ──
  const handleSubmit = async (
    overrideText?: unknown,
    _options?: Record<string, never>,
  ) => {
    // Может вызываться как onSubmit(event) и как handleSubmit("текст").
    if (overrideText && typeof overrideText === 'object' && 'preventDefault' in (overrideText as any)) {
      ;(overrideText as any).preventDefault?.()
    }
    const rawText = typeof overrideText === 'string' ? overrideText : question
    let text = String(rawText ?? '').trim()
    if (!text || isStreaming) return

    const contextsToSend = [...fileContexts]
    const currentDraft = draftDocument
    setQuestion('')
    // fileContexts are kept for the whole session — files stay available for follow-up messages

    const userMsg: ChatMessage = { role: 'user', content: text }
    const allMessages = [...messages, userMsg]
    setMessages([...allMessages, { role: 'assistant', content: '' }])
    setIsStreaming(true)

    abortRef.current?.abort()
    abortRef.current = new AbortController()

    if (isDraftMode) {
      // Сбрасываем флаг готовности: "Документ создан" показываем только после real document_created
      setDraftDocument(null)
      setDraftDocId(null)
    }

    let assistantContent = ''
    let draftDocIdThisRequest: string | null = null

    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(getApiUrl('/api/v2/assistant/chat'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Access-Token': token || '',
        },
        body: JSON.stringify({
          case_id: caseId,
          mode: resolveConversationMode(),
          messages: allMessages.map((m) => ({ role: m.role, content: m.content })),
          session_id: sessionIdRef.current ?? sessionId,
          file_contexts: contextsToSend.map((fc) => ({ filename: fc.filename, text: fc.text })),
          web_search: false,
          legal_research: isDraftMode ? false : isLegalResearch,
          use_legal_corpus: isDraftMode ? false : isLegalResearch,
          court_practice: false,
          draft_mode: isDraftMode,
          document_context: isDraftMode && currentDraft ? currentDraft.content : undefined,
          attached_file_ids: selectedCaseFileIds.length > 0 ? selectedCaseFileIds : undefined,
        }),
        signal: abortRef.current.signal,
      })

      if (!response.ok) throw new Error(`Server error: ${response.status}`)

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const processSSELine = (line: string) => {
        if (!line.startsWith('data: ')) return
        const raw = line.slice(6).trim()
        if (!raw) return
        try {
          const data = JSON.parse(raw)
          if (data.session_id) {
            sessionIdRef.current = data.session_id
            setSessionId((prev) => prev || data.session_id)
          } else if (data.type === 'citations' && Array.isArray(data.citations)) {
            const sources: SourceInfo[] = data.citations.map((c: unknown) =>
              citationRecordToSourceInfo(c as Record<string, unknown>)
            )
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              return [...prev.slice(0, -1), { ...last, sources }]
            })
          } else if (data.type === 'answer_blocks' && Array.isArray(data.blocks)) {
            const answerBlocks = data.blocks.map((b: Record<string, unknown>) => ({
              block_id: String(b.block_id ?? ''),
              markdown_text: String(b.markdown_text ?? ''),
              citation_ids: Array.isArray(b.citation_ids)
                ? (b.citation_ids as unknown[]).map((x) => String(x))
                : [],
            }))
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              return [...prev.slice(0, -1), { ...last, answerBlocks }]
            })
          } else if (data.type === 'assistant_activity') {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last.role !== 'assistant') return prev
              const reasoningSteps = applyAssistantActivityEvent(
                last.reasoningSteps || [],
                data,
              )
              return [...prev.slice(0, -1), { ...last, reasoningSteps }]
            })
          } else if (data.type === 'reasoning' && data.phase && data.content) {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last.role !== 'assistant') return prev
              const reasoningSteps = applyReasoningEvent(
                last.reasoningSteps || [],
                data,
              )
              return [...prev.slice(0, -1), { ...last, reasoningSteps }]
            })
          } else if (data.type === 'draft_todos' && Array.isArray(data.todos)) {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (!last || last.role !== 'assistant') return prev
              return [
                ...prev.slice(0, -1),
                {
                  ...last,
                  agentTodos: data.todos.map((t: { content?: string; status?: string }) => ({
                    content: String(t.content || ''),
                    status: String(t.status || 'pending'),
                  })),
                },
              ]
            })
          } else if (data.type === 'tool_call' && data.name) {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last.role !== 'assistant') return prev
              const toolCalls = last.toolCalls || []
              if (data.status === 'running') {
                return [
                  ...prev.slice(0, -1),
                  {
                    ...last,
                    toolCalls: [
                      ...toolCalls,
                      {
                        name: data.name,
                        status: 'running',
                        input: typeof data.input === 'string' ? data.input : JSON.stringify(data.input ?? ''),
                      },
                    ],
                  },
                ]
              }
              let idx = -1
              for (let i = toolCalls.length - 1; i >= 0; i--) {
                if (toolCalls[i].name === data.name && toolCalls[i].status === 'running') {
                  idx = i
                  break
                }
              }
              const updated = [...toolCalls]
              if (idx >= 0) {
                updated[idx] = {
                  ...updated[idx],
                  status: data.status === 'error' ? 'error' : 'completed',
                  output: data.output,
                }
                return [...prev.slice(0, -1), { ...last, toolCalls: updated }]
              }
              return [
                ...prev.slice(0, -1),
                {
                  ...last,
                  toolCalls: [
                    ...toolCalls,
                    {
                      name: data.name,
                      status: data.status === 'error' ? 'error' : 'completed',
                      output: data.output,
                    },
                  ],
                },
              ]
            })
          } else if (data.error) {
            assistantContent = `Ошибка: ${data.error}`
            setMessages((prev) => [
              ...prev.slice(0, -1),
              { role: 'assistant', content: assistantContent },
            ])
          } else if (
            (data.type === 'document_created' && data.document) ||
            (data.type === 'document-card' && data.data)
          ) {
            const doc = data.document || data.data
            const docId = doc.id
            const docTitle = doc.title || 'Черновик'
            draftDocIdThisRequest = docId
            setDraftDocId(docId)
            setDraftDocument({ title: docTitle, content: '' })
          } else if (data.type === 'content_sync' && typeof data.content === 'string') {
            // Финальный текст узла графа после sanitize — подменяем накопленный стрим (убирает утечки/дубли).
            assistantContent = data.content
            const draftShowContent =
              isDraftMode &&
              (assistantContent.includes('❌') ||
                assistantContent.includes('Ошибка') ||
                assistantContent.includes('✅'))
            if (!isDraftMode || draftShowContent) {
              setMessages((prev) => {
                const last = prev[prev.length - 1]
                return [...prev.slice(0, -1), { ...last, role: 'assistant', content: assistantContent }]
              })
            }
          } else if (data.textDelta) {
            assistantContent += data.textDelta
            const draftShowDelta =
              isDraftMode &&
              (data.textDelta.includes('❌') ||
                assistantContent.includes('Ошибка') ||
                assistantContent.includes('✅'))
            if (!isDraftMode || draftShowDelta) {
              // Preserve sources if already set (citations can arrive before last textDelta in some edge cases)
              setMessages((prev) => {
                const last = prev[prev.length - 1]
                return [...prev.slice(0, -1), { ...last, role: 'assistant', content: assistantContent }]
              })
            }
          }
        } catch {}
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          // Flush remaining buffer on stream end
          if (buffer) {
            for (const line of buffer.split('\n')) processSSELine(line)
          }
          break
        }
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) processSSELine(line)
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
      if (isDraftMode && assistantContent.trim()) {
        const draftFailed =
          !draftDocIdThisRequest &&
          (assistantContent.includes('❌') || assistantContent.includes('Ошибка создания'))
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last?.role !== 'assistant') return prev
          return [...prev.slice(0, -1), { ...last, role: 'assistant', content: assistantContent }]
        })
        if (draftFailed) {
          toast.error('Не удалось сохранить документ в редактор. Нажмите «Одобрить план» ещё раз.')
        }
      }
    }
  }

  // ── Open draft in case document editor ──
  const handleOpenInEditor = async () => {
    if (!caseId || !productFeatures.editor) return
    // If backend already created the document, navigate directly
    if (draftDocId) {
      navigate(`/cases/${caseId}/editor/${draftDocId}`)
      return
    }
    // Fallback: shouldn't happen, but handle gracefully
    toast.error('Документ ещё не готов')
  }

  // ── Open citation in document viewer (or quote popup for direct uploads) ──
  const handleCitationClick = (source: SourceInfo) => {
    // External sources (pravo.gov.ru etc.) — open in new tab, never local viewer
    if (source.source_type === 'external' || (source.url && source.url.startsWith('http'))) {
      if (source.url) {
        window.open(source.url, '_blank', 'noopener,noreferrer')
      }
      return
    }
    const resolved = resolveCaseCitationSource(
      source,
      availableCaseFiles,
      caseId ?? undefined,
    )
    setViewerSource(resolved)
  }

  // ── New chat ──
  const handleNewChat = () => {
    abortRef.current?.abort()
    setMessages([])
    setQuestion('')
    setFileContexts([])
    setSelectedCaseFileIds([])
    // Новый UUID = новый LangGraph thread; иначе бэкенд цепляется к последней сессии дела (<30 мин)
    const newSid = crypto.randomUUID()
    sessionIdRef.current = newSid
    setSessionId(newSid)
    resetChatInstruments()
    setDraftDocument(null)
    setDraftDocId(null)
    if (caseId) {
      navigate(`/cases/${caseId}/chat`, { replace: true })
    }
  }

  // ── Load history session ──
  const handleLoadHistory = async (histSessionId?: string) => {
    if (!caseId) return
    resetChatInstruments()
    try {
      const history = await loadChatHistory(caseId, histSessionId)
      setMessages(history.map((m) => mapAssistantHistoryMessage(m)))
      if (histSessionId) {
        sessionIdRef.current = histSessionId
        setSessionId(histSessionId)
      }
    } catch {
      toast.error('Не удалось загрузить историю')
    }
  }

  if (!caseId) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Дело не найдено</p>
      </div>
    )
  }

  const sessionParam = new URLSearchParams(location.search).get('session')
  const chatActive = messages.length > 0 || loadingSession || !!sessionParam

  const harveyInputProps = {
    appearance: 'mike' as const,
    variant: 'case' as const,
    value: question,
    onChange: setQuestion,
    onSubmit: handleSubmit,
    fileContexts,
    uploadingFiles,
    onAddFiles: handleAddFiles,
    onRemoveContext: handleRemoveContext,
    selectedCaseFiles,
    onOpenCaseFilePicker: handleOpenCaseFilePicker,
    onRemoveCaseFile: (id: string) => setSelectedCaseFileIds((prev) => prev.filter((x) => x !== id)),
    isStreaming,
    isDraftMode,
    onSetDraftMode: setIsDraftMode,
    useLegalCorpus: isLegalResearch,
    onUseLegalCorpusChange: setIsLegalResearch,
    useCourtPractice: isCourtPractice,
    onUseCourtPracticeChange: setIsCourtPractice,
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <CaseAssistantPageHeader
        caseTitle={caseTitle}
        onNavigateCases={() => navigate('/cases')}
        onNavigateCase={() => navigate(`/cases/${caseId}`)}
        onNewChat={handleNewChat}
      />

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden border-t border-gray-200">
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <div
            className="relative flex min-w-0 flex-col overflow-hidden transition-all duration-300"
            style={{ width: viewerSource ? '45%' : '100%' }}
          >
            {!chatActive ? (
              <div className="flex h-full w-full flex-col px-6">
                <div className="flex flex-1 flex-col items-center justify-center">
                  <div className="relative w-full max-w-4xl px-0 xl:px-8">
                    <MikeAssistantGreeting />
                    <HarveyInput {...harveyInputProps} />
                    <MikeAssistantDisclaimer />
                  </div>
                </div>
              </div>
            ) : (
              <>
                <div className="min-h-0 flex-1 overflow-y-auto">
                  <div className="relative mx-auto flex min-h-full w-full max-w-4xl flex-col space-y-6 px-6 pb-32 pt-4 md:px-8 md:pt-6">
                    {loadingSession && messages.length === 0 && (
                      <div className="flex items-center justify-center py-16">
                        <div className="flex gap-1">
                          {[0, 1, 2].map((i) => (
                            <div
                              key={i}
                              className="h-2 w-2 animate-bounce rounded-full bg-gray-300"
                              style={{ animationDelay: `${i * 150}ms` }}
                            />
                          ))}
                        </div>
                      </div>
                    )}
                    {messages.map((msg, idx) => {
                    const assistantTextBody =
                      msg.role === 'assistant'
                        ? (msg.content && msg.content.trim()) || ''
                        : ''
                    const showAssistantTextBody = msg.role === 'assistant' && Boolean(assistantTextBody)
                    /** Не подменять стрим markdown блоками Phase 2 — иначе весь текст визуально исчезает и рисуется заново из `AnswerBlocks`. */
                    const hasStreamedAssistantMarkdown = Boolean(
                      msg.role === 'assistant' && msg.content && msg.content.trim().length > 0,
                    )
                    const showAnswerBlocks =
                      msg.role === 'assistant' &&
                      (msg.answerBlocks?.length ?? 0) > 0 &&
                      !hasStreamedAssistantMarkdown
                    return (
                    <div key={idx}>
                      {msg.role === 'user' ? (
                        <MikeUserMessage content={msg.content} />
                      ) : (
                        <div className="min-w-0 max-w-full text-sm">
                          {((msg.toolCalls && msg.toolCalls.length > 0) ||
                            (msg.reasoningSteps && msg.reasoningSteps.length > 0) ||
                            (msg.agentTodos && msg.agentTodos.length > 0) ||
                            (isStreaming && idx === messages.length - 1 && !msg.content)) && (
                            <div className="mb-3">
                              <ThinkingBlock
                                steps={msg.reasoningSteps || []}
                                toolCalls={msg.toolCalls}
                                agentTodos={msg.agentTodos}
                                planOutlineTitle="Draft Agent"
                                isStreaming={isStreaming && idx === messages.length - 1 && !msg.content}
                                defaultOpen
                              />
                            </div>
                          )}
                          {showAnswerBlocks ? (
                            <AnswerBlocks
                              blocks={msg.answerBlocks!}
                              citations={sourceInfosToAnswerBlockCitations(msg.sources || [])}
                              onCitationClick={handleCitationClick}
                              isStreaming={isStreaming && idx === messages.length - 1}
                            />
                          ) : showAssistantTextBody ? (
                            <MessageContent
                              content={assistantTextBody}
                              sources={msg.sources || []}
                              answerBlocks={msg.answerBlocks}
                              preferLegacyCitations={caseAssistantLegacyCitationsEnabled()}
                              onCitationClick={handleCitationClick}
                              isStreaming={isStreaming && idx === messages.length - 1}
                            />
                          ) : (
                            isStreaming && idx === messages.length - 1 && !isDraftMode && (
                              <div className="flex gap-1">
                                {[0, 1, 2].map((i) => (
                                  <div
                                    key={i}
                                    className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-300"
                                    style={{ animationDelay: `${i * 150}ms` }}
                                  />
                                ))}
                              </div>
                            )
                          )}
                          {/* Draft indicator */}
                          {productFeatures.draftMode && isDraftMode && idx === messages.length - 1 && (
                            isStreaming ? (
                              <div className="flex items-center gap-2 mt-1">
                                <Loader2 className="w-3.5 h-3.5 animate-spin" style={{ color: 'var(--color-accent-muted)' }} />
                                <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Создаю документ...</span>
                              </div>
                            ) : draftDocId && draftDocument ? (
                              <div className="flex flex-col gap-2 mt-1">
                                <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                                  Готово! Документ{draftDocument.title ? ` «${draftDocument.title}»` : ''} создан.
                                </p>
                                {productFeatures.editor && (
                                <button
                                  onClick={handleOpenInEditor}
                                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors self-start"
                                  style={{
                                    border: '1px solid var(--color-border)',
                                    backgroundColor: 'var(--color-bg-hover)',
                                    color: 'var(--color-accent)',
                                  }}
                                >
                                  <ExternalLink className="w-3.5 h-3.5" />
                                  Перейти в редактор
                                </button>
                                )}
                              </div>
                            ) : null
                          )}
                        </div>
                      )}
                    </div>
                    )
                  })}
                    <div ref={messagesEndRef} />
                  </div>
                </div>

                <div className="absolute bottom-0 left-0 right-0 z-30 w-full">
                  <div className="pointer-events-none absolute bottom-0 left-0 right-4 z-0 h-28 bg-gradient-to-t from-white/50 via-white/25 to-transparent backdrop-blur-[1px]" />
                  <div className="relative z-20 mx-auto w-full max-w-4xl px-4 md:px-6">
                    <HarveyInput {...harveyInputProps} />
                    <MikeAssistantDisclaimer />
                  </div>
                </div>
              </>
            )}
          </div>

          {viewerSource && chatActive && (
              <div
                className="ws-side-panel transition-all duration-300"
                style={{ width: '55%' }}
              >
                <CitationDocumentPanel
                  source={viewerSource}
                  caseId={caseId}
                  onClose={() => setViewerSource(null)}
                  citationPreview
                  className="h-full"
                />
              </div>
            )}
        </div>
      </div>

      {/* History drawer */}
      <ChatHistoryPanel
        isOpen={historyPanelOpen}
        onClose={() => setHistoryPanelOpen(false)}
        currentCaseId={caseId}
        onSelectQuery={(query, _sId) => {
          setQuestion(query)
          setHistoryPanelOpen(false)
        }}
        onLoadHistory={handleLoadHistory}
      />

      {/* Case file picker modal */}
      <CaseFilePickerModal
        isOpen={showCaseFilePicker}
        files={availableCaseFiles}
        loading={loadingCaseFiles}
        initialSelectedIds={selectedCaseFileIds}
        onApply={(ids) => {
          setSelectedCaseFileIds(ids)
          setShowCaseFilePicker(false)
        }}
        onClose={() => setShowCaseFilePicker(false)}
      />
    </div>
  )
}

export default AssistantChatPage
