import React from 'react'
import { FileText, Trash2, Calendar, Edit, ArrowLeft } from 'lucide-react'
import { Button } from '@/components/UI/Button'
import { toast } from 'sonner'
import { Document, deleteDocument } from '@/services/documentEditorApi'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale/ru'
import { useNavigate } from 'react-router-dom'

interface DocumentsListProps {
  documents: Document[]
  caseId: string
  onDocumentSelect: (documentId: string) => void
  onDocumentDeleted?: () => void
}

export const DocumentsList: React.FC<DocumentsListProps> = ({
  documents,
  caseId,
  onDocumentSelect,
  onDocumentDeleted,
}) => {
  const navigate = useNavigate()
  const [deletingId, setDeletingId] = React.useState<string | null>(null)

  const handleDelete = async (documentId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    
    if (!confirm('Вы уверены, что хотите удалить этот документ?')) {
      return
    }

    try {
      setDeletingId(documentId)
      await deleteDocument(documentId)
      toast.success('Документ удален')
      onDocumentDeleted?.()
    } catch (error: any) {
      toast.error(error.message || 'Ошибка при удалении документа')
    } finally {
      setDeletingId(null)
    }
  }

  const formatDate = (dateString: string) => {
    try {
      return format(new Date(dateString), 'dd MMMM yyyy, HH:mm', { locale: ru })
    } catch {
      return dateString
    }
  }

  if (documents.length === 0) {
    return null // Пустое состояние обрабатывается в родительском компоненте
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center gap-4 mb-6">
          <button
            onClick={() => navigate(`/cases/${caseId}/editor`)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg transition-all duration-150 hover:bg-gray-100"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <ArrowLeft className="w-4 h-4" />
            Назад
          </button>
          <h2 className="text-2xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>
            Документы редактора
          </h2>
        </div>
        
        <div className="grid gap-4">
          {documents.map((doc) => (
            <div
              key={doc.id}
              onClick={() => onDocumentSelect(doc.id)}
              className="p-4 rounded-lg border cursor-pointer transition-all hover:shadow-md"
              style={{
                borderColor: 'var(--color-border)',
                backgroundColor: 'var(--color-bg-elevated)',
              }}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-2">
                    <FileText className="w-5 h-5 shrink-0" style={{ color: 'var(--color-text-secondary)' }} />
                    <h3
                      className="text-lg font-medium truncate"
                      style={{ color: 'var(--color-text-primary)' }}
                    >
                      {doc.title}
                    </h3>
                  </div>
                  
                  <div className="flex items-center gap-4 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                    <div className="flex items-center gap-1">
                      <Calendar className="w-4 h-4" />
                      <span>Создан: {formatDate(doc.created_at)}</span>
                    </div>
                    {doc.updated_at !== doc.created_at && (
                      <div className="flex items-center gap-1">
                        <Edit className="w-4 h-4" />
                        <span>Обновлен: {formatDate(doc.updated_at)}</span>
                      </div>
                    )}
                  </div>
                </div>
                
                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={(e) => handleDelete(doc.id, e)}
                    disabled={deletingId === doc.id}
                    style={{ borderColor: 'var(--color-border)' }}
                  >
                    {deletingId === doc.id ? (
                      'Удаление...'
                    ) : (
                      <>
                        <Trash2 className="w-4 h-4 mr-2" />
                        Удалить
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

