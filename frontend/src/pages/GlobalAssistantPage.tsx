import { useState, useEffect, useRef, useCallback } from 'react'
import { toast } from 'sonner'
import { useLocation, useNavigate } from 'react-router-dom'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { FileText, X, Loader2, Download } from 'lucide-react'
import {
  getApiUrl,
  getGlobalAssistantSession,
  saveSessionDraft,
  UploadedFile,
  SourceInfo,
  fetchLegalCorpusStatus,
  fetchLegalCorpusFiles,
  uploadLegalCorpusFiles,
  deleteLegalCorpusFile,
  type LegalCorpusStatus,
  type LegalCorpusFileRow,
  extractErrorMessage,
} from '../services/api'
import { citationRecordToSourceInfo } from '../services/chatHistoryService'
import { DocumentEditor, DocumentEditorRef } from '../components/Editor/DocumentEditor'
import MessageContent from '../components/Chat/MessageContent'
import ThinkingBlock from '../components/Chat/ThinkingBlock'
import DocumentPreviewSheet from '../components/Chat/DocumentPreviewSheet'
import { HarveyInput } from '../components/Chat/HarveyInput'
import { CaseDocumentPickerModal } from '../components/Chat/CaseDocumentPickerModal'
import { GlobalAssistantPageHeader } from '../components/assistant/GlobalAssistantPageHeader'
import { MikeAssistantDisclaimer, MikeAssistantGreeting } from '../components/assistant/MikeAssistantGreeting'
import { MikeUserMessage } from '../components/assistant/MikeUserMessage'
import { productFeatures } from '../lib/productFeatures'
import { buildMainNavItems } from '../lib/mainNavItems'
import { useChatInstrumentSettings } from '../hooks/useChatInstrumentSettings'

function inlineFmt(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
}

function markdownToHtml(md: string): string {
  const lines = md.split('\n')
  let html = ''
  let inUl = false
  let inOl = false
  for (const line of lines) {
    if (!/^[-*]\s/.test(line) && inUl) { html += '</ul>'; inUl = false }
    if (!/^\d+\.\s/.test(line) && inOl) { html += '</ol>'; inOl = false }
    const h4 = line.match(/^####\s+(.+)$/); const h3 = line.match(/^###\s+(.+)$/)
    const h2 = line.match(/^##\s+(.+)$/); const h1 = line.match(/^#\s+(.+)$/)
    if (h1) { html += `<h1>${inlineFmt(h1[1])}</h1>`; continue }
    if (h2) { html += `<h2>${inlineFmt(h2[1])}</h2>`; continue }
    if (h3) { html += `<h3>${inlineFmt(h3[1])}</h3>`; continue }
    if (h4) { html += `<h4>${inlineFmt(h4[1])}</h4>`; continue }
    // Skip decorator/separator lines (---, ***, •••, ===, etc.) — not needed in legal docs
    const trimmed = line.trim()
    if (trimmed.length >= 3 && /^(.)\1+$/.test(trimmed) && !/\w/.test(trimmed)) { continue }
    const ul = line.match(/^[-*]\s+(.+)$/)
    if (ul) { if (!inUl) { html += '<ul>'; inUl = true } html += `<li>${inlineFmt(ul[1])}</li>`; continue }
    const ol = line.match(/^\d+\.\s+(.+)$/)
    if (ol) { if (!inOl) { html += '<ol>'; inOl = true } html += `<li>${inlineFmt(ol[1])}</li>`; continue }
    if (line.trim() === '') continue
    html += `<p>${inlineFmt(line)}</p>`
  }
  if (inUl) html += '</ul>'
  if (inOl) html += '</ol>'
  return html
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  attachedFiles?: Array<{ id: string; filename: string }>
  sources?: SourceInfo[]
  reasoningSteps?: Array<{
    phase: string
    step: number
    totalSteps: number
    content: string
    status?: 'pending' | 'running' | 'completed' | 'error'
    toolName?: string
  }>
}

interface FileContext {
  file_id?: string
  filename: string
  file_type?: string
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
const GlobalAssistantPage = () => {
  const location = useLocation()
  const navigate = useNavigate()
  const [question, setQuestion] = useState('')
  const [fileContexts, setFileContexts] = useState<FileContext[]>([])
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  /** Синхронный id сессии для запросов (до re-render React после SSE session). */
  const sessionIdRef = useRef<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const {
    legalResearch: useLegalCorpus,
    courtPractice: useCourtPractice,
    draftMode: isDraftMode,
    setLegalResearch: setUseLegalCorpus,
    setCourtPractice: setUseCourtPractice,
    setDraftMode: setIsDraftMode,
    reset: resetChatInstruments,
  } = useChatInstrumentSettings()
  const [draftDocument, setDraftDocument] = useState<DraftDocument | null>(null)
  const [showDraftPanel, setShowDraftPanel] = useState(false)
  const [editorContent, setEditorContent] = useState<string | null>(null)
  const draftEditorRef = useRef<DocumentEditorRef>(null)
  const editorHtmlRef = useRef<string>('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const applySessionId = useCallback(
    (id: string) => {
      if (!id) return
      sessionIdRef.current = id
      setSessionId(id)
      const params = new URLSearchParams(location.search)
      if (params.get('session') !== id) {
        params.set('session', id)
        const q = params.toString()
        navigate({ pathname: location.pathname, search: q ? `?${q}` : '' }, { replace: true })
      }
    },
    [location.pathname, location.search, navigate],
  )

  const [selectedCaseFiles, setSelectedCaseFiles] = useState<UploadedFile[]>([])
  const [showCasePicker, setShowCasePicker] = useState(false)
  const [citationPreview, setCitationPreview] = useState<SourceInfo | null>(null)
  const [legalCorpusStatus, setLegalCorpusStatus] = useState<LegalCorpusStatus | null>(null)
  const [corpusFilesList, setCorpusFilesList] = useState<LegalCorpusFileRow[]>([])
  const [corpusUploading, setCorpusUploading] = useState(false)
  const refreshLegalCorpus = useCallback(async () => {
    try {
      const st = await fetchLegalCorpusStatus()
      setLegalCorpusStatus(st)
      if (st.is_uploader) {
        const { files } = await fetchLegalCorpusFiles()
        setCorpusFilesList(files)
      } else {
        setCorpusFilesList([])
      }
    } catch {
      /* не блокируем чат */
    }
  }, [])

  useEffect(() => {
    void refreshLegalCorpus()
  }, [refreshLegalCorpus])

  const handleUseLegalCorpusChange = setUseLegalCorpus
  const handleUseCourtPracticeChange = setUseCourtPractice
  const handleSetDraftMode = setIsDraftMode

  const resolveConversationMode = (): 'research' | 'case_advice' | 'drafting' | 'review' | 'comparison' | 'clarify' => {
    if (isDraftMode) return 'drafting'
    if (useLegalCorpus) return 'research'
    return 'case_advice'
  }

  const handleCorpusFilesSelected = async (files: File[]) => {
    if (!files.length) return
    setCorpusUploading(true)
    try {
      const res = await uploadLegalCorpusFiles(files)
      if (res.indexed.length) {
        toast.success(
          `Справочник: добавлено файлов ${res.indexed.length}, всего фрагментов в индексе: ${res.chunk_count_total}`
        )
      }
      if (res.errors.length) {
        res.errors.forEach((e) => toast.error(`${e.filename}: ${e.detail}`))
      }
      await refreshLegalCorpus()
    } catch (err: unknown) {
      toast.error(extractErrorMessage(err))
    } finally {
      setCorpusUploading(false)
    }
  }

  const handleDeleteCorpusFile = async (corpusFileId: string) => {
    try {
      await deleteLegalCorpusFile(corpusFileId)
      toast.success('Файл удалён из справочника')
      await refreshLegalCorpus()
    } catch (err: unknown) {
      toast.error(extractErrorMessage(err))
    }
  }

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
        const loadedMessages = data.messages.map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))
        setMessages(loadedMessages)
        sessionIdRef.current = sessionParam
        setSessionId(sessionParam)

        // Restore draft document: prefer saved draft, else detect from last assistant message
        if (data.draft_content && data.draft_title) {
          setDraftDocument({ title: data.draft_title, content: data.draft_content })
          setEditorContent(data.draft_content) // already HTML
        } else {
          const lastMsg = loadedMessages[loadedMessages.length - 1]
          if (lastMsg?.role === 'assistant' && lastMsg.content.length > 400) {
            const lines = lastMsg.content.trim().split('\n')
            const firstLine = lines[0].trim()
            const boldMatch = firstLine.match(/^\*\*(.+?)\*\*$/)
            const headingMatch = firstLine.match(/^#+\s+(.+)$/)
            let title = ''
            let bodyContent = lastMsg.content.trim()
            if (boldMatch) { title = boldMatch[1]; bodyContent = lines.slice(1).join('\n').trimStart() }
            else if (headingMatch) { title = headingMatch[1]; bodyContent = lines.slice(1).join('\n').trimStart() }
            if (title && bodyContent.length > 200) {
              setDraftDocument({ title, content: bodyContent })
              setEditorContent(markdownToHtml(bodyContent))
            }
          }
        }
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
          headers: { 'X-Access-Token': token || '' },
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

  const handleRemoveCaseFile = (id: string) => {
    setSelectedCaseFiles((prev) => prev.filter((f) => f.id !== id))
  }

  const handleCasePickerConfirm = (files: UploadedFile[]) => {
    setSelectedCaseFiles((prev) => {
      const existingIds = new Set(prev.map((f) => f.id))
      const newFiles = files.filter((f) => !existingIds.has(f.id))
      return [...prev, ...newFiles]
    })
  }

  const handleSubmit = async () => {
    const text = question.trim()
    if (!text || isStreaming) return

    const contextsToSend = [...fileContexts]
    const caseFileIdsToSend = selectedCaseFiles.map((f) => f.id)
    const currentDraft = draftDocument
    setQuestion('')
    setFileContexts([])
    setSelectedCaseFiles([])

    const allAttachedFiles = [
      ...contextsToSend.map((fc) => ({ id: fc.file_id || fc.filename, filename: fc.filename })),
      ...selectedCaseFiles.map((f) => ({ id: f.id, filename: f.filename })),
    ]
    const userMsg: ChatMessage = {
      role: 'user',
      content: text,
      attachedFiles: allAttachedFiles.length > 0 ? allAttachedFiles : undefined,
    }
    const allMessages = [...messages, userMsg]
    setMessages([...allMessages, { role: 'assistant', content: '' }])
    setIsStreaming(true)

    abortRef.current?.abort()
    abortRef.current = new AbortController()

    if (isDraftMode) {
      setDraftDocument((prev) => prev ?? { title: 'Черновик', content: '' })
      setEditorContent(null)
      editorHtmlRef.current = ''
    }

    let finalDraftContent = ''
    let finalDraftTitle = 'Документ'
    const activeSessionId = sessionIdRef.current ?? sessionId
    let capturedSessionId = activeSessionId

    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(getApiUrl('/api/v2/assistant/global-chat'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Access-Token': token || '',
        },
        body: JSON.stringify({
          mode: resolveConversationMode(),
          messages: allMessages.map((m) => ({ role: m.role, content: m.content })),
          session_id: activeSessionId,
          file_contexts: contextsToSend.map((fc) => ({ file_id: fc.file_id, filename: fc.filename, text: fc.text })),
          attached_file_ids: caseFileIdsToSend.length > 0 ? caseFileIdsToSend : undefined,
          draft_mode: isDraftMode,
          document_context: isDraftMode && currentDraft ? currentDraft.content : undefined,
          use_legal_corpus: isDraftMode ? false : useLegalCorpus,
          court_practice: isDraftMode ? false : useCourtPractice,
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
            if (data.session_id) {
              applySessionId(data.session_id)
              capturedSessionId = data.session_id
            } else if (data.error) {
              assistantContent = `Ошибка: ${data.error}`
              setMessages((prev) => [
                ...prev.slice(0, -1),
                { role: 'assistant', content: assistantContent },
              ])
            } else if (data.type === 'citations' && Array.isArray(data.citations)) {
              const sources: SourceInfo[] = data.citations.map((c: unknown) => {
                const s = citationRecordToSourceInfo(c as Record<string, unknown>)
                const raw = c as Record<string, unknown>
                if (typeof raw.case_id === 'string') {
                  s.case_id = raw.case_id
                }
                return s
              })
              setMessages((prev) => [
                ...prev.slice(0, -1),
                { ...prev[prev.length - 1], sources },
              ])
            } else if (data.textDelta) {
              assistantContent += data.textDelta
              if (!isDraftMode) {
                setMessages((prev) => [
                  ...prev.slice(0, -1),
                  { role: 'assistant', content: assistantContent },
                ])
              } else {
                // Draft mode: keep chat empty, parse content for right panel
                const draftLines = assistantContent.trim().split('\n')
                const firstLine = draftLines[0].trim()
                const boldMatch = firstLine.match(/^\*\*(.+?)\*\*$/)
                const headingMatch = firstLine.match(/^#+\s+(.+)$/)
                if (boldMatch) {
                  finalDraftTitle = boldMatch[1]
                  finalDraftContent = draftLines.slice(1).join('\n').trimStart()
                  setDraftDocument({ title: boldMatch[1], content: finalDraftContent })
                } else if (headingMatch) {
                  finalDraftTitle = headingMatch[1]
                  finalDraftContent = draftLines.slice(1).join('\n').trimStart()
                  setDraftDocument({ title: headingMatch[1], content: finalDraftContent })
                } else {
                  finalDraftContent = assistantContent.trim()
                  setDraftDocument((prev) => ({ title: prev?.title ?? 'Документ', content: finalDraftContent }))
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
      if (isDraftMode && finalDraftContent) {
        const htmlContent = markdownToHtml(finalDraftContent)
        setEditorContent(htmlContent)
        editorHtmlRef.current = ''
        if (capturedSessionId) {
          saveSessionDraft(capturedSessionId, finalDraftTitle, htmlContent).catch(() => {})
        }
      }
    }
  }

  const handleDownloadDocx = async () => {
    if (!draftDocument) return
    try {
      const token = localStorage.getItem('access_token')
      const contentToSend = editorHtmlRef.current || editorContent || draftDocument.content
      const contentTypeToSend = (editorHtmlRef.current || editorContent) ? 'html' : 'markdown'
      console.log('[download] content_type:', contentTypeToSend, 'content_len:', contentToSend?.length)
      const res = await fetch(getApiUrl('/api/v2/assistant/download-docx'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Access-Token': token || '' },
        body: JSON.stringify({
          title: draftDocument.title,
          content: contentToSend,
          content_type: contentTypeToSend,
        }),
      })
      if (!res.ok) {
        const errText = await res.text().catch(() => '')
        console.error('[download] server error:', res.status, errText)
        throw new Error(`Server ${res.status}: ${errText}`)
      }
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
      toast.error('Ошибка при скачивании документа')
    }
  }

  const handleNewChat = () => {
    abortRef.current?.abort()
    setMessages([])
    setQuestion('')
    setFileContexts([])
    setSelectedCaseFiles([])
    sessionIdRef.current = null
    setSessionId(null)
    resetChatInstruments()
    setDraftDocument(null)
    setShowDraftPanel(false)
    setEditorContent(null)
    editorHtmlRef.current = ''
    navigate('/assistant', { replace: true })
  }

  const sessionParam = new URLSearchParams(location.search).get('session')
  const chatActive = messages.length > 0 || !!sessionParam
  const sidePanelOpen = productFeatures.draftMode && showDraftPanel && Boolean(draftDocument)

  const harveyInputProps = {
    appearance: 'mike' as const,
    variant: 'global' as const,
    value: question,
    onChange: setQuestion,
    onSubmit: handleSubmit,
    fileContexts,
    uploadingFiles,
    onAddFiles: handleAddFiles,
    onRemoveContext: handleRemoveContext,
    isStreaming,
    isDraftMode,
    onSetDraftMode: handleSetDraftMode,
    selectedCaseFiles,
    onRemoveCaseFile: handleRemoveCaseFile,
    onOpenCasePicker: () => setShowCasePicker(true),
    useLegalCorpus,
    onUseLegalCorpusChange: handleUseLegalCorpusChange,
    useCourtPractice,
    onUseCourtPracticeChange: handleUseCourtPracticeChange,
    isLegalCorpusUploader: Boolean(legalCorpusStatus?.is_uploader),
    corpusFiles: corpusFilesList,
    corpusUploading,
    onCorpusFilesSelected: handleCorpusFilesSelected,
    onDeleteCorpusFile: handleDeleteCorpusFile,
  }

  return (
    <div className="ws-shell ws-tabular-shell flex h-screen overflow-hidden">
      <UnifiedSidebar navItems={buildMainNavItems()} title="Legal AI" showBackButton={false} variant="tabular" />

      {showCasePicker && (
        <CaseDocumentPickerModal
          onClose={() => setShowCasePicker(false)}
          onConfirm={handleCasePickerConfirm}
          alreadySelectedIds={new Set(selectedCaseFiles.map((f) => f.id))}
        />
      )}

      <main className="ws-tabular-page flex min-h-0 flex-1 flex-col overflow-hidden">
        <GlobalAssistantPageHeader onNewChat={handleNewChat} />

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden border-t border-gray-200">
          <div className="flex min-h-0 flex-1 overflow-hidden">
            <div
              className="relative flex min-w-0 flex-col overflow-hidden transition-all duration-300"
              style={{ width: sidePanelOpen ? '45%' : '100%' }}
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
                      {messages.map((msg, idx) => {
                        const showAssistantTextBody = Boolean(msg.content && msg.content.trim())
                        const internalDraftUi = productFeatures.draftMode && (isDraftMode || draftDocument)
                        const assistantTextBody = (msg.content && msg.content.trim()) || ''

                        return (
                          <div key={idx}>
                            {msg.role === 'user' ? (
                              <MikeUserMessage
                                content={msg.content}
                                files={msg.attachedFiles?.map((f) => ({ filename: f.filename }))}
                              />
                            ) : (
                              <div className="min-w-0 max-w-full text-sm leading-relaxed text-gray-900">
                                {((msg.reasoningSteps && msg.reasoningSteps.length > 0) ||
                                  (isStreaming && idx === messages.length - 1 && !msg.content)) && (
                                  <ThinkingBlock
                                    steps={msg.reasoningSteps || []}
                                    isStreaming={isStreaming && idx === messages.length - 1 && !msg.content}
                                    defaultOpen
                                  />
                                )}
                                {showAssistantTextBody ? (
                                  <MessageContent
                                    content={assistantTextBody}
                                    sources={msg.sources || []}
                                    isStreaming={isStreaming && idx === messages.length - 1 && !isDraftMode}
                                    onCitationClick={(source) => {
                                      if (source.source_type === 'external' || (source.url && source.url.startsWith('http'))) {
                                        if (source.url) window.open(source.url, '_blank', 'noopener,noreferrer')
                                        return
                                      }
                                      setCitationPreview(source)
                                    }}
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
                                {internalDraftUi && idx === messages.length - 1 && (
                                  isStreaming ? (
                                    <div className="mt-3 flex flex-col gap-2">
                                      <p className="text-sm text-gray-700">Создаю документ...</p>
                                      <button
                                        type="button"
                                        onClick={() => setShowDraftPanel(true)}
                                        className="inline-flex items-center gap-2 self-start rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50"
                                      >
                                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                        Генерация черновика...
                                      </button>
                                    </div>
                                  ) : draftDocument ? (
                                    <div className="mt-3 flex flex-col gap-2">
                                      <p className="text-sm text-gray-700">
                                        Готово! Документ{draftDocument.title ? ` «${draftDocument.title}»` : ''} создан.
                                      </p>
                                      <button
                                        type="button"
                                        onClick={() => setShowDraftPanel(true)}
                                        className="inline-flex items-center gap-2 self-start rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50"
                                      >
                                        <FileText className="h-3.5 w-3.5" />
                                        Открыть документ
                                      </button>
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

            {chatActive && citationPreview && citationPreview.case_id ? (
                <DocumentPreviewSheet
                  isOpen={!!citationPreview}
                  onClose={() => setCitationPreview(null)}
                  source={citationPreview}
                  caseId={citationPreview.case_id}
                />
              ) : citationPreview && citationPreview.source_type === 'court_practice' ? (
                <DocumentPreviewSheet
                  isOpen={!!citationPreview}
                  onClose={() => setCitationPreview(null)}
                  source={citationPreview}
                  caseId=""
                />
              ) : citationPreview && citationPreview.source_id ? (
                <DocumentPreviewSheet
                  isOpen={!!citationPreview}
                  onClose={() => setCitationPreview(null)}
                  source={citationPreview}
                  caseId=""
                  filesApiBase="/api/v2/assistant"
                />
              ) : citationPreview && (
                <div
                  className="ws-side-panel"
                  style={{ width: '400px', minWidth: '320px' }}
                >
                  <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderBottomColor: '#E5E7EB' }}>
                    <div className="flex items-center gap-2 min-w-0">
                      <FileText className="w-4 h-4 shrink-0" style={{ color: '#6366F1' }} />
                      <span className="text-sm font-medium truncate" style={{ color: '#111827' }}>
                        {citationPreview.title || citationPreview.file || 'Источник'}
                      </span>
                    </div>
                    <button
                      onClick={() => setCitationPreview(null)}
                      className="p-1 rounded hover:bg-gray-100 shrink-0"
                    >
                      <X className="w-4 h-4" style={{ color: '#6B7280' }} />
                    </button>
                  </div>
                  <div className="flex-1 overflow-y-auto p-4">
                    {citationPreview.quote || citationPreview.text_preview ? (
                      <div className="ws-quote-block">
                        {citationPreview.quote || citationPreview.text_preview}
                      </div>
                    ) : (
                      <p className="text-sm" style={{ color: '#9CA3AF' }}>Текст фрагмента недоступен.</p>
                    )}
                  </div>
                </div>
              )}

              {/* Document panel */}
              {chatActive && productFeatures.draftMode && showDraftPanel && draftDocument && (
                <div
                  className="ws-side-panel"
                  style={{ width: '55%' }}
                >
                  <div
                    className="flex items-center gap-3 px-5 py-3 border-b bg-white shrink-0"
                    style={{ borderBottomColor: '#E5E7EB' }}
                  >
                    <input
                      value={draftDocument.title}
                      onChange={(e) => {
                        const newTitle = e.target.value
                        setDraftDocument((prev) => prev ? { ...prev, title: newTitle } : null)
                        if (sessionId) {
                          clearTimeout((window as any)._draftSaveTimer)
                          ;(window as any)._draftSaveTimer = setTimeout(() => {
                            saveSessionDraft(sessionId, newTitle, editorHtmlRef.current || editorContent || '').catch(() => {})
                          }, 1500)
                        }
                      }}
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
                      onClick={() => setShowDraftPanel(false)}
                      className="p-1 rounded-md transition-colors hover:bg-gray-100"
                      style={{ color: '#9CA3AF' }}
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                  <div className="flex-1 flex flex-col overflow-hidden">
                    {isStreaming ? (
                      <div
                        className="flex-1 overflow-y-auto p-8 bg-white"
                        style={{ fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.75', color: '#111827', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
                      >
                        {draftDocument.content}
                      </div>
                    ) : editorContent !== null ? (
                      <DocumentEditor
                        ref={draftEditorRef}
                        content={editorContent}
                        onChange={(html) => {
                          editorHtmlRef.current = html
                          // Auto-save to session with debounce
                          if (sessionId && draftDocument) {
                            clearTimeout((window as any)._draftSaveTimer)
                            ;(window as any)._draftSaveTimer = setTimeout(() => {
                              saveSessionDraft(sessionId, draftDocument.title, html).catch(() => {})
                            }, 1500)
                          }
                        }}
                        onSelectionChange={() => {}}
                      />
                    ) : null}
                  </div>
                </div>
              )}
          </div>
        </div>
      </main>
    </div>
  )
}

export default GlobalAssistantPage
