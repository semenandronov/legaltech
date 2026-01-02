import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import {
  Box,
  Typography,
  CircularProgress,
  IconButton,
  Drawer,
} from '@mui/material'
import { Description as DescriptionIcon, Close as CloseIcon } from '@mui/icons-material'
import { MessageSquare, FileText, Table, Filter } from 'lucide-react'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import DocumentViewer from '../components/Documents/DocumentViewer'
import DocumentFilters, { DocumentFiltersState } from '../components/Documents/DocumentFilters'
import { DocumentWithMetadata } from '../components/Documents/DocumentsList'

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
  
  useEffect(() => {
    if (caseId) {
      loadDocuments()
    }
  }, [caseId])
  
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
      <div className="flex h-screen bg-gradient-to-br from-[#F8F9FA] via-white to-[#F0F4F8]">
        {caseId && (
          <UnifiedSidebar 
            navItems={[
              { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
              { id: 'documents', label: 'Документы', icon: FileText, path: `/cases/${caseId}/documents` },
              { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
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
    { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
  ]

  return (
    <div className="flex h-screen bg-gradient-to-br from-[#F8F9FA] via-white to-[#F0F4F8]">
      {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
      <div className="flex-1 overflow-auto content-background">
        <div className="p-8 fade-in-up">
          <div className="flex items-center justify-between mb-6">
            <h1 className="font-display text-h1 text-[#1F2937]">
              Документы ({filteredDocuments.length} / {documents.length})
            </h1>
            <button
              onClick={() => setShowFilters(!showFilters)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-[#00D4FF]/10 to-[#7C3AED]/10 text-[#00D4FF] border border-[#00D4FF]/20 hover:from-[#00D4FF]/20 hover:to-[#7C3AED]/20 transition-all"
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
                'statement_of_claim': 'Исковое заявление',
                'application': 'Заявление',
                'response_to_claim': 'Отзыв на иск',
                'counterclaim': 'Встречный иск',
                'motion': 'Ходатайство',
                'appeal': 'Апелляционная жалоба',
                'cassation': 'Кассационная жалоба',
                'supervisory_appeal': 'Надзорная жалоба',
                'protocol_remarks': 'Замечания на протокол',
                'settlement_agreement': 'Мировое соглашение',
                'court_order': 'Судебный приказ',
                'court_decision': 'Решение',
                'court_ruling': 'Определение',
                'court_resolution': 'Постановление',
                'contract': 'Договор',
                'act': 'Акт',
                'certificate': 'Справка',
                'correspondence': 'Деловая переписка',
                'electronic_document': 'Электронный документ',
                'protocol': 'Протокол',
                'expert_opinion': 'Заключение эксперта',
                'specialist_consultation': 'Консультация специалиста',
                'witness_statement': 'Показания свидетеля',
                'audio_recording': 'Аудиозапись',
                'video_recording': 'Видеозапись',
                'physical_evidence': 'Вещественное доказательство',
                'other': 'Другое'
              }
              
              const getDocTypeColor = (docType: string) => {
                if (['statement_of_claim', 'application', 'response_to_claim', 'counterclaim', 'motion', 'appeal', 'cassation', 'supervisory_appeal', 'protocol_remarks', 'settlement_agreement'].includes(docType)) {
                  return 'from-blue-500/20 to-blue-600/20 text-blue-600 border-blue-500/30'
                }
                if (['court_order', 'court_decision', 'court_ruling', 'court_resolution'].includes(docType)) {
                  return 'from-purple-500/20 to-purple-600/20 text-purple-600 border-purple-500/30'
                }
                if (['contract', 'act', 'certificate', 'correspondence', 'electronic_document', 'protocol', 'expert_opinion', 'specialist_consultation', 'witness_statement', 'audio_recording', 'video_recording', 'physical_evidence'].includes(docType)) {
                  return 'from-green-500/20 to-green-600/20 text-green-600 border-green-500/30'
                }
                return 'from-gray-500/20 to-gray-600/20 text-gray-600 border-gray-500/30'
              }
              
              return (
              <div
                key={doc.id}
                className="bg-white rounded-lg border border-[#E5E7EB] p-6 cursor-pointer hoverable transition-all duration-300 shadow-sm hover:shadow-md"
                style={{ animationDelay: `${index * 0.05}s` }}
                onClick={() => {
                  const idx = filteredDocuments.findIndex(d => d.id === doc.id)
                  setSelectedDocument(doc)
                  setSelectedDocumentIndex(idx)
                }}
              >
                <div className="space-y-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#00D4FF]/20 to-[#7C3AED]/20 flex items-center justify-center flex-shrink-0">
                      <DescriptionIcon className="w-5 h-5 text-[#00D4FF]" />
                    </div>
                    <h3 className="font-display text-h3 text-[#1F2937] truncate flex-1">
                      {doc.filename}
                    </h3>
                  </div>

                  {classification && (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`inline-block px-3 py-1 rounded-full text-xs font-medium bg-gradient-to-r ${getDocTypeColor(classification.doc_type)} border`}>
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
                    <span className="inline-block px-3 py-1 rounded-full text-xs font-medium bg-gradient-to-r from-[#00D4FF]/10 to-[#7C3AED]/10 text-[#00D4FF] border border-[#00D4FF]/20">
                      {doc.file_type}
                    </span>
                  )}

                  {doc.created_at && (
                    <p className="text-xs text-[#6B7280]">
                      {new Date(doc.created_at).toLocaleDateString('ru-RU')}
                    </p>
                  )}
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
    </div>
  )
}

export default DocumentsPage
