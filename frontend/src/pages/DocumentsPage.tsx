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
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Stack,
} from '@mui/material'
import { Description as DescriptionIcon } from '@mui/icons-material'
import MainLayout from '../components/Layout/MainLayout'
import CaseNavigation from '../components/CaseOverview/CaseNavigation'

interface DocumentFile {
  id: string
  filename: string
  file_type?: string
  status?: string
}

const DocumentsPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const [documents, setDocuments] = useState<DocumentFile[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedDocument, setSelectedDocument] = useState<DocumentFile | null>(null)
  
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

  return (
    <MainLayout>
      <Box sx={{ display: 'flex', height: '100%' }}>
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
                  onClick={() => setSelectedDocument(doc)}
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
      </Box>
      
      <Dialog
        open={!!selectedDocument}
        onClose={() => setSelectedDocument(null)}
        maxWidth="md"
        fullWidth
      >
        {selectedDocument && (
          <>
            <DialogTitle>{selectedDocument.filename}</DialogTitle>
            <DialogContent>
              <Stack spacing={3}>
                <Box>
                  <Typography variant="body2" fontWeight={500} sx={{ mb: 1 }}>
                    Файл
                  </Typography>
                  <Typography variant="body1" color="text.secondary">
                    {selectedDocument.filename}
                  </Typography>
                </Box>

                {selectedDocument.file_type && (
                  <Box>
                    <Typography variant="body2" fontWeight={500} sx={{ mb: 1 }}>
                      Тип
                    </Typography>
                    <Chip
                      label={selectedDocument.file_type}
                      size="small"
                      variant="outlined"
                      color="primary"
                    />
                  </Box>
                )}

                {selectedDocument.status && (
                  <Box>
                    <Typography variant="body2" fontWeight={500} sx={{ mb: 1 }}>
                      Статус
                    </Typography>
                    <Typography variant="body1" color="text.secondary">
                      {selectedDocument.status}
                    </Typography>
                  </Box>
                )}
              </Stack>
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setSelectedDocument(null)}>Закрыть</Button>
            </DialogActions>
          </>
        )}
      </Dialog>
    </MainLayout>
  )
}

export default DocumentsPage
