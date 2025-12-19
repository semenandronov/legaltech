import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Sidebar from '../components/Layout/Sidebar'
import Header from '../components/Layout/Header'
import WorkspaceLayout from '../components/Workspace/WorkspaceLayout'
import DocumentOverview from '../components/Documents/DocumentOverview'
import DocumentFilters, { DocumentFiltersState } from '../components/Documents/DocumentFilters'
import DocumentsList, { DocumentWithMetadata } from '../components/Documents/DocumentsList'
import DocumentViewer from '../components/Documents/DocumentViewer'
import ChatWindow from '../components/ChatWindow'
import {
  getCase,
  getDocuments,
  getClassifications,
  getPrivilegeChecks,
  DocumentItem,
  DocumentClassification,
  PrivilegeCheck
} from '../services/api'
import './CaseWorkspacePage.css'

const CaseWorkspacePage: React.FC = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()
  
  const [caseData, setCaseData] = useState<any>(null)
  const [documents, setDocuments] = useState<DocumentWithMetadata[]>([])
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null)
  const [selectedDocuments, setSelectedDocuments] = useState<Set<string>>(new Set())
  const [rightPanelCollapsed, setRightPanelCollapsed] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  
  const [filters, setFilters] = useState<DocumentFiltersState>({
    searchQuery: '',
    docTypes: [],
    privilegeStatus: [],
    relevanceRange: [0, 100],
    confidenceLevels: [],
    statuses: []
  })

  useEffect(() => {
    if (caseId) {
      loadCaseData()
    }
  }, [caseId])

  useEffect(() => {
    if (caseId) {
      loadDocuments()
    }
  }, [caseId, filters])

  const loadCaseData = async () => {
    if (!caseId) return
    try {
      const data = await getCase(caseId)
      setCaseData(data)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка при загрузке дела')
    }
  }

  const loadDocuments = async () => {
    if (!caseId) return
    setLoading(true)
    try {
      // Загружаем документы
      const docsResponse = await getDocuments(caseId)
      let docs: DocumentWithMetadata[] = docsResponse.documents.map((doc: DocumentItem) => ({
        ...doc,
        confidence: undefined,
        status: undefined
      }))

      // Загружаем классификации
      try {
        const classificationsResponse = await getClassifications(caseId)
        const classificationsMap = new Map<string, DocumentClassification>()
        classificationsResponse.classifications.forEach((c: DocumentClassification) => {
          classificationsMap.set(c.file_id, c)
        })

        // Загружаем проверки привилегий
        const privilegeResponse = await getPrivilegeChecks(caseId)
        const privilegeMap = new Map<string, PrivilegeCheck>()
        privilegeResponse.privilege_checks.forEach((p: PrivilegeCheck) => {
          privilegeMap.set(p.file_id, p)
        })

        // Объединяем данные
        docs = docs.map(doc => {
          const classification = classificationsMap.get(doc.id)
          const privilegeCheck = privilegeMap.get(doc.id)
          const confidence = classification?.confidence || privilegeCheck?.confidence || 0
          
          return {
            ...doc,
            classification,
            privilegeCheck,
            confidence: typeof confidence === 'string' ? parseFloat(confidence) : confidence,
            status: privilegeCheck?.is_privileged ? 'privileged' : undefined
          }
        })

      } catch (err) {
        console.warn('Ошибка при загрузке классификаций:', err)
      }

      // Применяем фильтры
      let filteredDocs = docs
      
      if (filters.searchQuery) {
        const query = filters.searchQuery.toLowerCase()
        filteredDocs = filteredDocs.filter(doc => 
          doc.filename.toLowerCase().includes(query)
        )
      }

      if (filters.docTypes.length > 0) {
        filteredDocs = filteredDocs.filter(doc => 
          doc.classification && filters.docTypes.includes(doc.classification.doc_type)
        )
      }

      if (filters.privilegeStatus.length > 0 && !filters.privilegeStatus.includes('All')) {
        filteredDocs = filteredDocs.filter(doc => {
          const isPrivileged = doc.privilegeCheck?.is_privileged || doc.classification?.is_privileged || false
          if (filters.privilegeStatus.includes('Privileged')) {
            return isPrivileged
          }
          if (filters.privilegeStatus.includes('Not Privileged')) {
            return !isPrivileged
          }
          return true
        })
      }

      if (filters.relevanceRange[0] > 0 || filters.relevanceRange[1] < 100) {
        filteredDocs = filteredDocs.filter(doc => {
          const score = doc.classification?.relevance_score || 0
          return score >= filters.relevanceRange[0] && score <= filters.relevanceRange[1]
        })
      }

      // Сортировка
      if (filters.searchQuery || filters.docTypes.length > 0) {
        // Если есть активные фильтры, сортируем по релевантности
        filteredDocs.sort((a, b) => {
          const scoreA = a.classification?.relevance_score || 0
          const scoreB = b.classification?.relevance_score || 0
          return scoreB - scoreA
        })
      } else {
        // Иначе по дате
        filteredDocs.sort((a, b) => {
          const dateA = new Date(a.created_at).getTime()
          const dateB = new Date(b.created_at).getTime()
          return dateB - dateA
        })
      }

      setDocuments(filteredDocs)
      
      // Автоматически выбираем первый документ если нет выбранного
      if (!selectedDocumentId && filteredDocs.length > 0) {
        setSelectedDocumentId(filteredDocs[0].id)
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка при загрузке документов')
    } finally {
      setLoading(false)
    }
  }

  const handleDocumentClick = (fileId: string) => {
    setSelectedDocumentId(fileId)
  }

  const handleSelectDocument = (fileId: string, selected: boolean) => {
    setSelectedDocuments(prev => {
      const newSet = new Set(prev)
      if (selected) {
        newSet.add(fileId)
      } else {
        newSet.delete(fileId)
      }
      return newSet
    })
  }

  const handleBatchAction = async (action: string, fileIds: string[]) => {
    if (!caseId) return
    try {
      // TODO: Реализовать batch actions через API
      console.log(`Batch action: ${action}`, fileIds)
      // После успешного действия очистить выбор
      setSelectedDocuments(new Set())
    } catch (err: any) {
      setError(err.response?.data?.detail || `Ошибка при выполнении ${action}`)
    }
  }

  const handleClearFilters = () => {
    setFilters({
      searchQuery: '',
      docTypes: [],
      privilegeStatus: [],
      relevanceRange: [0, 100],
      confidenceLevels: [],
      statuses: []
    })
  }

  const handleSaveView = (name: string) => {
    // TODO: Сохранить фильтры как View
    console.log('Saving view:', name, filters)
  }

  const handleDownloadAuditLog = () => {
    // TODO: Реализовать скачивание audit log
    console.log('Downloading audit log')
  }

  if (!caseId) {
    return <div>Дело не найдено</div>
  }

  if (loading && documents.length === 0) {
    return (
      <div className="dashboard-root">
        <Sidebar />
        <div className="dashboard-content">
          <Header />
          <main className="dashboard-main">
            <div className="loading-state">Загрузка документов...</div>
          </main>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="dashboard-root">
        <Sidebar />
        <div className="dashboard-content">
          <Header />
          <main className="dashboard-main">
            <div className="error-state">Ошибка: {error}</div>
          </main>
        </div>
      </div>
    )
  }

  // Вычисляем статистику
  const totalFiles = documents.length
  const relevantCount = documents.filter(d => (d.classification?.relevance_score || 0) > 70).length
  const privilegedCount = documents.filter(d => 
    d.privilegeCheck?.is_privileged || d.classification?.is_privileged
  ).length
  const notRelevantCount = documents.filter(d => (d.classification?.relevance_score || 0) < 30).length

  const selectedDocument = documents.find(d => d.id === selectedDocumentId) || null

  // Левая панель
  const leftPanel = (
    <div className="workspace-left-content">
      <DocumentOverview
        totalFiles={totalFiles}
        relevantCount={relevantCount}
        privilegedCount={privilegedCount}
        notRelevantCount={notRelevantCount}
        onDownloadAuditLog={handleDownloadAuditLog}
      />
      <DocumentFilters
        filters={filters}
        onFiltersChange={setFilters}
        onClearFilters={handleClearFilters}
        onSaveView={handleSaveView}
      />
      <DocumentsList
        documents={documents}
        selectedDocuments={selectedDocuments}
        onSelectDocument={handleSelectDocument}
        onDocumentClick={handleDocumentClick}
        onBatchAction={handleBatchAction}
        sortBy="date"
      />
    </div>
  )

  // Центральная панель
  const centerPanel = (
    <DocumentViewer
      document={selectedDocument}
      caseId={caseId}
      onNavigateNext={() => {
        const currentIndex = documents.findIndex(d => d.id === selectedDocumentId)
        if (currentIndex < documents.length - 1) {
          setSelectedDocumentId(documents[currentIndex + 1].id)
        }
      }}
      onNavigatePrev={() => {
        const currentIndex = documents.findIndex(d => d.id === selectedDocumentId)
        if (currentIndex > 0) {
          setSelectedDocumentId(documents[currentIndex - 1].id)
        }
      }}
    />
  )

  // Правая панель (Chat)
  const rightPanel = (
    <ChatWindow
      caseId={caseId}
      fileNames={caseData?.file_names || []}
      onDocumentClick={(filename) => {
        // Найти документ по имени и открыть его
        const doc = documents.find(d => d.filename === filename)
        if (doc) {
          setSelectedDocumentId(doc.id)
        }
      }}
    />
  )

  return (
    <div className="dashboard-root">
      <Sidebar />
      <div className="dashboard-content workspace-content">
        <Header />
        <main className="dashboard-main workspace-main">
          <div className="workspace-header">
            <button className="workspace-back-btn" onClick={() => navigate('/')}>
              ← Назад к Dashboard
            </button>
            <h1 className="workspace-title">
              {caseData?.title || `Дело #${caseId.slice(0, 8)}`}
            </h1>
          </div>
          <WorkspaceLayout
            leftPanel={leftPanel}
            centerPanel={centerPanel}
            rightPanel={rightPanel}
            rightPanelCollapsed={rightPanelCollapsed}
            onToggleRightPanel={() => setRightPanelCollapsed(!rightPanelCollapsed)}
          />
        </main>
      </div>
    </div>
  )
}

export default CaseWorkspacePage
