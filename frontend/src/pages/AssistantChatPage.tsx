import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { AssistantUIChat } from '../components/Chat/AssistantUIChat'
import { ChatHistoryPanel } from '../components/Chat/ChatHistoryPanel'
import { 
  DropdownMenu, 
  DropdownMenuContent, 
  DropdownMenuItem, 
  DropdownMenuTrigger 
} from '../components/UI/dropdown-menu'
import { ChevronDown, Upload, Share2, History, FileText, Download, MessageSquare, MoreVertical } from 'lucide-react'
import { toast } from 'sonner'
import { getCase } from '../services/api'

const AssistantChatPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [historyPanelOpen, setHistoryPanelOpen] = useState(false)
  const [selectedQuery, setSelectedQuery] = useState<string>('')
  const [caseInfo, setCaseInfo] = useState<{ title?: string; documentCount?: number } | null>(null)
  const [isLoadingCaseInfo, setIsLoadingCaseInfo] = useState(true)
  const chatRef = useRef<{ clearMessages: () => void } | null>(null)

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

  const handleUploadDocuments = () => {
    navigate(`/cases/${caseId}/documents`)
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
    if (window.confirm('Вы уверены, что хотите начать новый чат? Текущая история будет очищена.')) {
      chatRef.current?.clearMessages()
      toast.success('Новый чат начат')
    }
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
    <div className="h-full w-full flex flex-col fade-in-up relative">
      {/* Top toolbar */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-gray-200 bg-white">
        <div className="flex items-center gap-4">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors">
                <FileText className="w-4 h-4" />
                Документы
                <ChevronDown className="w-4 h-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem onClick={() => navigate(`/cases/${caseId}/documents`)}>
                <FileText className="w-4 h-4 mr-2" />
                Просмотр документов
              </DropdownMenuItem>
              <DropdownMenuItem onClick={handleUploadDocuments}>
                <Upload className="w-4 h-4 mr-2" />
                Загрузить документы
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors">
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
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
            title="Начать новый чат"
          >
            <MessageSquare className="w-4 h-4" />
            <span className="hidden sm:inline">Новый чат</span>
          </button>
          <button 
            onClick={handleExport}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
            title="Экспортировать историю"
          >
            <Download className="w-4 h-4" />
            <span className="hidden sm:inline">Экспорт</span>
          </button>
          <button 
            onClick={handleShare}
            className="px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
            title="Скопировать ссылку на чат"
          >
            <Share2 className="w-4 h-4" />
          </button>
          <button 
            onClick={() => setHistoryPanelOpen(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <History className="w-4 h-4" />
            <span className="hidden sm:inline">История</span>
          </button>
        </div>
      </div>

      {/* Main chat area */}
      <div className="flex-1 overflow-hidden">
        <AssistantUIChat 
          caseId={caseId} 
          className="h-full"
          initialQuery={selectedQuery}
          onQuerySelected={() => setSelectedQuery('')}
          caseTitle={caseInfo?.title}
          documentCount={caseInfo?.documentCount}
          isLoadingCaseInfo={isLoadingCaseInfo}
          ref={chatRef}
        />
      </div>

      {/* History panel */}
      <ChatHistoryPanel
        isOpen={historyPanelOpen}
        onClose={() => setHistoryPanelOpen(false)}
        currentCaseId={caseId}
        onSelectQuery={handleSelectQuery}
      />
    </div>
  )
}

export default AssistantChatPage


