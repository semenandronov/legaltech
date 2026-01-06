import React, { useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/UI/dialog'
import { Button } from '@/components/UI/Button'
import { Checkbox } from '@/components/UI/Checkbox'
import { Textarea } from '@/components/UI/Textarea'
import { AlertCircle, AlertTriangle, CheckCircle2 } from 'lucide-react'
import { logger } from '@/lib/logger'

interface TableClarificationModalProps {
  questions: string[]
  context: {
    task?: string
    table_name?: string
    partial_columns?: any[]
  }
  availableDocTypes: string[]
  onSubmit: (answer: { doc_types?: string[], columns_clarification?: string }) => Promise<void>
}

// Маппинг типов документов на русские названия
const DOC_TYPE_LABELS: Record<string, string> = {
  'contract': 'Договор',
  'statement_of_claim': 'Исковое заявление',
  'court_decision': 'Решение суда',
  'correspondence': 'Переписка',
  'motion': 'Ходатайство',
  'appeal': 'Апелляционная жалоба',
  'court_ruling': 'Определение суда',
  'court_resolution': 'Постановление',
  'response_to_claim': 'Отзыв на иск',
  'counterclaim': 'Встречный иск',
  'pre_claim': 'Претензия',
  'power_of_attorney': 'Доверенность',
  'act': 'Акт',
  'certificate': 'Справка',
  'protocol': 'Протокол',
  'expert_opinion': 'Заключение эксперта',
}

export const TableClarificationModal: React.FC<TableClarificationModalProps> = ({
  questions,
  context,
  availableDocTypes,
  onSubmit,
}) => {
  const [selectedDocTypes, setSelectedDocTypes] = useState<string[]>([])
  const [columnsClarification, setColumnsClarification] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleDocTypeToggle = (docType: string) => {
    setSelectedDocTypes((prev) =>
      prev.includes(docType)
        ? prev.filter((t) => t !== docType)
        : [...prev, docType]
    )
    setError(null)
  }

  const handleSubmit = async () => {
    if (isSubmitting) return

    // Валидация: хотя бы один doc_type выбран или текстовое уточнение
    if (selectedDocTypes.length === 0 && !columnsClarification.trim()) {
      setError('Пожалуйста, выберите типы документов или укажите уточнение')
      return
    }

    setIsSubmitting(true)
    setError(null)

    try {
      const answer: { doc_types?: string[], columns_clarification?: string } = {}
      
      if (selectedDocTypes.length > 0) {
        answer.doc_types = selectedDocTypes
      }
      
      if (columnsClarification.trim()) {
        answer.columns_clarification = columnsClarification.trim()
      }

      await onSubmit(answer)
      logger.info(`Table clarification submitted: ${JSON.stringify(answer)}`)
    } catch (err) {
      logger.error(`Error submitting table clarification: ${err}`)
      setError('Ошибка при отправке ответа. Попробуйте еще раз.')
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog open={true}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertCircle className="w-5 h-5 text-amber-600" />
            Уточнение для создания таблицы
          </DialogTitle>
          <DialogDescription>
            Для создания таблицы "{context.table_name || 'Данные из документов'}" требуется дополнительная информация
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Вопросы */}
          {questions.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-sm font-semibold text-gray-900">Вопросы:</h4>
              <ul className="list-disc list-inside space-y-1 text-sm text-gray-700">
                {questions.map((q, idx) => (
                  <li key={idx}>{q}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Выбор типов документов */}
          <div className="space-y-2">
            <h4 className="text-sm font-semibold text-gray-900">
              Выберите типы документов:
            </h4>
            
            {availableDocTypes.length === 0 ? (
              <div className="p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 text-yellow-600 mt-0.5" />
                  <div className="text-sm text-yellow-800">
                    <p className="font-medium mb-1">Документы не классифицированы</p>
                    <p className="text-xs">
                      Документы в деле еще не классифицированы по типам. 
                      Таблица будет создана из всех документов, или вы можете запустить классификацию.
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-2 max-h-60 overflow-y-auto border border-gray-200 rounded-lg p-3">
                {availableDocTypes.map((docType) => {
                  const label = DOC_TYPE_LABELS[docType] || docType
                  const isSelected = selectedDocTypes.includes(docType)
                  
                  return (
                    <label
                      key={docType}
                      className="flex items-center gap-2 p-2 rounded hover:bg-gray-50 cursor-pointer"
                    >
                      <Checkbox
                        checked={isSelected}
                        onCheckedChange={() => handleDocTypeToggle(docType)}
                      />
                      <span className="text-sm text-gray-700">{label}</span>
                    </label>
                  )
                })}
              </div>
            )}
          </div>

          {/* Уточнение колонок */}
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-gray-900">
              Уточнение по колонкам (опционально):
            </label>
            <Textarea
              value={columnsClarification}
              onChange={(e) => {
                setColumnsClarification(e.target.value)
                setError(null)
              }}
              placeholder="Если нужно уточнить какие колонки должны быть в таблице, укажите здесь..."
              rows={3}
              disabled={isSubmitting}
              className="text-sm"
            />
          </div>

          {/* Контекст */}
          {context.task && (
            <div className="p-3 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-600 mb-1">Исходная задача:</p>
              <p className="text-sm text-gray-800">{context.task}</p>
            </div>
          )}

          {/* Ошибка */}
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-700">{error}</p>
            </div>
          )}

          {/* Кнопки */}
          <div className="flex gap-2 justify-end pt-4 border-t">
            <Button
              onClick={handleSubmit}
              disabled={isSubmitting || (selectedDocTypes.length === 0 && !columnsClarification.trim())}
              className="bg-blue-600 hover:bg-blue-700"
            >
              {isSubmitting ? (
                <>
                  <span className="animate-spin mr-2">⏳</span>
                  Отправка...
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4 mr-2" />
                  Продолжить
                </>
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

