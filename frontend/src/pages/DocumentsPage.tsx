import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
// import { getCaseFiles } from '../services/api' // TODO: implement API call
import MainLayout from '../components/Layout/MainLayout'
import CaseNavigation from '../components/CaseOverview/CaseNavigation'
import { Card } from '../components/UI/Card'
import { Badge } from '../components/UI/Badge'
import Modal from '../components/UI/Modal'
import Spinner from '../components/UI/Spinner'
import { FileText } from 'lucide-react'

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
    try {
      // TODO: implement API call when available
      // const data = await getCaseFiles(caseId)
      // setDocuments(data.files || [])
      
      // Mock data for now
      setTimeout(() => {
        setDocuments([
          { id: '1', filename: 'contract_main.docx', file_type: 'Contract', status: 'Analyzed' },
          { id: '2', filename: 'addendum_spec.docx', file_type: 'Contract', status: 'Analyzed' },
          { id: '3', filename: 'letter_counterparty.pdf', file_type: 'Email', status: 'Pending' },
        ])
        setLoading(false)
      }, 500)
    } catch (error) {
      console.error('Ошибка при загрузке документов:', error)
      setLoading(false)
    }
  }
  
  if (loading) {
    return (
      <MainLayout>
        <div className="flex items-center justify-center h-full">
          <Spinner size="lg" />
        </div>
      </MainLayout>
    )
  }
  
  return (
    <MainLayout>
      <div className="flex h-full">
        {caseId && <CaseNavigation caseId={caseId} />}
        <div className="flex-1 overflow-y-auto p-6">
          <h1 className="text-h1 text-primary mb-6">
            Документы ({documents.length})
          </h1>
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {documents.map((doc) => (
              <Card
                key={doc.id}
                hoverable
                onClick={() => setSelectedDocument(doc)}
              >
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <FileText className="w-5 h-5 text-primary" />
                    <h3 className="text-h3 text-primary truncate">{doc.filename}</h3>
                  </div>
                  
                  {doc.file_type && (
                    <Badge variant="pending">{doc.file_type}</Badge>
                  )}
                  
                  {doc.status && (
                    <div className="text-small text-secondary">
                      Статус: {doc.status}
                    </div>
                  )}
                </div>
              </Card>
            ))}
          </div>
        </div>
      </div>
      
      {selectedDocument && (
        <Modal
          isOpen={!!selectedDocument}
          onClose={() => setSelectedDocument(null)}
          title={selectedDocument.filename}
          size="lg"
        >
          <div className="space-y-4">
            <div>
              <h4 className="text-body font-medium text-primary mb-2">Файл</h4>
              <p className="text-body text-secondary">{selectedDocument.filename}</p>
            </div>
            
            {selectedDocument.file_type && (
              <div>
                <h4 className="text-body font-medium text-primary mb-2">Тип</h4>
                <Badge variant="pending">{selectedDocument.file_type}</Badge>
              </div>
            )}
            
            {selectedDocument.status && (
              <div>
                <h4 className="text-body font-medium text-primary mb-2">Статус</h4>
                <p className="text-body text-secondary">{selectedDocument.status}</p>
              </div>
            )}
          </div>
        </Modal>
      )}
    </MainLayout>
  )
}

export default DocumentsPage
