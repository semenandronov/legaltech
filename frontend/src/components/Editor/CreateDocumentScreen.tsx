import React, { useState } from 'react'
import { FileText, Plus, Loader2 } from 'lucide-react'
import { Button } from '@/components/UI/Button'
import Input from '@/components/UI/Input'
import { toast } from 'sonner'
import { createDocument } from '@/services/documentEditorApi'

interface CreateDocumentScreenProps {
  caseId: string
  onDocumentCreated: (documentId: string) => void
}

export const CreateDocumentScreen: React.FC<CreateDocumentScreenProps> = ({
  caseId,
  onDocumentCreated,
}) => {
  const [title, setTitle] = useState('')
  const [loading, setLoading] = useState(false)

  const handleCreate = async () => {
    if (!title.trim()) {
      toast.error('Введите название документа')
      return
    }

    try {
      setLoading(true)
      const doc = await createDocument(caseId, title.trim(), '')
      toast.success('Документ создан')
      onDocumentCreated(doc.id)
    } catch (error: any) {
      toast.error(error.message || 'Ошибка при создании документа')
    } finally {
      setLoading(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !loading) {
      handleCreate()
    }
  }

  return (
    <div className="flex-1 flex items-center justify-center p-6">
      <div className="max-w-md w-full text-center">
        <div className="mb-8">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full flex items-center justify-center" style={{ backgroundColor: 'var(--color-bg-elevated)' }}>
            <FileText className="w-8 h-8" style={{ color: 'var(--color-text-secondary)' }} />
          </div>
          <h2 className="text-2xl font-semibold mb-2" style={{ color: 'var(--color-text-primary)' }}>
            Создайте документ
          </h2>
          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            Начните работу с новым документом в редакторе
          </p>
        </div>

        <div className="space-y-4">
          <div>
            <Input
              value={title}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setTitle(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Название документа"
              disabled={loading}
              autoFocus
              className="text-center"
            />
          </div>

          <Button
            onClick={handleCreate}
            disabled={!title.trim() || loading}
            className="w-full"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Создание...
              </>
            ) : (
              <>
                <Plus className="w-4 h-4 mr-2" />
                Создать документ
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  )
}

