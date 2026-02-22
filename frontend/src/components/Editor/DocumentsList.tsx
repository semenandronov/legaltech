import React, { useState } from 'react'
import { FileText, Trash2, Calendar, Edit, Plus, Loader2, Upload } from 'lucide-react'
import { Button } from '@/components/UI/Button'
import Input from '@/components/UI/Input'
import { toast } from 'sonner'
import { Document, deleteDocument, createDocument } from '@/services/documentEditorApi'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale/ru'

interface DocumentsListProps {
  documents: Document[]
  caseId: string
  onDocumentSelect: (documentId: string) => void
  onDocumentDeleted?: () => void
  onDocumentCreated?: (documentId: string) => void
  onImportDocx?: () => void
}

export const DocumentsList: React.FC<DocumentsListProps> = ({
  documents,
  caseId,
  onDocumentSelect,
  onDocumentDeleted,
  onDocumentCreated,
  onImportDocx,
}) => {
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [creating, setCreating] = useState(false)

  const handleDelete = async (documentId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('Вы уверены, что хотите удалить этот документ?')) return
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

  const handleCreate = async () => {
    if (!newTitle.trim()) {
      toast.error('Введите название документа')
      return
    }
    try {
      setCreating(true)
      const doc = await createDocument(caseId, newTitle.trim(), '')
      toast.success('Документ создан')
      onDocumentCreated?.(doc.id)
    } catch (error: any) {
      toast.error(error.message || 'Ошибка при создании документа')
    } finally {
      setCreating(false)
    }
  }

  const formatDate = (dateString: string) => {
    try {
      return format(new Date(dateString), 'dd MMMM yyyy, HH:mm', { locale: ru })
    } catch {
      return dateString
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>
            Документы редактора
          </h2>
          {!showCreate && (
            <div className="flex items-center gap-2">
              {onImportDocx && (
                <Button variant="outline" onClick={onImportDocx} size="sm">
                  <Upload className="w-4 h-4 mr-2" />
                  Импорт DOCX
                </Button>
              )}
              <Button onClick={() => setShowCreate(true)} size="sm">
                <Plus className="w-4 h-4 mr-2" />
                Новый документ
              </Button>
            </div>
          )}
        </div>

        {/* Inline create form */}
        {showCreate && (
          <div
            className="mb-6 p-4 rounded-lg border"
            style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-elevated)' }}
          >
            <p className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-primary)' }}>
              Новый документ
            </p>
            <div className="flex gap-3">
              <Input
                value={newTitle}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewTitle(e.target.value)}
                onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => {
                  if (e.key === 'Enter' && !creating) handleCreate()
                  if (e.key === 'Escape') { setShowCreate(false); setNewTitle('') }
                }}
                placeholder="Название документа"
                disabled={creating}
                autoFocus
                className="flex-1"
              />
              <Button onClick={handleCreate} disabled={!newTitle.trim() || creating}>
                {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Создать'}
              </Button>
              <Button
                variant="outline"
                onClick={() => { setShowCreate(false); setNewTitle('') }}
                disabled={creating}
              >
                Отмена
              </Button>
            </div>
          </div>
        )}

        {/* Empty state */}
        {documents.length === 0 && !showCreate && (
          <div className="text-center py-20">
            <div
              className="w-16 h-16 mx-auto mb-4 rounded-full flex items-center justify-center"
              style={{ backgroundColor: 'var(--color-bg-elevated)' }}
            >
              <FileText className="w-8 h-8" style={{ color: 'var(--color-text-secondary)' }} />
            </div>
            <h3 className="text-xl font-semibold mb-2" style={{ color: 'var(--color-text-primary)' }}>
              Нет документов
            </h3>
            <p className="text-sm mb-6" style={{ color: 'var(--color-text-secondary)' }}>
              Создайте первый документ для работы в редакторе
            </p>
            <Button onClick={() => setShowCreate(true)}>
              <Plus className="w-4 h-4 mr-2" />
              Создать документ
            </Button>
          </div>
        )}

        {/* Document grid */}
        {documents.length > 0 && (
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
        )}
      </div>
    </div>
  )
}
