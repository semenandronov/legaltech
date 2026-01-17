import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import {
  Box,
  Typography,
  CircularProgress,
  IconButton,
  Drawer,
} from '@mui/material'
import { Description as DescriptionIcon, Close as CloseIcon, OpenInNew as OpenInNewIcon } from '@mui/icons-material'
import { MessageSquare, FileText, Table, Filter, FileEdit, BookOpen, Workflow, CheckCircle, XCircle, AlertTriangle, X, Loader2, ChevronRight } from 'lucide-react'
import { toast } from 'sonner'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import DocumentViewer from '../components/Documents/DocumentViewer'
import DocumentFilters, { DocumentFiltersState } from '../components/Documents/DocumentFilters'
import { DocumentWithMetadata } from '../components/Documents/DocumentsList'
import * as playbooksApi from '../services/playbooksApi'
import type { Playbook, PlaybookCheck} from '../services/playbooksApi'

interface DocumentClassification {
  doc_type: string
  relevance_score: number
  is_privileged: boolean
  privilege_type: string
  key_topics: string[]
  confidence: number
  reasoning?: string
  needs_human_review: boolean
}

interface DocumentFile {
  id: string
  filename: string
  file_type?: string
  status?: string
  created_at?: string
  classification?: DocumentClassification
}

const DocumentsPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const [documents, setDocuments] = useState<DocumentFile[]>([])
  const [filteredDocuments, setFilteredDocuments] = useState<DocumentFile[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedDocument, setSelectedDocument] = useState<DocumentFile | null>(null)
  const [selectedDocumentIndex, setSelectedDocumentIndex] = useState<number | null>(null)
  const [showFilters, setShowFilters] = useState(false)
  const [filters, setFilters] = useState<DocumentFiltersState>({
    searchQuery: '',
    docTypes: [],
    privilegeStatus: [],
    relevanceRange: [0, 100],
    confidenceLevels: [],
    statuses: []
  })
  
  // Playbooks state
  const [playbooks, setPlaybooks] = useState<Playbook[]>([])
  const [showPlaybookModal, setShowPlaybookModal] = useState(false)
  const [docForPlaybook, setDocForPlaybook] = useState<DocumentFile | null>(null)
  const [runningPlaybook, setRunningPlaybook] = useState(false)
  const [playbookResult, setPlaybookResult] = useState<PlaybookCheck | null>(null)
  const [showResultPanel, setShowResultPanel] = useState(false)
  
  useEffect(() => {
    if (caseId) {
      loadDocuments()
      loadPlaybooks()
    }
  }, [caseId])
  
  const loadPlaybooks = async () => {
    try {
      const data = await playbooksApi.getPlaybooks()
      setPlaybooks(data)
    } catch (error) {
      console.error('Failed to load playbooks:', error)
    }
  }
  
  const handleRunPlaybook = async (playbookId: string) => {
    if (!docForPlaybook || !caseId) return
    
    try {
      setRunningPlaybook(true)
      setShowPlaybookModal(false)
      
      const result = await playbooksApi.checkDocument(
        playbookId,
        docForPlaybook.id,
        caseId
      )
      
      // Get full check result
      const fullCheck = await playbooksApi.getCheck(result.id)
      setPlaybookResult(fullCheck)
      setShowResultPanel(true)
      
      toast.success('Проверка завершена')
    } catch (error) {
      console.error('Playbook check failed:', error)
      toast.error('Ошибка проверки документа')
    } finally {
      setRunningPlaybook(false)
      setDocForPlaybook(null)
    }
  }
  
  const loadDocuments = async () => {
    if (!caseId) return
    setLoading(true)
    try {
      const { getDocuments } = await import('../services/api')
      const data = await getDocuments(caseId)
      setDocuments(data.documents.map((doc: any) => ({
        id: doc.id,
        filename: doc.filename,
        file_type: doc.file_type,
        status: doc.status || 'Pending',
        created_at: doc.created_at,
        classification: doc.classification
      })))
    } catch (error: any) {
      console.error('Ошибка при загрузке документов:', error)
    } finally {
      setLoading(false)
    }
  }
  
  const applyFilters = (docs: DocumentFile[]) => {
    let filtered = [...docs]
    
    // Поиск по названию
    if (filters.searchQuery) {
      const query = filters.searchQuery.toLowerCase()
      filtered = filtered.filter(doc => 
        doc.filename.toLowerCase().includes(query)
      )
    }
    
    // Фильтр по типу документа
    if (filters.docTypes.length > 0) {
      filtered = filtered.filter(doc => 
        doc.classification && filters.docTypes.includes(doc.classification.doc_type)
      )
    }
    
    // Фильтр по needs_human_review
    if (filters.privilegeStatus.includes('needs_review')) {
      filtered = filtered.filter(doc => 
        doc.classification?.needs_human_review === true
      )
    }
    
    // Фильтр по привилегированности
    if (filters.privilegeStatus.includes('Privileged')) {
      filtered = filtered.filter(doc => 
        doc.classification?.is_privileged === true
      )
    }
    if (filters.privilegeStatus.includes('Not Privileged')) {
      filtered = filtered.filter(doc => 
        doc.classification?.is_privileged === false
      )
    }
    
    // Фильтр по уверенности
    if (filters.confidenceLevels.includes('>95%')) {
      filtered = filtered.filter(doc => 
        doc.classification && doc.classification.confidence > 0.95
      )
    }
    if (filters.confidenceLevels.includes('80-95%')) {
      filtered = filtered.filter(doc => 
        doc.classification && 
        doc.classification.confidence >= 0.80 && 
        doc.classification.confidence <= 0.95
      )
    }
    if (filters.confidenceLevels.includes('<80%')) {
      filtered = filtered.filter(doc => 
        doc.classification && doc.classification.confidence < 0.80
      )
    }
    
    setFilteredDocuments(filtered)
  }
  
  useEffect(() => {
    if (documents.length > 0) {
      applyFilters(documents)
    }
  }, [filters, documents])
  
  const handleFiltersChange = (newFilters: DocumentFiltersState) => {
    setFilters(newFilters)
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
  
  if (loading) {
    return (
      <div className="flex h-screen bg-bg-primary">
        {caseId && (
          <UnifiedSidebar 
            navItems={[
              { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
              { id: 'documents', label: 'Документы', icon: FileText, path: `/cases/${caseId}/documents` },
              { id: 'editor', label: 'Редактор', icon: FileEdit, path: `/cases/${caseId}/editor` },
              { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
              { id: 'playbooks', label: 'Playbooks', icon: BookOpen, path: `/cases/${caseId}/playbooks` },
              { id: 'workflows', label: 'Workflows', icon: Workflow, path: `/cases/${caseId}/workflows` },
            ]} 
            title="Legal AI" 
          />
        )}
        <div className="flex-1 flex items-center justify-center">
          <CircularProgress />
        </div>
      </div>
    )
  }

  const navItems = [
    { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
    { id: 'documents', label: 'Документы', icon: FileText, path: `/cases/${caseId}/documents` },
    { id: 'editor', label: 'Редактор', icon: FileEdit, path: `/cases/${caseId}/editor` },
    { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
    { id: 'playbooks', label: 'Playbooks', icon: BookOpen, path: `/cases/${caseId}/playbooks` },
    { id: 'workflows', label: 'Workflows', icon: Workflow, path: `/cases/${caseId}/workflows` },
  ]

  return (
    <div className="flex h-screen bg-bg-primary">
      {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
      <div className="flex-1 overflow-auto bg-bg-primary">
        <div className="p-8 fade-in-up">
          <div className="flex items-center justify-between mb-6">
            <h1 className="font-display text-h1 text-text-primary">
              Документы ({filteredDocuments.length} / {documents.length})
            </h1>
            <button
              onClick={() => setShowFilters(!showFilters)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-bg-secondary text-text-primary border border-border hover:bg-bg-hover transition-all"
            >
              <Filter className="w-4 h-4" />
              Фильтры
            </button>
          </div>
          
          {showFilters && (
            <div className="mb-6">
              <DocumentFilters
                filters={filters}
                onFiltersChange={handleFiltersChange}
                onClearFilters={handleClearFilters}
              />
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredDocuments.map((doc, index) => {
              const classification = doc.classification
              const docTypeLabels: Record<string, string> = {
                // Судебные акты
                'court_order': 'Судебный приказ',
                'court_decision': 'Решение',
                'court_ruling': 'Определение',
                'court_resolution': 'Постановление',
                
                // Инициирующие дело
                'statement_of_claim': 'Исковое заявление',
                'order_application': 'Заявление о выдаче судебного приказа',
                'bankruptcy_application': 'Заявление о признании должника банкротом',
                
                // Ответные документы
                'response_to_claim': 'Отзыв на исковое заявление',
                'counterclaim': 'Встречный иск',
                'third_party_application': 'Заявление о вступлении третьего лица в дело',
                'third_party_objection': 'Возражения третьего лица',
                
                // Ходатайства
                'motion': 'Ходатайство',
                'motion_evidence': 'Ходатайство о доказательствах',
                'motion_security': 'Ходатайство об обеспечительных мерах',
                'motion_cancel_security': 'Ходатайство об отмене обеспечения иска',
                'motion_recusation': 'Ходатайство об отводе судьи',
                'motion_reinstatement': 'Ходатайство о восстановлении пропущенного срока',
                
                // Обжалование
                'appeal': 'Апелляционная жалоба',
                'cassation': 'Кассационная жалоба',
                'supervisory_appeal': 'Надзорная жалоба',
                
                // Специальные производства
                'arbitral_annulment': 'Заявление об отмене решения третейского суда',
                'arbitral_enforcement': 'Заявление о выдаче исполнительного листа на решение третейского суда',
                'creditor_registry': 'Заявление о включении требования в реестр требований кредиторов',
                'administrative_challenge': 'Заявление об оспаривании ненормативного правового акта',
                'admin_penalty_challenge': 'Заявление об оспаривании решения административного органа',
                
                // Урегулирование
                'settlement_agreement': 'Мировое соглашение',
                'protocol_remarks': 'Замечания на протокол судебного заседания',
                
                // Досудебные
                'pre_claim': 'Претензия (досудебное требование)',
                'written_explanation': 'Письменное объяснение по делу',
                
                // Приложения
                'power_of_attorney': 'Доверенность',
                'egrul_extract': 'Выписка из ЕГРЮЛ/ЕГРИП',
                'state_duty': 'Документ об уплате государственной пошлины',
                
                // Доказательства - Письменные
                'contract': 'Договор',
                'act': 'Акт',
                'certificate': 'Справка',
                'correspondence': 'Деловая переписка',
                'electronic_document': 'Электронный документ',
                'protocol': 'Протокол',
                'expert_opinion': 'Заключение эксперта',
                'specialist_consultation': 'Консультация специалиста',
                'witness_statement': 'Показания свидетеля',
                
                // Доказательства - Мультимедиа
                'audio_recording': 'Аудиозапись',
                'video_recording': 'Видеозапись',
                'physical_evidence': 'Вещественное доказательство',
                
                // Прочие
                'other': 'Другое'
              }

              return (
              <div
                key={doc.id}
                className="bg-bg-elevated rounded-lg border border-border p-6 cursor-pointer hoverable transition-all duration-300 shadow-sm hover:shadow-md"
                style={{ animationDelay: `${index * 0.05}s` }}
                onClick={() => {
                  const idx = filteredDocuments.findIndex(d => d.id === doc.id)
                  setSelectedDocument(doc)
                  setSelectedDocumentIndex(idx)
                }}
              >
                <div className="space-y-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-bg-secondary flex items-center justify-center flex-shrink-0">
                      <DescriptionIcon className="w-5 h-5 text-text-primary" />
                    </div>
                    <h3 className="font-display text-h3 text-text-primary truncate flex-1">
                      {doc.filename}
                    </h3>
                  </div>

                  {classification && (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`inline-block px-3 py-1 rounded-full text-xs font-medium bg-bg-secondary text-text-primary border border-border`}>
                          {docTypeLabels[classification.doc_type] || classification.doc_type}
                        </span>
                        {classification.needs_human_review && (
                          <span className="inline-block px-2 py-1 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 border border-yellow-300">
                            ⚠️ Требует проверки
                          </span>
                        )}
                        {classification.is_privileged && (
                          <span className="inline-block px-2 py-1 rounded-full text-xs font-medium bg-red-100 text-red-800 border border-red-300">
                            🔒 Привилегированный
                          </span>
                        )}
                      </div>
                      
                      {classification.key_topics && classification.key_topics.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {classification.key_topics.slice(0, 3).map((tag, i) => (
                            <span key={i} className="px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-600">
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                      
                      <div className="flex items-center gap-2 text-xs text-gray-500">
                        <span>Уверенность: {Math.round(classification.confidence * 100)}%</span>
                        {classification.relevance_score > 0 && (
                          <span>• Релевантность: {classification.relevance_score}%</span>
                        )}
                      </div>
                    </div>
                  )}

                  {!classification && doc.file_type && (
                    <span className="inline-block px-3 py-1 rounded-full text-xs font-medium bg-bg-secondary text-text-primary border border-border">
                      {doc.file_type}
                    </span>
                  )}

                  {doc.created_at && (
                    <p className="text-xs text-text-secondary">
                      {new Date(doc.created_at).toLocaleDateString('ru-RU')}
                    </p>
                  )}
                  
                  {/* Playbook Button */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      setDocForPlaybook(doc)
                      setShowPlaybookModal(true)
                    }}
                    className="w-full mt-3 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors"
                    style={{
                      backgroundColor: 'rgba(99, 102, 241, 0.1)',
                      color: 'var(--color-accent, #6366f1)',
                    }}
                  >
                    <BookOpen className="w-4 h-4" />
                    Проверить Playbook
                  </button>
                </div>
              </div>
              )
            })}
          </div>
        </div>
      </div>
      
      {/* Drawer для просмотра документа */}
      <Drawer
        anchor="right"
        open={!!selectedDocument}
        onClose={() => {
          setSelectedDocument(null)
          setSelectedDocumentIndex(null)
        }}
        PaperProps={{
          sx: {
            width: '90%',
            maxWidth: '1200px',
            bgcolor: 'white',
          },
        }}
      >
        {selectedDocument && caseId && (
          <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            {/* Header */}
            <Box
              sx={{
                p: 3,
                borderBottom: '1px solid #E5E7EB',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                bgcolor: 'white',
              }}
            >
              <Typography variant="h6" sx={{ fontWeight: 600, fontFamily: 'Playfair Display', color: '#1F2937' }}>
                {selectedDocument.filename}
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <IconButton
                  onClick={async () => {
                    if (!caseId || !selectedDocument?.id) return
                    try {
                      const baseUrl = import.meta.env.VITE_API_URL || ''
                      const url = baseUrl 
                        ? `${baseUrl}/api/cases/${caseId}/files/${selectedDocument.id}/download`
                        : `/api/cases/${caseId}/files/${selectedDocument.id}/download`
                      const response = await fetch(url, {
                        headers: {
                          'Authorization': `Bearer ${localStorage.getItem('access_token')}`
                        }
                      })
                      if (response.ok) {
                        const blob = await response.blob()
                        const blobUrl = window.URL.createObjectURL(blob)
                        window.open(blobUrl, '_blank')
                        // Clean up the blob URL after a delay
                        setTimeout(() => window.URL.revokeObjectURL(blobUrl), 100)
                      }
                    } catch (error) {
                      console.error('Ошибка при открытии документа:', error)
                    }
                  }}
                  sx={{
                    '&:hover': {
                      bgcolor: '#F3F4F6',
                    },
                  }}
                  title="Открыть в оригинальном формате"
                >
                  <OpenInNewIcon />
                </IconButton>
                <IconButton
                  onClick={() => {
                    setSelectedDocument(null)
                    setSelectedDocumentIndex(null)
                  }}
                  sx={{
                    '&:hover': {
                      bgcolor: '#F3F4F6',
                    },
                  }}
                >
                  <CloseIcon />
                </IconButton>
              </Box>
            </Box>

            {/* Document Viewer */}
            <Box sx={{ flex: 1, overflow: 'hidden', bgcolor: 'white' }}>
              <DocumentViewer
                document={
                  selectedDocument
                    ? {
                        id: selectedDocument.id,
                        filename: selectedDocument.filename,
                        file_type: selectedDocument.file_type || 'pdf',
                        created_at: selectedDocument.created_at,
                        classification: selectedDocument.classification,
                      } as DocumentWithMetadata
                    : null
                }
                caseId={caseId}
                onNavigateNext={() => {
                  if (selectedDocumentIndex !== null && selectedDocumentIndex < filteredDocuments.length - 1) {
                    const nextDoc = filteredDocuments[selectedDocumentIndex + 1]
                    setSelectedDocument(nextDoc)
                    setSelectedDocumentIndex(selectedDocumentIndex + 1)
                  }
                }}
                onNavigatePrev={() => {
                  if (selectedDocumentIndex !== null && selectedDocumentIndex > 0) {
                    const prevDoc = filteredDocuments[selectedDocumentIndex - 1]
                    setSelectedDocument(prevDoc)
                    setSelectedDocumentIndex(selectedDocumentIndex - 1)
                  }
                }}
              />
            </Box>
          </Box>
        )}
      </Drawer>
      
      {/* Playbook Selection Modal */}
      {showPlaybookModal && docForPlaybook && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div
            className="w-full max-w-lg rounded-xl shadow-xl"
            style={{ backgroundColor: 'var(--color-bg-primary, white)' }}
          >
            <div
              className="flex items-center justify-between p-4 border-b"
              style={{ borderColor: 'var(--color-border, #e5e7eb)' }}
            >
              <div>
                <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary, #1f2937)' }}>
                  Выбрать Playbook
                </h2>
                <p className="text-sm" style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
                  {docForPlaybook.filename}
                </p>
              </div>
              <button
                onClick={() => {
                  setShowPlaybookModal(false)
                  setDocForPlaybook(null)
                }}
                className="p-2 rounded-lg hover:bg-gray-100"
                style={{ color: 'var(--color-text-secondary, #6b7280)' }}
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="p-4 max-h-96 overflow-y-auto space-y-2">
              {playbooks.map(playbook => (
                <button
                  key={playbook.id}
                  onClick={() => handleRunPlaybook(playbook.id)}
                  className="w-full flex items-center gap-4 p-4 rounded-lg border text-left transition-colors hover:border-indigo-500"
                  style={{
                    backgroundColor: 'var(--color-bg-secondary, #f9fafb)',
                    borderColor: 'var(--color-border, #e5e7eb)'
                  }}
                >
                  <div
                    className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                    style={{ backgroundColor: 'rgba(99, 102, 241, 0.15)' }}
                  >
                    <BookOpen className="w-5 h-5" style={{ color: '#6366f1' }} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium" style={{ color: 'var(--color-text-primary, #1f2937)' }}>
                      {playbook.display_name}
                    </div>
                    <div className="text-sm truncate" style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
                      {playbook.rules_count} правил • {playbook.usage_count} проверок
                    </div>
                  </div>
                  <ChevronRight className="w-5 h-5 shrink-0" style={{ color: 'var(--color-text-tertiary, #9ca3af)' }} />
                </button>
              ))}
              
              {playbooks.length === 0 && (
                <p className="text-center py-8" style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
                  Нет доступных Playbooks
                </p>
              )}
            </div>
          </div>
        </div>
      )}
      
      {/* Running Playbook Overlay */}
      {runningPlaybook && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div
            className="rounded-xl p-8 flex flex-col items-center"
            style={{ backgroundColor: 'var(--color-bg-primary, white)' }}
          >
            <Loader2 className="w-12 h-12 animate-spin mb-4" style={{ color: '#6366f1' }} />
            <p className="text-lg font-medium" style={{ color: 'var(--color-text-primary, #1f2937)' }}>
              Проверка документа...
            </p>
            <p className="text-sm" style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
              Это может занять 1-2 минуты
            </p>
          </div>
        </div>
      )}
      
      {/* Playbook Result Panel */}
      {showResultPanel && playbookResult && (
        <div
          className="fixed right-0 top-0 bottom-0 w-[480px] shadow-xl border-l overflow-hidden flex flex-col z-40"
          style={{
            backgroundColor: 'var(--color-bg-primary, white)',
            borderColor: 'var(--color-border, #e5e7eb)'
          }}
        >
          {/* Header */}
          <div
            className="flex items-center justify-between p-4 border-b shrink-0"
            style={{ borderColor: 'var(--color-border, #e5e7eb)' }}
          >
            <div>
              <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary, #1f2937)' }}>
                Результат проверки
              </h2>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
                {playbookResult.document_name}
              </p>
            </div>
            <button
              onClick={() => {
                setShowResultPanel(false)
                setPlaybookResult(null)
              }}
              className="p-2 rounded-lg hover:bg-gray-100"
              style={{ color: 'var(--color-text-secondary, #6b7280)' }}
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          
          {/* Stats */}
          <div className="p-4 grid grid-cols-2 gap-3">
            <div
              className="rounded-lg p-3"
              style={{ backgroundColor: 'var(--color-bg-secondary, #f9fafb)' }}
            >
              <div className="text-2xl font-bold" style={{ color: '#6366f1' }}>
                {playbookResult.compliance_score?.toFixed(0) || 0}%
              </div>
              <div className="text-xs" style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
                Соответствие
              </div>
            </div>
            <div
              className="rounded-lg p-3 flex items-center"
              style={{ backgroundColor: 'var(--color-bg-secondary, #f9fafb)' }}
            >
              <span
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
                style={{
                  backgroundColor: playbookResult.overall_status === 'compliant'
                    ? 'rgba(34, 197, 94, 0.15)'
                    : playbookResult.overall_status === 'non_compliant'
                    ? 'rgba(239, 68, 68, 0.15)'
                    : 'rgba(234, 179, 8, 0.15)',
                  color: playbookResult.overall_status === 'compliant'
                    ? '#22c55e'
                    : playbookResult.overall_status === 'non_compliant'
                    ? '#ef4444'
                    : '#eab308'
                }}
              >
                {playbookResult.overall_status === 'compliant' && <CheckCircle className="w-3.5 h-3.5" />}
                {playbookResult.overall_status === 'non_compliant' && <XCircle className="w-3.5 h-3.5" />}
                {playbookResult.overall_status === 'needs_review' && <AlertTriangle className="w-3.5 h-3.5" />}
                {playbooksApi.getStatusLabel(playbookResult.overall_status)}
              </span>
            </div>
          </div>
          
          {/* Counters */}
          <div
            className="mx-4 p-3 rounded-lg flex items-center justify-around"
            style={{ backgroundColor: 'var(--color-bg-secondary, #f9fafb)' }}
          >
            <div className="text-center">
              <div className="text-lg font-semibold" style={{ color: '#22c55e' }}>
                {playbookResult.passed_rules}
              </div>
              <div className="text-xs" style={{ color: 'var(--color-text-tertiary, #9ca3af)' }}>Пройдено</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-semibold" style={{ color: '#ef4444' }}>
                {playbookResult.red_line_violations}
              </div>
              <div className="text-xs" style={{ color: 'var(--color-text-tertiary, #9ca3af)' }}>Нарушений</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-semibold" style={{ color: '#eab308' }}>
                {playbookResult.fallback_issues}
              </div>
              <div className="text-xs" style={{ color: 'var(--color-text-tertiary, #9ca3af)' }}>Предупреждений</div>
            </div>
          </div>
          
          {/* Results */}
          <div className="flex-1 overflow-y-auto p-4">
            <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-primary, #1f2937)' }}>
              Результаты по правилам
            </h3>
            <div className="space-y-2">
              {playbookResult.results?.map((result, idx) => (
                <div
                  key={idx}
                  className="rounded-lg p-3 border"
                  style={{
                    backgroundColor: 'var(--color-bg-secondary, #f9fafb)',
                    borderColor: result.status === 'violation' ? 'rgba(239, 68, 68, 0.3)' : 'var(--color-border, #e5e7eb)'
                  }}
                >
                  <div className="flex items-start justify-between mb-1">
                    <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary, #1f2937)' }}>
                      {result.rule_name}
                    </span>
                    <span
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium"
                      style={{
                        backgroundColor: result.status === 'passed'
                          ? 'rgba(34, 197, 94, 0.15)'
                          : result.status === 'violation'
                          ? 'rgba(239, 68, 68, 0.15)'
                          : 'rgba(156, 163, 175, 0.15)',
                        color: result.status === 'passed'
                          ? '#22c55e'
                          : result.status === 'violation'
                          ? '#ef4444'
                          : '#9ca3af'
                      }}
                    >
                      {result.status === 'passed' && <CheckCircle className="w-3 h-3" />}
                      {result.status === 'violation' && <XCircle className="w-3 h-3" />}
                      {playbooksApi.getStatusLabel(result.status)}
                    </span>
                  </div>
                  {result.issue_description && (
                    <p className="text-xs" style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
                      {result.issue_description}
                    </p>
                  )}
                </div>
              ))}
            </div>
            
            {/* Redlines */}
            {playbookResult.redlines && playbookResult.redlines.length > 0 && (
              <>
                <h3 className="text-sm font-medium mt-6 mb-3" style={{ color: 'var(--color-text-primary, #1f2937)' }}>
                  Предлагаемые исправления ({playbookResult.redlines.length})
                </h3>
                <div className="space-y-3">
                  {playbookResult.redlines.map((redline, idx) => (
                    <div
                      key={idx}
                      className="rounded-lg p-3 border-l-4"
                      style={{
                        backgroundColor: 'var(--color-bg-secondary, #f9fafb)',
                        borderLeftColor: '#ef4444'
                      }}
                    >
                      <div className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary, #1f2937)' }}>
                        {redline.rule_name}
                      </div>
                      {redline.original_text && (
                        <div className="mb-2">
                          <div className="text-xs mb-1" style={{ color: 'var(--color-text-tertiary, #9ca3af)' }}>
                            Исходный текст:
                          </div>
                          <div
                            className="text-xs p-2 rounded line-through"
                            style={{ backgroundColor: 'rgba(239, 68, 68, 0.1)', color: 'var(--color-text-secondary, #6b7280)' }}
                          >
                            {redline.original_text.slice(0, 200)}...
                          </div>
                        </div>
                      )}
                      <div>
                        <div className="text-xs mb-1" style={{ color: 'var(--color-text-tertiary, #9ca3af)' }}>
                          Предлагаемый текст:
                        </div>
                        <div
                          className="text-xs p-2 rounded"
                          style={{ backgroundColor: 'rgba(34, 197, 94, 0.1)', color: 'var(--color-text-primary, #1f2937)' }}
                        >
                          {redline.suggested_text?.slice(0, 200)}...
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default DocumentsPage
