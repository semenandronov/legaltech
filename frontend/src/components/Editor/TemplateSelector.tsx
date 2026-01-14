import React, { useState } from 'react'
import { FileText, Search, Loader2 } from 'lucide-react'
import { Button } from '@/components/UI/Button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/UI/dialog'
import { Input } from '@/components/UI/Input'
import { Textarea } from '@/components/UI/Textarea'
import { toast } from 'sonner'
import { createDocument } from '@/services/documentEditorApi'
import { useNavigate } from 'react-router-dom'

interface TemplateSelectorProps {
  caseId: string
  isOpen: boolean
  onClose: () => void
}

const TEMPLATE_SUGGESTIONS = [
  { label: 'Договор поставки', query: 'Создай договор поставки товаров' },
  { label: 'Договор аренды', query: 'Создай договор аренды недвижимости' },
  { label: 'Договор подряда', query: 'Создай договор подряда на выполнение работ' },
  { label: 'Договор оказания услуг', query: 'Создай договор оказания услуг' },
  { label: 'Договор купли-продажи', query: 'Создай договор купли-продажи' },
  { label: 'Соглашение о расторжении', query: 'Создай соглашение о расторжении договора' },
  { label: 'Дополнительное соглашение', query: 'Создай дополнительное соглашение к договору' },
  { label: 'Претензия', query: 'Создай претензию' },
  { label: 'Исковое заявление', query: 'Создай исковое заявление' },
]

export const TemplateSelector: React.FC<TemplateSelectorProps> = ({
  caseId,
  isOpen,
  onClose,
}) => {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [title, setTitle] = useState('')
  const [loading, setLoading] = useState(false)

  const handleCreate = async () => {
    if (!query.trim()) {
      toast.error('Введите описание документа')
      return
    }

    try {
      setLoading(true)
      // Create empty document first
      const doc = await createDocument(caseId, title || 'Новый документ', '')
      
      // Navigate to editor and trigger AI creation via chat
      navigate(`/cases/${caseId}/editor/${doc.id}`)
      toast.success('Документ создан. Используйте чат для создания из шаблона.')
      onClose()
      setQuery('')
      setTitle('')
    } catch (error: any) {
      toast.error(error.message || 'Ошибка при создании документа')
    } finally {
      setLoading(false)
    }
  }

  const handleSuggestionClick = (suggestion: string) => {
    setQuery(suggestion)
    if (!title) {
      // Extract title from suggestion
      const titleMatch = suggestion.match(/Создай (.+)/)
      if (titleMatch) {
        setTitle(titleMatch[1])
      }
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="w-5 h-5" />
            Создать документ из шаблона
          </DialogTitle>
          <DialogDescription>
            Опишите, какой документ вам нужен. ИИ создаст его на основе шаблонов.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium mb-2 block">Название документа</label>
            <Input
              value={title}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setTitle(e.target.value)}
              placeholder="Например: Договор поставки №1"
            />
          </div>

          <div>
            <label className="text-sm font-medium mb-2 block">Описание документа</label>
            <Textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Например: Создай договор поставки товаров с условиями оплаты и доставки"
              rows={4}
            />
          </div>

          <div>
            <label className="text-sm font-medium mb-2 block flex items-center gap-2">
              <Search className="w-4 h-4" />
              Быстрые шаблоны
            </label>
            <div className="grid grid-cols-2 gap-2">
              {TEMPLATE_SUGGESTIONS.map((suggestion, index) => (
                <Button
                  key={index}
                  variant="outline"
                  size="sm"
                  onClick={() => handleSuggestionClick(suggestion.query)}
                  className="text-left justify-start"
                >
                  {suggestion.label}
                </Button>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-4">
            <Button onClick={onClose} variant="outline" disabled={loading}>
              Отмена
            </Button>
            <Button onClick={handleCreate} disabled={!query.trim() || loading}>
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Создание...
                </>
              ) : (
                'Создать документ'
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

