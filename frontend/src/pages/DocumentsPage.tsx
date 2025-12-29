import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import {
  Box,
  Grid,
  Card,
  CardContent,
  Typography,
  Chip,
  CircularProgress,
  IconButton,
  Drawer,
  Stack,
} from '@mui/material'
import { Description as DescriptionIcon, Close as CloseIcon } from '@mui/icons-material'
import CaseNavigation from '../components/CaseOverview/CaseNavigation'
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
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DocumentsPage.tsx:loadDocuments',message:'Loading documents',data:{caseId},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'H2'})}).catch(()=>{});
    // #endregion
    try {
      const { getDocuments } = await import('../services/api')
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DocumentsPage.tsx:loadDocuments',message:'Calling getDocuments API',data:{caseId,apiUrl:`/api/cases/${caseId}/files`},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'H2'})}).catch(()=>{});
      // #endregion
      const data = await getDocuments(caseId)
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DocumentsPage.tsx:loadDocuments',message:'Documents received',data:{caseId,docCount:data.documents?.length||0,total:data.total||0},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'H2'})}).catch(()=>{});
      // #endregion
      setDocuments(data.documents.map((doc: any) => ({
        id: doc.id,
        filename: doc.filename,
        file_type: doc.file_type,
        status: doc.status || 'Pending'
      })))
    } catch (error: any) {
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DocumentsPage.tsx:loadDocuments',message:'Error loading documents',data:{caseId,error:error?.message||String(error),status:error?.response?.status,statusText:error?.response?.statusText},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'H2'})}).catch(()=>{});
      // #endregion
      console.error('Ошибка при загрузке документов:', error)
    } finally {
      setLoading(false)
    }
  }
  
  if (loading) {
    return (
      <Box
        sx={{
          height: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: 'background.default',
        }}
      >
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box 
      sx={{ 
        height: '100vh',
        display: 'flex', 
        bgcolor: 'background.default',
        overflow: 'hidden',
      }}
    >
      {caseId && <CaseNavigation caseId={caseId} />}
      <Box
        sx={{
          flex: 1,
          overflow: 'auto',
          p: 3,
        }}
      >
          <Typography variant="h4" sx={{ mb: 3, fontWeight: 600 }}>
            Документы ({documents.length})
          </Typography>

          <Grid container spacing={2}>
            {documents.map((doc) => (
              <Grid item xs={12} sm={6} md={4} key={doc.id}>
                <Card
                  sx={{
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                    '&:hover': {
                      boxShadow: 4,
                      transform: 'translateY(-2px)',
                    },
                  }}
                  onClick={() => {
                    const index = documents.findIndex(d => d.id === doc.id)
                    setSelectedDocument(doc)
                    setSelectedDocumentIndex(index)
                  }}
                >
                  <CardContent>
                    <Stack spacing={2}>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <DescriptionIcon color="primary" />
                        <Typography
                          variant="h6"
                          sx={{
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            fontWeight: 500,
                          }}
                        >
                          {doc.filename}
                        </Typography>
                      </Stack>

                      {doc.file_type && (
                        <Chip
                          label={doc.file_type}
                          size="small"
                          variant="outlined"
                          color="primary"
                        />
                      )}

                      {doc.status && (
                        <Typography variant="body2" color="text.secondary">
                          Статус: {doc.status}
                        </Typography>
                      )}
                    </Stack>
                  </CardContent>
                </Card>
              </Grid>
            ))}
          </Grid>
      </Box>
      
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
          },
        }}
      >
        {selectedDocument && caseId && (
          <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            {/* Header */}
            <Box
              sx={{
                p: 2,
                borderBottom: 1,
                borderColor: 'divider',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <Typography variant="h6" sx={{ fontWeight: 600 }}>
                {selectedDocument.filename}
              </Typography>
              <IconButton
                onClick={() => {
                  setSelectedDocument(null)
                  setSelectedDocumentIndex(null)
                }}
              >
                <CloseIcon />
              </IconButton>
            </Box>

            {/* Document Viewer */}
            <Box sx={{ flex: 1, overflow: 'hidden' }}>
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
    </Box>
  )
}

export default DocumentsPage
