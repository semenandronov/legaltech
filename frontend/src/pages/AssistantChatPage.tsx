import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { AssistantUIChat, AssistantUIChatRef } from '../components/Chat/AssistantUIChat'
import { ChatHistoryPanel } from '../components/Chat/ChatHistoryPanel'
import { DocumentsPanel } from '../components/Chat/DocumentsPanel'
import { History, FileText, MessageSquare } from 'lucide-react'
import { toast } from 'sonner'
import { getCase } from '../services/api'
import { 
  consumePendingWorkflowResult, 
  createWorkflowResultChatMessage,
  saveWorkflowMessageToHistory
} from '../services/workflowResultsService'

const AssistantChatPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [historyPanelOpen, setHistoryPanelOpen] = useState(false)
  const [documentsPanelOpen, setDocumentsPanelOpen] = useState(false)
  const [selectedQuery, setSelectedQuery] = useState<string>('')
  const [caseInfo, setCaseInfo] = useState<{ title?: string; documentCount?: number } | null>(null)
  const [isLoadingCaseInfo, setIsLoadingCaseInfo] = useState(true)
  const chatRef = useRef<AssistantUIChatRef | null>(null)
  const workflowResultProcessed = useRef(false)

  // Load case info
  useEffect(() => {
    if (!caseId) return

    const loadCaseInfo = async () => {
      setIsLoadingCaseInfo(true)
      try {
        const caseData = await getCase(caseId)
        setCaseInfo({
          title: caseData.title || undefined,
          documentCount: caseData.num_documents,
        })
      } catch (error) {
        console.error('Error loading case info:', error)
      } finally {
        setIsLoadingCaseInfo(false)
      }
    }

    loadCaseInfo()
  }, [caseId])

  // Handle deep linking
  useEffect(() => {
    const fileParam = searchParams.get('file')
    const tableParam = searchParams.get('table')
    
    if (fileParam) {
      // Navigate to documents page with file highlighted
      navigate(`/cases/${caseId}/documents?file=${encodeURIComponent(fileParam)}`, { replace: true })
    } else if (tableParam) {
      // Navigate to tabular review with table highlighted
      navigate(`/cases/${caseId}/tabular-review?table=${encodeURIComponent(tableParam)}`, { replace: true })
    }
  }, [searchParams, caseId, navigate])

  // Handle pending workflow result - показать результаты workflow в чате
  useEffect(() => {
    // Задержка чтобы chatRef успел инициализироваться
    const timer = setTimeout(async () => {
      if (workflowResultProcessed.current) return
      
      const pendingResult = consumePendingWorkflowResult()
      if (pendingResult && pendingResult.case_id === caseId && chatRef.current) {
        workflowResultProcessed.current = true
        
        // Очищаем чат и добавляем результат workflow
        chatRef.current.clearMessages()
        
        const message = createWorkflowResultChatMessage(pendingResult)
        chatRef.current.addMessage(message)
        
        // Сохраняем сообщение в историю на сервере
        try {
          const saveResult = await saveWorkflowMessageToHistory(pendingResult)
          if (saveResult.success) {
            console.log('Workflow message saved to history, session:', saveResult.session_id)
          }
        } catch (error) {
          console.error('Failed to save workflow message to history:', error)
        }
        
        // Показываем уведомление
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
    }, 500) // Небольшая задержка для инициализации

    return () => clearTimeout(timer)
  }, [caseId])

  if (!caseId) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-body text-[#6B7280]">Дело не найдено</p>
      </div>
    )
  }

  const handleSelectQuery = (query: string, _sessionId?: string) => {
    setSelectedQuery(query)
    setHistoryPanelOpen(false)
  }

  const handleNewChat = () => {
    chatRef.current?.clearMessages()
    toast.success('Новый чат начат')
  }

  return (
    <div 
      className="h-full w-full flex flex-col relative animate-fade-in"
      style={{ backgroundColor: 'var(--color-bg-primary)' }}
    >
      {/* Top toolbar */}
      <div 
        className="flex items-center justify-between px-6 py-6 border-b"
        style={{ 
          padding: 'var(--space-6) var(--space-6)',
          borderBottomColor: 'var(--color-border)',
          backgroundColor: 'var(--color-bg-primary)'
        }}
      >
        <div className="flex items-center gap-4">
          <button
            onClick={() => setDocumentsPanelOpen(!documentsPanelOpen)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg transition-all duration-150 text-[color:var(--color-text-secondary)] hover:bg-[color:var(--color-bg-hover)] hover:text-[color:var(--color-text-primary)]"
            aria-label="Открыть панель документов"
            aria-expanded={documentsPanelOpen}
          >
            <FileText className="w-4 h-4" aria-hidden="true" />
            Документы
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button 
            onClick={handleNewChat}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg transition-all duration-150 text-[color:var(--color-text-secondary)] hover:bg-[color:var(--color-bg-hover)] hover:text-[color:var(--color-text-primary)]"
            aria-label="Начать новый чат"
          >
            <MessageSquare className="w-4 h-4" aria-hidden="true" />
            <span className="hidden sm:inline">Новый чат</span>
          </button>
          <button 
            onClick={() => setHistoryPanelOpen(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg transition-all duration-150 text-[color:var(--color-text-secondary)] hover:bg-[color:var(--color-bg-hover)] hover:text-[color:var(--color-text-primary)]"
            aria-label="Открыть историю чатов"
            aria-expanded={historyPanelOpen}
          >
            <History className="w-4 h-4" aria-hidden="true" />
            <span className="hidden sm:inline">История</span>
          </button>
        </div>
      </div>

      {/* Main chat area with documents panel */}
      <div className="flex-1 overflow-hidden flex relative">
        <div className={`flex-1 transition-all duration-300 ${documentsPanelOpen ? 'mr-80' : ''}`}>
          <AssistantUIChat 
            caseId={caseId} 
            className="h-full"
            initialQuery={selectedQuery}
            onQuerySelected={() => setSelectedQuery('')}
            caseTitle={caseInfo?.title}
            documentCount={caseInfo?.documentCount}
            isLoadingCaseInfo={isLoadingCaseInfo}
            onDocumentDrop={() => {
              // Документ уже добавлен через attachments API, визуальная индикация через PromptInputAttachments
              // Уведомление не нужно, так как файл виден под полем ввода
            }}
            ref={chatRef}
          />
        </div>

        {/* Documents Panel - узкое окно справа */}
        <DocumentsPanel
          isOpen={documentsPanelOpen}
          onClose={() => setDocumentsPanelOpen(false)}
          caseId={caseId}
          onDocumentClick={(document) => {
            // Открываем документ справа в панели предпросмотра через AssistantUIChat
            // Это будет обработано через DocumentPreviewSheet в AssistantUIChat
            // Пока что просто показываем уведомление
            toast.info(`Документ "${document.filename}" выбран. Перетащите его в чат для добавления.`)
          }}
        />
      </div>

      {/* History panel */}
      <ChatHistoryPanel
        isOpen={historyPanelOpen}
        onClose={() => setHistoryPanelOpen(false)}
        currentCaseId={caseId}
        onSelectQuery={handleSelectQuery}
        onLoadHistory={async (sessionId?: string) => {
          if (chatRef.current) {
            await chatRef.current.loadHistory(sessionId)
          }
        }}
      />
    </div>
  )
}

export default AssistantChatPage


