import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Download, ArrowLeft, MessageSquare, FileText, Table, FileEdit, History, BookOpen, Workflow, ChevronDown } from 'lucide-react'
import { toast } from 'sonner'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { DocumentEditor, DocumentEditorRef } from '../components/Editor/DocumentEditor'
import { DocumentEditorContextChat } from '../components/Editor/DocumentEditorContextChat'
import { VersionHistory } from '../components/Editor/VersionHistory'
// CommentsPanel removed — was overlapping the chat sidebar
import { TemplateSelector } from '../components/Editor/TemplateSelector'
import { DocxImporter } from '../components/Editor/DocxImporter'
import { getDocument, createDocument, updateDocument, exportDocx, exportPdf, listDocuments, Document } from '../services/documentEditorApi'
import { getPlaybooks, checkDocument as runPlaybookCheck, getCheck, Playbook } from '../services/playbooksApi'
import { DocumentsList } from '../components/Editor/DocumentsList'
import { PlaybookResultsPanel } from '../components/Playbooks/PlaybookResultsPanel'

interface DocumentData {
  id: string
  title: string
  content: string
  case_id: string
  version?: number
}

const DocumentEditorPage = () => {
  const { caseId, documentId } = useParams<{ caseId: string; documentId?: string }>()
  const navigate = useNavigate()
  const [document, setDocument] = useState<DocumentData | null>(null)
  const [content, setContent] = useState('')
  const [title, setTitle] = useState('Новый документ')
  const [selectedText, setSelectedText] = useState('')
  const [selectionRange, setSelectionRange] = useState<{ from: number; to: number } | null>(null)
  const [showVersionHistory, setShowVersionHistory] = useState(false)
  // showComments removed — CommentsPanel was overlapping the chat sidebar
  const [showTemplateSelector, setShowTemplateSelector] = useState(false)
  const [showDocxImporter, setShowDocxImporter] = useState(false)
  // comments state removed — CommentsPanel was removed
  const [showPlaybookModal, setShowPlaybookModal] = useState(false)
  const [playbooks, setPlaybooks] = useState<Playbook[]>([])
  const [loadingPlaybooks, setLoadingPlaybooks] = useState(false)
  const [runningPlaybookId, setRunningPlaybookId] = useState<string | null>(null)
  const [playbookResult, setPlaybookResult] = useState<any>(null)
  const [showResultsPanel, setShowResultsPanel] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [documentsList, setDocumentsList] = useState<Document[]>([])
  const [loadingDocuments, setLoadingDocuments] = useState(false)
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const editorRef = useRef<DocumentEditorRef>(null)
  const [showDownloadDropdown, setShowDownloadDropdown] = useState(false)
  const downloadDropdownRef = useRef<HTMLDivElement>(null)

  // Закрытие выпадающего списка «Скачать» при клике снаружи
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (downloadDropdownRef.current && !downloadDropdownRef.current.contains(e.target as Node)) {
        setShowDownloadDropdown(false)
      }
    }
    if (showDownloadDropdown) {
      window.addEventListener('mousedown', handleClickOutside)
      return () => window.removeEventListener('mousedown', handleClickOutside)
    }
  }, [showDownloadDropdown])

  // Warn user about unsaved changes before leaving
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (hasUnsavedChanges) {
        e.preventDefault()
        e.returnValue = 'У вас есть несохранённые изменения. Вы уверены, что хотите уйти?'
        return e.returnValue
      }
    }
    
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [hasUnsavedChanges])

  // Load documents list if documentId is not provided
  useEffect(() => {
    if (!caseId) {
      toast.error('Дело не найдено')
      navigate('/cases')
      return
    }

    const loadData = async () => {
      if (documentId) {
        // Load specific document
        try {
          setLoading(true)
          const doc = await getDocument(documentId)
          setDocument(doc)
          setTitle(doc.title)
          setContent(doc.content || '')
        } catch (error: any) {
          toast.error(error.message || 'Ошибка при загрузке документа')
          navigate(`/cases/${caseId}/editor`)
        } finally {
          setLoading(false)
        }
      } else {
        // Load documents list
        try {
          setLoadingDocuments(true)
          const docs = await listDocuments(caseId)
          setDocumentsList(docs)
        } catch (error: any) {
          toast.error(error.message || 'Ошибка при загрузке списка документов')
        } finally {
          setLoadingDocuments(false)
          setLoading(false)
        }
      }
    }

    loadData()
  }, [caseId, documentId, navigate])

  const handleDocumentSelect = (selectedDocumentId: string) => {
    navigate(`/cases/${caseId}/editor/${selectedDocumentId}`)
  }

  const handleDocumentCreated = (createdDocumentId: string) => {
    navigate(`/cases/${caseId}/editor/${createdDocumentId}`)
  }

  const handleDocumentDeleted = async () => {
    // Reload documents list
    if (caseId) {
      try {
        const docs = await listDocuments(caseId)
        setDocumentsList(docs)
      } catch (error: any) {
        toast.error(error.message || 'Ошибка при обновлении списка документов')
      }
    }
  }

  const handleSave = useCallback(async (showToast: boolean = true) => {
    if (!caseId) return

    if (!title.trim()) {
      if (showToast) toast.error('Введите название документа')
      return
    }

    try {
      setSaving(true)

      if (documentId && document) {
        // Update existing document
        await updateDocument(documentId, content, title)
        if (showToast) {
          toast.success('Документ сохранен')
        }
        setHasUnsavedChanges(false)
      } else {
        // Create new document
        const newDoc = await createDocument(caseId, title, content)
        setDocument(newDoc)
        navigate(`/cases/${caseId}/editor/${newDoc.id}`, { replace: true })
        if (showToast) {
          toast.success('Документ создан')
        }
        setHasUnsavedChanges(false)
      }
    } catch (error: any) {
      toast.error(error.message || 'Ошибка при сохранении')
    } finally {
      setSaving(false)
    }
  }, [caseId, documentId, document, content, title, navigate])

  // Auto-save with debounce
  useEffect(() => {
    if (!documentId || !hasUnsavedChanges) return

    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current)
    }

    saveTimeoutRef.current = setTimeout(() => {
      handleSave(false) // Silent save
    }, 2000) // Auto-save after 2 seconds of inactivity

    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current)
      }
    }
  }, [content, documentId, hasUnsavedChanges, handleSave])

  const handleExportDocx = async () => {
    if (!documentId) {
      toast.error('Сначала сохраните документ')
      return
    }

    try {
      await exportDocx(documentId)
      toast.success('Документ экспортирован в Word')
    } catch (error: any) {
      toast.error(error.message || 'Ошибка при экспорте')
    }
  }

  const handleExportPdf = async () => {
    if (!documentId) {
      toast.error('Сначала сохраните документ')
      return
    }

    try {
      await exportPdf(documentId)
      toast.success('Документ экспортирован в PDF')
    } catch (error: any) {
      toast.error(error.message || 'Ошибка при экспорте')
    }
  }

  const handleContentChange = (newContent: string) => {
    setContent(newContent)
    setHasUnsavedChanges(true)
  }

  const handleInsertText = (text: string) => {
    // Insert text at cursor position in editor
    if (editorRef.current) {
      editorRef.current.insertText(text)
      setHasUnsavedChanges(true)
    }
  }

  const stripMarkdownCodeBlock = (text: string): string => {
    const trimmed = text.trim()
    const match = trimmed.match(/^```(?:html)?\s*\n?([\s\S]*?)\n?```$/i)
    return match ? match[1].trim() : trimmed
  }

  const handleApplyEdit = (editedContent: string) => {
    if (editorRef.current) {
      editorRef.current.setContent(stripMarkdownCodeBlock(editedContent))
      setHasUnsavedChanges(true)
      toast.success('Изменения применены к документу')
    }
  }

  const handleScrollToText = (text: string): boolean => {
    // Scroll to specific text in the document
    if (editorRef.current) {
      return editorRef.current.scrollToText(text)
    }
    return false
  }

  const handleReplaceTextInDocument = (originalText: string, newText: string): boolean => {
    // Replace specific text in the document
    if (editorRef.current) {
      const success = editorRef.current.replaceText(originalText, newText)
      if (success) {
        setHasUnsavedChanges(true)
      }
      return success
    }
    return false
  }

  const handleReplaceRange = (from: number, to: number, text: string) => {
    if (editorRef.current) {
      editorRef.current.replaceRange(from, to, text)
      setHasUnsavedChanges(true)
    }
  }

  const handleVersionRestored = (restoredContent: string) => {
    setContent(restoredContent)
    setHasUnsavedChanges(true)
    // Reload document to get updated version
    if (documentId) {
      getDocument(documentId).then((doc) => {
        setDocument(doc)
        setTitle(doc.title)
      })
    }
  }

  const handleDocxImport = async (html: string) => {
    const cleanHtml = stripMarkdownCodeBlock(html)
    // Also strip full DOCTYPE/html wrappers — TipTap needs body content only
    const bodyContent = cleanHtml.replace(/<!DOCTYPE[^>]*>[\s\S]*?<body[^>]*>/i, '')
                                 .replace(/<\/body>[\s\S]*?<\/html>/i, '')
                                 .trim() || cleanHtml

    if (editorRef.current) {
      // Already inside editor — just set content
      editorRef.current.setContent(bodyContent)
      setHasUnsavedChanges(true)
    } else {
      // In list mode — create a new document with the imported content
      try {
        const doc = await createDocument(caseId!, 'Импортированный документ', bodyContent)
        toast.success('Документ импортирован')
        navigate(`/cases/${caseId}/editor/${doc.id}`)
      } catch (err: any) {
        toast.error('Ошибка при создании документа: ' + (err.message || ''))
      }
    }
  }

  // handleAddComment / handleRemoveComment removed — CommentsPanel was removed

  // Загрузка playbooks при открытии модального окна
  const handleOpenPlaybookModal = async () => {
    setShowPlaybookModal(true)
    setLoadingPlaybooks(true)
    setPlaybookResult(null)
    try {
      const data = await getPlaybooks()
      setPlaybooks(data)
    } catch (error: any) {
      toast.error('Ошибка загрузки playbooks: ' + (error.message || 'Неизвестная ошибка'))
    } finally {
      setLoadingPlaybooks(false)
    }
  }

  // Запуск проверки документа с playbook
  const handleRunPlaybook = async (playbookId: string) => {
    if (!documentId || !caseId) return
    
    setRunningPlaybookId(playbookId)
    try {
      const checkResponse = await runPlaybookCheck(playbookId, documentId, caseId)
      // Get full check result using check_id
      const fullResult = await getCheck(checkResponse.check_id)
      setPlaybookResult(fullResult)
      setShowPlaybookModal(false)
      setShowResultsPanel(true)
      toast.success(`Проверка завершена! Соответствие: ${fullResult.compliance_score?.toFixed(1) || 0}%`)
    } catch (error: any) {
      const status = error?.response?.status
      if (status === 500) {
        toast.error('Ошибка проверки: внутренняя ошибка сервера при выполнении playbook. Сообщите администратору, что в БД может отсутствовать столбец files.folder_id.')
      } else {
        toast.error('Ошибка проверки: ' + (error.message || 'Неизвестная ошибка'))
      }
    } finally {
      setRunningPlaybookId(null)
    }
  }

  // Навигация к месту в документе
  const handleNavigateToIssue = (location: { start: number; end: number }) => {
    if (editorRef.current && location.start !== undefined && location.end !== undefined) {
      try {
        // Выделяем текст и прокручиваем к нему
        editorRef.current.setSelection(location.start, location.end)
        toast.info('Перешли к найденному месту в документе')
      } catch (error) {
        console.error('Failed to navigate to issue:', error)
        toast.info(`Найдено на позиции ${location.start}-${location.end}`)
      }
    } else {
      toast.warning('Позиция в документе не определена')
    }
  }

  // Load comments effect removed — CommentsPanel was removed

  const navItems = caseId ? [
    { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
    { id: 'documents', label: 'Документы', icon: FileText, path: `/cases/${caseId}/documents` },
    { id: 'editor', label: 'Редактор', icon: FileEdit, path: `/cases/${caseId}/editor` },
    { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
    { id: 'playbooks', label: 'Playbooks', icon: BookOpen, path: `/cases/${caseId}/playbooks` },
    { id: 'workflows', label: 'Workflows', icon: Workflow, path: `/cases/${caseId}/workflows` },
  ] : []

  // Show loading state
  if (loading || loadingDocuments) {
    return (
      <div className="h-screen bg-bg-primary flex">
        {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" forceCollapsed={true} />}
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
            <p className="text-gray-600">
              {documentId ? 'Загрузка документа...' : 'Загрузка списка документов...'}
            </p>
          </div>
        </div>
      </div>
    )
  }

  // Show documents list if no documentId
  if (!documentId) {
    return (
      <div className="h-screen bg-bg-primary flex">
        {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" forceCollapsed={true} />}
        <div className="flex-1 flex flex-col" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
          <DocumentsList
            documents={documentsList}
            caseId={caseId!}
            onDocumentSelect={handleDocumentSelect}
            onDocumentDeleted={handleDocumentDeleted}
            onDocumentCreated={handleDocumentCreated}
            onImportDocx={() => setShowDocxImporter(true)}
          />
        </div>
        <DocxImporter
          isOpen={showDocxImporter}
          onClose={() => setShowDocxImporter(false)}
          onImport={handleDocxImport}
        />
      </div>
    )
  }

  // Show editor for specific document
  return (
    <div className="h-screen bg-bg-primary flex">
      {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" forceCollapsed={true} />}
      <div className="flex-1 flex flex-col" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-3 border-b gap-2" style={{ borderBottomColor: 'var(--color-border)' }}>
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={() => navigate(`/cases/${caseId}/editor`)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-sm font-medium rounded-lg transition-all duration-150 hover:bg-gray-100"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <ArrowLeft className="w-4 h-4" />
              Назад
            </button>
            {!documentId && (
              <button
                onClick={() => setShowTemplateSelector(true)}
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-sm font-medium rounded-lg transition-all duration-150 hover:bg-gray-100 border"
                style={{
                  color: 'var(--color-text-primary)',
                  borderColor: 'var(--color-border)'
                }}
              >
                <FileText className="w-4 h-4" />
                Шаблон
              </button>
            )}
          </div>
          <div className="h-6 w-px bg-gray-300 flex-shrink-0"></div>
          <input
            type="text"
            value={title}
            onChange={(e) => {
              setTitle(e.target.value)
              setHasUnsavedChanges(true)
            }}
            className="text-base font-semibold bg-transparent border-none outline-none px-2 py-1 rounded min-w-0 flex-1"
            style={{ color: 'var(--color-text-primary)' }}
            placeholder="Название документа"
          />
        </div>

        <div className="flex items-center gap-1.5 flex-shrink-0">
          <div className="relative" ref={downloadDropdownRef}>
            <button
              onClick={() => setShowDownloadDropdown((v) => !v)}
              disabled={!documentId || saving}
              className="flex items-center gap-1.5 px-3 py-2 text-sm border rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
              style={{ borderColor: 'var(--color-border)' }}
              aria-label="Скачать документ"
              aria-expanded={showDownloadDropdown}
              aria-haspopup="listbox"
            >
              <Download className="w-4 h-4" />
              Скачать
              <ChevronDown className="w-4 h-4" aria-hidden="true" />
            </button>
            {showDownloadDropdown && (
              <div
                className="absolute top-full left-0 mt-1 py-1 min-w-[120px] bg-white border rounded-lg shadow-lg z-50"
                style={{ borderColor: 'var(--color-border)' }}
                role="listbox"
              >
                <button
                  role="option"
                  onClick={() => {
                    handleExportDocx()
                    setShowDownloadDropdown(false)
                  }}
                  disabled={!documentId || saving}
                  className="flex items-center gap-2 w-full px-3 py-2 text-sm text-left hover:bg-gray-100 disabled:opacity-50 transition-colors"
                >
                  <Download className="w-4 h-4" />
                  DOCX
                </button>
                <button
                  role="option"
                  onClick={() => {
                    handleExportPdf()
                    setShowDownloadDropdown(false)
                  }}
                  disabled={!documentId || saving}
                  className="flex items-center gap-2 w-full px-3 py-2 text-sm text-left hover:bg-gray-100 disabled:opacity-50 transition-colors"
                >
                  <Download className="w-4 h-4" />
                  PDF
                </button>
              </div>
            )}
          </div>
          {documentId && (
            <button
              onClick={() => setShowVersionHistory(true)}
              className="flex items-center gap-1.5 px-3 py-2 text-sm border rounded-lg hover:bg-gray-50 transition-colors"
              style={{ borderColor: 'var(--color-border)' }}
            >
              <History className="w-4 h-4" />
              Версии
            </button>
          )}
        </div>
      </div>

      {/* Main content area */}
      <div className="flex-1 overflow-hidden flex">
        {/* Editor */}
        <div className="flex-1 flex flex-col transition-all duration-300">
          <DocumentEditor
            ref={editorRef}
            content={content}
            onChange={handleContentChange}
            onSelectionChange={setSelectedText}
            onSelectionRangeChange={(range) => {
              setSelectionRange(range)
              if (range && range.from !== range.to) {
                // Actual text selection — highlight it
                editorRef.current?.setSelectionHighlight(range.from, range.to)
              } else {
                // Just cursor movement — clear highlight but keep position
                editorRef.current?.clearSelectionHighlight()
              }
            }}
            caseId={caseId}
            documentId={documentId}
            onInsertText={handleInsertText}
          />
        </div>

        {/* Правая колонка: либо чат с ИИ, либо панель результатов playbook */}
        {documentId && (
          <div className="w-[480px] border-l border-border shrink-0 flex flex-col">
            {showResultsPanel && playbookResult ? (
              <PlaybookResultsPanel
                result={{
                  id: playbookResult.id || 'temp',
                  playbook_id: playbookResult.playbook_id || '',
                  playbook_name: playbookResult.playbook_name || 'Playbook',
                  document_id: documentId || '',
                  compliance_score: playbookResult.compliance_score || 0,
                  total_rules: playbookResult.total_rules || (playbookResult.results?.length || 0),
                  passed_rules: playbookResult.passed_rules || 0,
                  red_line_violations: playbookResult.red_line_violations || 0,
                  no_go_violations: playbookResult.no_go_violations || 0,
                  fallback_issues: playbookResult.fallback_issues || 0,
                  results: playbookResult.results || [],
                  summary: playbookResult.summary,
                  recommendations: playbookResult.recommendations,
                  created_at: playbookResult.created_at || new Date().toISOString()
                }}
                onClose={() => {
                  setShowResultsPanel(false)
                  setPlaybookResult(null)
                }}
                onNavigateToIssue={handleNavigateToIssue}
                onScrollToText={handleScrollToText}
                onApplyFix={handleReplaceTextInDocument}
                onRerun={() => {
                  setShowResultsPanel(false)
                  setShowPlaybookModal(true)
                }}
              />
            ) : (
              <DocumentEditorContextChat
                documentId={documentId}
                documentTitle={title}
                documentContent={content}
                onApplyEdit={handleApplyEdit}
                onInsertText={handleInsertText}
                onReplaceText={handleReplaceTextInDocument}
                onRunPlaybook={handleOpenPlaybookModal}
                caseId={caseId}
                pendingPlaybookResult={null}
                onPlaybookResultConsumed={() => {}}
                selectedText={selectedText}
                selectionRange={selectionRange}
                onClearSelection={() => {
                  setSelectedText('')
                  setSelectionRange(null)
                  editorRef.current?.clearSelectionHighlight()
                }}
                onReplaceRange={handleReplaceRange}
              />
            )}
          </div>
        )}
      </div>
      </div>

      {/* Version History Dialog */}
      {documentId && (
        <VersionHistory
          documentId={documentId}
          currentVersion={document?.version || 1}
          onVersionRestored={handleVersionRestored}
          isOpen={showVersionHistory}
          onClose={() => setShowVersionHistory(false)}
        />
      )}

      {/* Comments Panel - скрыт, т.к. перекрывает чат */}

      {/* Template Selector */}
      {caseId && (
        <TemplateSelector
          caseId={caseId}
          isOpen={showTemplateSelector}
          onClose={() => setShowTemplateSelector(false)}
        />
      )}

      {/* DOCX Importer */}
      <DocxImporter
        isOpen={showDocxImporter}
        onClose={() => setShowDocxImporter(false)}
        onImport={handleDocxImport}
      />

      {/* Playbook Modal */}
      {showPlaybookModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden">
            <div className="flex items-center justify-between p-6 border-b" style={{ borderBottomColor: 'var(--color-border)' }}>
              <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                Проверка документа с Playbook
              </h2>
              <button
                onClick={() => {
                  setShowPlaybookModal(false)
                }}
                className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
              >
                ✕
              </button>
            </div>
            
            <div className="p-6 overflow-y-auto max-h-[60vh]">
              {loadingPlaybooks ? (
                <div className="flex items-center justify-center py-8">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                </div>
              ) : playbooks.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  <BookOpen className="w-12 h-12 mx-auto mb-4 opacity-50" />
                  <p>Нет доступных Playbooks</p>
                  <button
                    onClick={() => navigate(`/cases/${caseId}/playbooks`)}
                    className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                  >
                    Создать Playbook
                  </button>
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-sm text-gray-500 mb-4">
                    Выберите Playbook для проверки документа:
                  </p>
                  {playbooks.map((pb) => (
                    <button
                      key={pb.id}
                      onClick={() => handleRunPlaybook(pb.id)}
                      disabled={runningPlaybookId !== null}
                      className="w-full p-4 border rounded-lg text-left hover:border-blue-300 hover:bg-blue-50 transition-all disabled:opacity-50"
                      style={{ borderColor: 'var(--color-border)' }}
                    >
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                            {pb.display_name}
                          </div>
                          {pb.description && (
                            <div className="text-sm text-gray-500 mt-1">{pb.description}</div>
                          )}
                          <div className="flex items-center gap-2 mt-2">
                            <span className="text-xs px-2 py-1 bg-gray-100 rounded">{pb.document_type}</span>
                            {pb.jurisdiction && (
                              <span className="text-xs px-2 py-1 bg-gray-100 rounded">{pb.jurisdiction}</span>
                            )}
                            <span className="text-xs text-gray-400">{pb.rules_count || 0} правил</span>
                          </div>
                        </div>
                        {runningPlaybookId === pb.id && (
                          <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

    </div>
  )
}

export default DocumentEditorPage

