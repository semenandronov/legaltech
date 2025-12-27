import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Box,
  Button,
  Typography,
  Stack,
  Paper,
  Alert,
  CircularProgress,
  Container,
} from '@mui/material'
import {
  ArrowBack as ArrowBackIcon,
} from '@mui/icons-material'
import MainLayout from '../components/Layout/MainLayout'
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
  batchConfirm,
  batchReject,
  batchWithhold,
  DocumentItem,
  DocumentClassification,
  PrivilegeCheck
} from '../services/api'

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
    if (!caseId || fileIds.length === 0) return
    try {
      setLoading(true)
      setError(null)

      let response
      switch (action) {
        case 'confirm':
          response = await batchConfirm(caseId, fileIds)
          break
        case 'reject':
          response = await batchReject(caseId, fileIds)
          break
        case 'withhold':
          response = await batchWithhold(caseId, fileIds)
          break
        default:
          throw new Error(`Неизвестное действие: ${action}`)
      }

      // После успешного действия очистить выбор и перезагрузить документы
      setSelectedDocuments(new Set())
      await loadDocuments()
      
      // Показать сообщение об успехе (можно добавить toast notification)
      console.log(`Успешно: ${response.message || action}`)
    } catch (err: any) {
      setError(err.response?.data?.detail || `Ошибка при выполнении ${action}`)
    } finally {
      setLoading(false)
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
      <MainLayout>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
          }}
        >
          <CircularProgress />
        </Box>
      </MainLayout>
    )
  }

  if (error) {
    return (
      <MainLayout>
        <Container>
          <Alert severity="error" sx={{ mt: 2 }}>
            Ошибка: {error}
          </Alert>
        </Container>
      </MainLayout>
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
    <Stack
      spacing={2}
      sx={{
        height: '100%',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
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
      <Box sx={{ flexGrow: 1, overflow: 'auto' }}>
        <DocumentsList
          documents={documents}
          selectedDocuments={selectedDocuments}
          onSelectDocument={handleSelectDocument}
          onDocumentClick={handleDocumentClick}
          onBatchAction={handleBatchAction}
          sortBy="date"
        />
      </Box>
    </Stack>
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
      onRelatedDocumentClick={(fileId) => {
        setSelectedDocumentId(fileId)
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
    <MainLayout>
      <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        {/* Header */}
        <Paper
          elevation={0}
          sx={{
            p: 2,
            borderBottom: '1px solid',
            borderColor: 'divider',
            bgcolor: 'background.paper',
          }}
        >
          <Stack direction="row" spacing={2} alignItems="center">
            <Button
              startIcon={<ArrowBackIcon />}
              onClick={() => navigate('/')}
              variant="outlined"
              size="small"
              sx={{ textTransform: 'none' }}
            >
              Назад к Dashboard
            </Button>
            <Typography variant="h5" component="h1" sx={{ fontWeight: 600 }}>
              {caseData?.title || `Дело #${caseId.slice(0, 8)}`}
            </Typography>
          </Stack>
        </Paper>

        {/* Workspace Layout */}
        <Box sx={{ flexGrow: 1, overflow: 'hidden' }}>
          <WorkspaceLayout
            leftPanel={leftPanel}
            centerPanel={centerPanel}
            rightPanel={rightPanel}
            rightPanelCollapsed={rightPanelCollapsed}
            onToggleRightPanel={() => setRightPanelCollapsed(!rightPanelCollapsed)}
          />
        </Box>
      </Box>
    </MainLayout>
  )
}

export default CaseWorkspacePage
