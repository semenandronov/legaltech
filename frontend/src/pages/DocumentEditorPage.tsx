import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Save, Download, ArrowLeft, MessageSquare, FileText, Table, FileEdit, History, Upload, BookOpen, Workflow } from 'lucide-react'
import { toast } from 'sonner'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { DocumentEditor, DocumentEditorRef } from '../components/Editor/DocumentEditor'
import { AssistantUIChat } from '../components/Chat/AssistantUIChat'
import { VersionHistory } from '../components/Editor/VersionHistory'
import { CommentsPanel } from '../components/Editor/CommentsPanel'
import { TemplateSelector } from '../components/Editor/TemplateSelector'
import { DocxImporter } from '../components/Editor/DocxImporter'
import { getDocument, createDocument, updateDocument, exportDocx, exportPdf, listDocuments, Document } from '../services/documentEditorApi'
import { getPlaybooks, checkDocument as runPlaybookCheck, Playbook } from '../services/playbooksApi'
import { DocumentsList } from '../components/Editor/DocumentsList'
import { CreateDocumentScreen } from '../components/Editor/CreateDocumentScreen'
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
  const [showChat, setShowChat] = useState(false)
  const [showVersionHistory, setShowVersionHistory] = useState(false)
  const [showComments, setShowComments] = useState(false)
  const [showTemplateSelector, setShowTemplateSelector] = useState(false)
  const [showDocxImporter, setShowDocxImporter] = useState(false)
  const [comments, setComments] = useState<Array<{ id: string; from: number; to: number; text: string; createdAt?: string }>>([])
  const [showPlaybookModal, setShowPlaybookModal] = useState(false)
  const [playbooks, setPlaybooks] = useState<Playbook[]>([])
  const [loadingPlaybooks, setLoadingPlaybooks] = useState(false)
  const [runningPlaybook, setRunningPlaybook] = useState(false)
  const [playbookResult, setPlaybookResult] = useState<any>(null)
  const [showResultsPanel, setShowResultsPanel] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [documentsList, setDocumentsList] = useState<Document[]>([])
  const [loadingDocuments, setLoadingDocuments] = useState(false)
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const editorRef = useRef<DocumentEditorRef>(null)

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
  }, [content, documentId, hasUnsavedChanges])

  const handleSave = async (showToast: boolean = true) => {
    if (!caseId) return

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
  }

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

  const handleApplyEdit = (editedContent: string) => {
    // Apply edited content from AI to the document
    if (editorRef.current) {
      editorRef.current.setContent(editedContent)
      setHasUnsavedChanges(true)
      toast.success('Изменения применены к документу')
    }
  }

  const handleReplaceText = (text: string) => {
    // Replace selected text with new text
    if (editorRef.current) {
      editorRef.current.replaceSelectedText(text)
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

  const handleDocxImport = (html: string) => {
    if (editorRef.current) {
      editorRef.current.setContent(html)
      setHasUnsavedChanges(true)
    }
  }

  const handleAddComment = (from: number, to: number, text: string) => {
    if (editorRef.current) {
      editorRef.current.addComment(from, to, text)
      // Reload comments
      const updatedComments = editorRef.current.getComments()
      setComments(updatedComments)
    }
  }

  const handleRemoveComment = (id: string) => {
    if (editorRef.current) {
      editorRef.current.removeComment(id)
      // Reload comments
      const updatedComments = editorRef.current.getComments()
      setComments(updatedComments)
    }
  }

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
    
    setRunningPlaybook(true)
    try {
      const result = await runPlaybookCheck(playbookId, documentId, caseId)
      setPlaybookResult(result)
      setShowPlaybookModal(false)
      setShowResultsPanel(true)
      toast.success(`Проверка завершена! Соответствие: ${result.compliance_score?.toFixed(1) || 0}%`)
    } catch (error: any) {
      toast.error('Ошибка проверки: ' + (error.message || 'Неизвестная ошибка'))
    } finally {
      setRunningPlaybook(false)
    }
  }

  // Навигация к месту в документе
  const handleNavigateToIssue = (location: { start: number; end: number }) => {
    if (editorRef.current) {
      // Показываем уведомление о найденной позиции
      toast.info(`Найдено на позиции ${location.start}-${location.end}`)
    }
  }

  // Load comments when editor is ready
  useEffect(() => {
    if (editorRef.current) {
      const loadedComments = editorRef.current.getComments()
      setComments(loadedComments)
    }
  }, [content]) // eslint-disable-line react-hooks/exhaustive-deps

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
        {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
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

  // Show documents list or create screen if no documentId
  if (!documentId) {
    return (
      <div className="h-screen bg-bg-primary flex">
        {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
        <div className="flex-1 flex flex-col" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
          {documentsList.length === 0 ? (
            <CreateDocumentScreen caseId={caseId!} onDocumentCreated={handleDocumentCreated} />
          ) : (
            <DocumentsList
              documents={documentsList}
              caseId={caseId!}
              onDocumentSelect={handleDocumentSelect}
              onDocumentDeleted={handleDocumentDeleted}
            />
          )}
        </div>
      </div>
    )
  }

  // Show editor for specific document
  return (
    <div className="h-screen bg-bg-primary flex">
      {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
      <div className="flex-1 flex flex-col" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      {/* Toolbar */}
      <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderBottomColor: 'var(--color-border)' }}>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate(`/cases/${caseId}/editor`)}
              className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg transition-all duration-150 hover:bg-gray-100"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <ArrowLeft className="w-4 h-4" />
              Назад
            </button>
            {!documentId && (
              <button
                onClick={() => setShowTemplateSelector(true)}
                className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg transition-all duration-150 hover:bg-gray-100 border"
                style={{ 
                  color: 'var(--color-text-primary)',
                  borderColor: 'var(--color-border)'
                }}
              >
                <FileText className="w-4 h-4" />
                Создать из шаблона
              </button>
            )}
          </div>
          <div className="h-6 w-px bg-gray-300"></div>
          <input
            type="text"
            value={title}
            onChange={(e) => {
              setTitle(e.target.value)
              setHasUnsavedChanges(true)
            }}
            className="text-lg font-semibold bg-transparent border-none outline-none px-2 py-1 rounded"
            style={{ color: 'var(--color-text-primary)' }}
            placeholder="Название документа"
          />
        </div>

        <div className="flex items-center gap-2">
          {saving && (
            <span className="text-sm text-gray-500 flex items-center gap-2">
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>
              Сохранение...
            </span>
          )}
          {hasUnsavedChanges && !saving && (
            <span className="text-sm text-gray-500">Несохраненные изменения</span>
          )}
          <button
            onClick={() => handleSave()}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            <Save className="w-4 h-4" />
            Сохранить
          </button>
          <div className="relative flex gap-2">
            <button
              onClick={() => setShowDocxImporter(true)}
              disabled={saving}
              className="flex items-center gap-2 px-4 py-2 border rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
              style={{ borderColor: 'var(--color-border)' }}
              title="Импорт DOCX"
            >
              <Upload className="w-4 h-4" />
              Импорт
            </button>
            <button
              onClick={handleExportDocx}
              disabled={!documentId || saving}
              className="flex items-center gap-2 px-4 py-2 border rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
              style={{ borderColor: 'var(--color-border)' }}
            >
              <Download className="w-4 h-4" />
              DOCX
            </button>
          </div>
          <button
            onClick={handleExportPdf}
            disabled={!documentId || saving}
            className="flex items-center gap-2 px-4 py-2 border rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
            style={{ borderColor: 'var(--color-border)' }}
          >
            <Download className="w-4 h-4" />
            PDF
          </button>
          {/* Кнопка Playbooks - проверка документа */}
          <button
            onClick={handleOpenPlaybookModal}
            disabled={!documentId}
            className="flex items-center gap-2 px-4 py-2 border rounded-lg hover:bg-green-50 hover:border-green-300 disabled:opacity-50 transition-colors"
            style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
            title="Проверить документ с помощью Playbook"
          >
            <BookOpen className="w-4 h-4" style={{ color: '#10b981' }} />
            Playbook
          </button>
          {/* Кнопка чата - показывается всегда */}
          <button
            onClick={() => setShowChat(!showChat)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
              showChat
                ? 'bg-blue-100 text-blue-700'
                : 'border hover:bg-gray-50'
            }`}
            style={{ borderColor: showChat ? 'transparent' : 'var(--color-border)' }}
            title="Чат с ИИ"
          >
            <MessageSquare className="w-4 h-4" />
            Чат с ИИ
          </button>
          {documentId && (
            <button
              onClick={() => setShowVersionHistory(true)}
              className="flex items-center gap-2 px-4 py-2 border rounded-lg hover:bg-gray-50 transition-colors"
              style={{ borderColor: 'var(--color-border)' }}
              title="История версий"
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
        <div className={`flex-1 flex flex-col transition-all duration-300 ${showChat ? 'mr-96' : ''}`}>
          <DocumentEditor
            ref={editorRef}
            content={content}
            onChange={handleContentChange}
            onSelectionChange={setSelectedText}
            caseId={caseId}
            onInsertText={handleInsertText}
          />
        </div>

        {/* Chat справа */}
        {showChat && caseId && (
          <div className="w-96 border-l border-border shrink-0 bg-bg-elevated flex flex-col">
            <AssistantUIChat
              caseId={caseId}
              className="h-full"
              documentEditorMode={true}
              currentDocumentId={documentId}
              currentDocumentContent={content}
              selectedText={selectedText}
              onApplyEdit={handleApplyEdit}
              onInsertText={handleInsertText}
              onReplaceText={handleReplaceText}
              onOpenDocumentInEditor={(docId) => {
                navigate(`/cases/${caseId}/editor/${docId}`, { replace: true })
              }}
            />
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

      {/* Comments Panel */}
      <div className="fixed bottom-4 right-4 z-50">
        <CommentsPanel
          comments={comments}
          onAddComment={handleAddComment}
          onRemoveComment={handleRemoveComment}
          showPanel={showComments}
          onTogglePanel={() => setShowComments(!showComments)}
          selectedText={selectedText}
          selectedRange={editorRef.current?.getSelectedRange() || undefined}
        />
      </div>

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
                      disabled={runningPlaybook}
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
                        {runningPlaybook && (
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

      {/* Playbook Results Panel */}
      {showResultsPanel && playbookResult && (
        <PlaybookResultsPanel
          result={{
            id: playbookResult.id || 'temp',
            playbook_id: playbookResult.playbook_id || '',
            playbook_name: playbookResult.playbook_name || 'Playbook',
            document_id: documentId || '',
            compliance_score: playbookResult.compliance_score || 0,
            total_rules: playbookResult.total_rules || 0,
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
          onRerun={() => {
            setShowResultsPanel(false)
            setShowPlaybookModal(true)
          }}
        />
      )}
    </div>
  )
}

export default DocumentEditorPage

