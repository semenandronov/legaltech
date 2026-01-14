import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Save, Download, Sparkles, ArrowLeft, MessageSquare, FileText, Table, FileEdit, History, Upload } from 'lucide-react'
import { toast } from 'sonner'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { DocumentEditor, DocumentEditorRef } from '../components/Editor/DocumentEditor'
import { AIAssistantSidebar } from '../components/Editor/AIAssistantSidebar'
import { DocumentChat } from '../components/Editor/DocumentChat'
import { VersionHistory } from '../components/Editor/VersionHistory'
import { CommentsPanel } from '../components/Editor/CommentsPanel'
import { TemplateSelector } from '../components/Editor/TemplateSelector'
import { DocxImporter } from '../components/Editor/DocxImporter'
import { getDocument, createDocument, updateDocument, exportDocx, exportPdf } from '../services/documentEditorApi'

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
  const [showAISidebar, setShowAISidebar] = useState(false)
  const [isChatOpen, setIsChatOpen] = useState(false)
  const [showVersionHistory, setShowVersionHistory] = useState(false)
  const [showComments, setShowComments] = useState(false)
  const [showTemplateSelector, setShowTemplateSelector] = useState(false)
  const [showDocxImporter, setShowDocxImporter] = useState(false)
  const [comments, setComments] = useState<Array<{ id: string; from: number; to: number; text: string; createdAt?: string }>>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const editorRef = useRef<DocumentEditorRef>(null)

  // Load document if documentId is provided
  useEffect(() => {
    if (!caseId) {
      toast.error('Дело не найдено')
      navigate('/cases')
      return
    }

    const loadDocument = async () => {
      if (documentId) {
        try {
          setLoading(true)
          const doc = await getDocument(documentId)
          setDocument(doc)
          setTitle(doc.title)
          setContent(doc.content || '')
        } catch (error: any) {
          toast.error(error.message || 'Ошибка при загрузке документа')
          navigate(`/cases/${caseId}/documents`)
        } finally {
          setLoading(false)
        }
      } else {
        // New document
        setLoading(false)
        setDocument(null)
        setContent('')
        setTitle('Новый документ')
      }
    }

    loadDocument()
  }, [caseId, documentId, navigate])

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

  // Load comments when editor is ready
  useEffect(() => {
    if (editorRef.current) {
      const loadedComments = editorRef.current.getComments()
      setComments(loadedComments)
    }
  }, [content, editorRef.current])

  const navItems = caseId ? [
    { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
    { id: 'documents', label: 'Документы', icon: FileText, path: `/cases/${caseId}/documents` },
    { id: 'editor', label: 'Редактор', icon: FileEdit, path: `/cases/${caseId}/editor` },
    { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
  ] : []

  if (loading) {
    return (
      <div className="h-screen bg-bg-primary flex">
        {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
            <p className="text-gray-600">Загрузка документа...</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen bg-bg-primary flex">
      {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
      <div className="flex-1 flex flex-col" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      {/* Toolbar */}
      <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderBottomColor: 'var(--color-border)' }}>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate(`/cases/${caseId}/documents`)}
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
          {/* Кнопка чата - показывается только если есть documentId */}
          {documentId && (
            <button
              onClick={() => setIsChatOpen(!isChatOpen)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                isChatOpen
                  ? 'bg-blue-100 text-blue-700'
                  : 'border hover:bg-gray-50'
              }`}
              style={{ borderColor: isChatOpen ? 'transparent' : 'var(--color-border)' }}
              title="Чат с ИИ"
            >
              <MessageSquare className="w-4 h-4" />
              Чат
            </button>
          )}
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
          <button
            onClick={() => setShowAISidebar(!showAISidebar)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
              showAISidebar
                ? 'bg-blue-100 text-blue-700'
                : 'border hover:bg-gray-50'
            }`}
            style={{ borderColor: showAISidebar ? 'transparent' : 'var(--color-border)' }}
            title="Быстрые действия ИИ"
          >
            <Sparkles className="w-4 h-4" />
            AI
          </button>
        </div>
      </div>

      {/* Main content area */}
      <div className="flex-1 overflow-hidden flex">
        {/* Chat panel (Left) - показывается когда isChatOpen === true и есть documentId */}
        {isChatOpen && documentId && (
          <div className="w-80 border-r border-border shrink-0 bg-bg-elevated flex flex-col">
            <DocumentChat
              documentId={documentId}
              documentTitle={title}
              onApplyEdit={handleApplyEdit}
            />
          </div>
        )}

        {/* Editor and AI Sidebar */}
        <div className="flex-1 overflow-hidden flex">
          {/* Editor */}
          <div className={`flex-1 flex flex-col transition-all duration-300 ${showAISidebar ? 'mr-80' : ''}`}>
            <DocumentEditor
              ref={editorRef}
              content={content}
              onChange={handleContentChange}
              onSelectionChange={setSelectedText}
              caseId={caseId}
              onInsertText={handleInsertText}
            />
          </div>

          {/* AI Sidebar (Quick Actions) */}
          {showAISidebar && (
            <AIAssistantSidebar
              caseId={caseId}
              documentId={documentId}
              selectedText={selectedText}
              onInsertText={handleInsertText}
              onReplaceText={handleReplaceText}
            />
          )}
        </div>
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
    </div>
  )
}

export default DocumentEditorPage

