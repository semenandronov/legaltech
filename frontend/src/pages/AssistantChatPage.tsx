import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { AssistantUIChat } from '../components/Chat/AssistantUIChat'
import { ChatHistoryPanel } from '../components/Chat/ChatHistoryPanel'
import { DocumentsPanel } from '../components/Chat/DocumentsPanel'
import { 
  DropdownMenu, 
  DropdownMenuContent, 
  DropdownMenuItem, 
  DropdownMenuTrigger 
} from '../components/UI/dropdown-menu'
import { ChevronDown, Share2, History, FileText, Download, MessageSquare, MoreVertical } from 'lucide-react'
import { toast } from 'sonner'
import { getCase } from '../services/api'

const AssistantChatPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [historyPanelOpen, setHistoryPanelOpen] = useState(false)
  const [documentsPanelOpen, setDocumentsPanelOpen] = useState(false)
  const [selectedQuery, setSelectedQuery] = useState<string>('')
  const [caseInfo, setCaseInfo] = useState<{ title?: string; documentCount?: number } | null>(null)
  const [isLoadingCaseInfo, setIsLoadingCaseInfo] = useState(true)
  const chatRef = useRef<{ clearMessages: () => void; loadHistory: () => Promise<void> } | null>(null)

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

  if (!caseId) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-body text-[#6B7280]">Дело не найдено</p>
      </div>
    )
  }

  const handleSelectQuery = (query: string) => {
    setSelectedQuery(query)
    setHistoryPanelOpen(false)
  }

  const handleShare = async () => {
    try {
      const url = window.location.href
      await navigator.clipboard.writeText(url)
      toast.success('Ссылка на чат скопирована в буфер обмена')
    } catch (error) {
      console.error('Ошибка при копировании URL:', error)
      toast.error('Не удалось скопировать ссылку')
    }
  }

  const handleNewChat = () => {
    chatRef.current?.clearMessages()
    toast.success('Новый чат начат')
  }

  const handleExport = async () => {
    try {
      const token = localStorage.getItem('access_token')
      const apiUrl = import.meta.env.VITE_API_URL || ''
      const baseUrl = apiUrl.endsWith('/') ? apiUrl.slice(0, -1) : apiUrl
      const response = await fetch(`${baseUrl}/api/chat/${caseId}/export?format=markdown`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      })

      if (!response.ok) {
        throw new Error('Ошибка экспорта')
      }

      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `chat-history-${caseId}-${new Date().toISOString().split('T')[0]}.md`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
      toast.success('История чата экспортирована')
    } catch (error) {
      console.error('Ошибка при экспорте:', error)
      toast.error('Не удалось экспортировать историю')
    }
  }

  return (
    <div 
      className="h-full w-full flex flex-col relative animate-fade-in"
      style={{ backgroundColor: 'var(--color-bg-primary)' }}
    >
      {/* Top toolbar */}
      <div 
        className="flex items-center justify-between px-6 py-3 border-b"
        style={{ 
          padding: 'var(--space-3) var(--space-6)',
          borderBottomColor: 'var(--color-border)',
          backgroundColor: 'var(--color-bg-primary)'
        }}
      >
        <div className="flex items-center gap-4">
          <button
            onClick={() => setDocumentsPanelOpen(!documentsPanelOpen)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg transition-all duration-150"
            style={{
              color: 'var(--color-text-secondary)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
              e.currentTarget.style.color = 'var(--color-text-primary)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent'
              e.currentTarget.style.color = 'var(--color-text-secondary)'
            }}
            title="Открыть панель документов"
          >
            <FileText className="w-4 h-4" />
            Документы
          </button>
          
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button 
                className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg transition-all duration-150"
                style={{
                  color: 'var(--color-text-secondary)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
                  e.currentTarget.style.color = 'var(--color-text-primary)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent'
                  e.currentTarget.style.color = 'var(--color-text-secondary)'
                }}
              >
                <MoreVertical className="w-4 h-4" />
                Еще
                <ChevronDown className="w-4 h-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem onClick={() => navigate(`/cases/${caseId}/tabular-review`)}>
                Tabular Review
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate(`/cases/${caseId}/analysis`)}>
                Анализ
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate(`/cases/${caseId}/contradictions`)}>
                Противоречия
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate(`/cases/${caseId}/reports`)}>
                Отчеты
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <div className="flex items-center gap-2">
          <button 
            onClick={handleNewChat}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg transition-all duration-150"
            style={{
              color: 'var(--color-text-secondary)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
              e.currentTarget.style.color = 'var(--color-text-primary)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent'
              e.currentTarget.style.color = 'var(--color-text-secondary)'
            }}
            title="Начать новый чат"
          >
            <MessageSquare className="w-4 h-4" />
            <span className="hidden sm:inline">Новый чат</span>
          </button>
          <button 
            onClick={handleExport}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg transition-all duration-150"
            style={{
              color: 'var(--color-text-secondary)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
              e.currentTarget.style.color = 'var(--color-text-primary)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent'
              e.currentTarget.style.color = 'var(--color-text-secondary)'
            }}
            title="Экспортировать историю"
          >
            <Download className="w-4 h-4" />
            <span className="hidden sm:inline">Экспорт</span>
          </button>
          <button 
            onClick={handleShare}
            className="px-3 py-1.5 text-sm font-medium rounded-lg transition-all duration-150"
            style={{
              color: 'var(--color-text-secondary)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
              e.currentTarget.style.color = 'var(--color-text-primary)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent'
              e.currentTarget.style.color = 'var(--color-text-secondary)'
            }}
            title="Скопировать ссылку на чат"
          >
            <Share2 className="w-4 h-4" />
          </button>
          <button 
            onClick={() => setHistoryPanelOpen(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg transition-all duration-150"
            style={{
              color: 'var(--color-text-secondary)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
              e.currentTarget.style.color = 'var(--color-text-primary)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent'
              e.currentTarget.style.color = 'var(--color-text-secondary)'
            }}
          >
            <History className="w-4 h-4" />
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
            onDocumentDrop={(documentFilename) => {
              // Добавляем имя документа в поле ввода
              if (chatRef.current) {
                // Можно добавить логику для добавления документа в сообщение
                toast.info(`Документ "${documentFilename}" добавлен`)
              }
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
        onLoadHistory={async () => {
          if (chatRef.current) {
            await chatRef.current.loadHistory()
          }
        }}
      />
    </div>
  )
}

export default AssistantChatPage


