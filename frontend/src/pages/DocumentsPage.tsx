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
import { Home, MessageSquare, FileText, Table } from 'lucide-react'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import DocumentViewer from '../components/Documents/DocumentViewer'
import { DocumentWithMetadata } from '../components/Documents/DocumentsList'

interface DocumentFile {
  id: string
  filename: string
  file_type?: string
  status?: string
  created_at?: string
}

const DocumentsPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const [documents, setDocuments] = useState<DocumentFile[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedDocument, setSelectedDocument] = useState<DocumentFile | null>(null)
  const [selectedDocumentIndex, setSelectedDocumentIndex] = useState<number | null>(null)
  
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
        status: doc.status || 'Pending'
      })))
    } catch (error: any) {
      console.error('Ошибка при загрузке документов:', error)
    } finally {
      setLoading(false)
    }
  }
  
  if (loading) {
    return (
      <div className="flex h-screen bg-gradient-to-br from-[#F8F9FA] via-white to-[#F0F4F8]">
        {caseId && (
          <UnifiedSidebar 
            navItems={[
              { id: 'overview', label: 'Обзор', icon: Home, path: `/cases/${caseId}/workspace` },
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
    { id: 'overview', label: 'Обзор', icon: Home, path: `/cases/${caseId}/workspace` },
    { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
    { id: 'documents', label: 'Документы', icon: FileText, path: `/cases/${caseId}/documents` },
    { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
  ]

  return (
    <div className="flex h-screen bg-gradient-to-br from-[#F8F9FA] via-white to-[#F0F4F8]">
      {caseId && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
      <div className="flex-1 overflow-auto content-background">
        <div className="p-8 fade-in-up">
          <h1 className="font-display text-h1 text-[#1F2937] mb-6">
            Документы ({documents.length})
          </h1>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {documents.map((doc, index) => (
              <div
                key={doc.id}
                className="bg-white rounded-lg border border-[#E5E7EB] p-6 cursor-pointer hoverable transition-all duration-300"
                style={{ animationDelay: `${index * 0.05}s` }}
                onClick={() => {
                  const idx = documents.findIndex(d => d.id === doc.id)
                  setSelectedDocument(doc)
                  setSelectedDocumentIndex(idx)
                }}
              >
                <div className="space-y-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#00D4FF]/20 to-[#7C3AED]/20 flex items-center justify-center">
                      <DescriptionIcon className="w-5 h-5 text-[#00D4FF]" />
                    </div>
                    <h3 className="font-display text-h3 text-[#1F2937] truncate flex-1">
                      {doc.filename}
                    </h3>
                  </div>

                  {doc.file_type && (
                    <span className="inline-block px-3 py-1 rounded-full text-xs font-medium bg-gradient-to-r from-[#00D4FF]/10 to-[#7C3AED]/10 text-[#00D4FF] border border-[#00D4FF]/20">
                      {doc.file_type}
                    </span>
                  )}

                  {doc.status && (
                    <p className="text-sm text-[#6B7280]">
                      Статус: {doc.status}
                    </p>
                  )}
                </div>
              </div>
            ))}
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
                      } as DocumentWithMetadata
                    : null
                }
                caseId={caseId}
                onNavigateNext={() => {
                  if (selectedDocumentIndex !== null && selectedDocumentIndex < documents.length - 1) {
                    const nextDoc = documents[selectedDocumentIndex + 1]
                    setSelectedDocument(nextDoc)
                    setSelectedDocumentIndex(selectedDocumentIndex + 1)
                  }
                }}
                onNavigatePrev={() => {
                  if (selectedDocumentIndex !== null && selectedDocumentIndex > 0) {
                    const prevDoc = documents[selectedDocumentIndex - 1]
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
