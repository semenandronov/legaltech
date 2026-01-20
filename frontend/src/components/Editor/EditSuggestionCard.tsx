import React, { useState } from 'react'
import { Check, X, ArrowRight, ChevronDown, ChevronUp } from 'lucide-react'
import type { StructuredEdit } from '@/services/documentEditorApi'

interface EditSuggestionCardProps {
  edit: StructuredEdit
  onApply: (edit: StructuredEdit) => void
  onSkip: (edit: StructuredEdit) => void
  onNavigate: (text: string) => void
  isApplied?: boolean
  isSkipped?: boolean
}

export const EditSuggestionCard: React.FC<EditSuggestionCardProps> = ({
  edit,
  onApply,
  onSkip,
  onNavigate,
  isApplied = false,
  isSkipped = false,
}) => {
  const [isExpanded, setIsExpanded] = useState(true)
  
  const isProcessed = isApplied || isSkipped
  
  // Функция для подсветки различий между оригиналом и новым текстом
  const highlightDiff = (original: string, newText: string) => {
    // Простая подсветка - показываем полный текст
    // В будущем можно добавить более сложный diff алгоритм
    return { original, newText }
  }
  
  const { original, newText } = highlightDiff(edit.original_text, edit.new_text)
  
  return (
    <div 
      className={`rounded-lg border overflow-hidden transition-all duration-200 ${
        isApplied 
          ? 'border-green-300 bg-green-50/50' 
          : isSkipped 
            ? 'border-gray-200 bg-gray-50/50 opacity-60' 
            : 'border-amber-200 bg-amber-50/30'
      }`}
    >
      {/* Заголовок карточки */}
      <div 
        className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-black/5 transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${
            isApplied ? 'bg-green-500' : isSkipped ? 'bg-gray-400' : 'bg-amber-500'
          }`} />
          <span className="text-sm font-medium text-gray-700">
            {isApplied ? 'Изменение применено' : isSkipped ? 'Изменение пропущено' : 'Предлагаемое изменение'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {!isProcessed && edit.found_in_document && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onNavigate(edit.original_text)
              }}
              className="p-1.5 rounded-md hover:bg-amber-200/50 text-amber-700 transition-colors"
              title="Перейти к месту в документе"
              aria-label="Перейти к месту в документе"
            >
              <ArrowRight className="w-4 h-4" />
            </button>
          )}
          {isExpanded ? (
            <ChevronUp className="w-4 h-4 text-gray-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-gray-400" />
          )}
        </div>
      </div>
      
      {/* Содержимое карточки */}
      {isExpanded && (
        <div className="px-4 pb-4">
          {/* Контекст (если есть) */}
          {edit.context_before && (
            <div className="text-xs text-gray-400 mb-1 truncate">
              ...{edit.context_before}
            </div>
          )}
          
          {/* Блок "Было" */}
          <div className="mb-3">
            <div className="text-xs font-medium text-red-600 mb-1 uppercase tracking-wide">
              Было:
            </div>
            <div className="px-3 py-2 rounded-md bg-red-50 border border-red-200">
              <span className="text-sm text-red-800 line-through decoration-red-400">
                {original}
              </span>
            </div>
          </div>
          
          {/* Стрелка вниз */}
          <div className="flex justify-center my-2">
            <div className="w-6 h-6 rounded-full bg-gray-100 flex items-center justify-center">
              <ChevronDown className="w-4 h-4 text-gray-400" />
            </div>
          </div>
          
          {/* Блок "Стало" */}
          <div className="mb-4">
            <div className="text-xs font-medium text-green-600 mb-1 uppercase tracking-wide">
              Стало:
            </div>
            <div className="px-3 py-2 rounded-md bg-green-50 border border-green-200">
              <span className="text-sm text-green-800 font-medium">
                {newText}
              </span>
            </div>
          </div>
          
          {/* Контекст после (если есть) */}
          {edit.context_after && (
            <div className="text-xs text-gray-400 mb-3 truncate">
              {edit.context_after}...
            </div>
          )}
          
          {/* Предупреждение если текст не найден */}
          {!edit.found_in_document && (
            <div className="mb-3 px-3 py-2 rounded-md bg-yellow-50 border border-yellow-200">
              <span className="text-xs text-yellow-700">
                Текст не найден в документе. Возможно, документ был изменен.
              </span>
            </div>
          )}
          
          {/* Кнопки действий */}
          {!isProcessed && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => onApply(edit)}
                disabled={!edit.found_in_document}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-green-600 text-white text-sm font-medium hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Check className="w-4 h-4" />
                Применить
              </button>
              <button
                onClick={() => onSkip(edit)}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-gray-100 text-gray-700 text-sm font-medium hover:bg-gray-200 transition-colors"
              >
                <X className="w-4 h-4" />
                Пропустить
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

interface EditSuggestionsListProps {
  edits: StructuredEdit[]
  onApply: (edit: StructuredEdit) => void
  onSkip: (edit: StructuredEdit) => void
  onNavigate: (text: string) => void
  onApplyAll: () => void
  onSkipAll: () => void
  appliedIds: Set<string>
  skippedIds: Set<string>
}

export const EditSuggestionsList: React.FC<EditSuggestionsListProps> = ({
  edits,
  onApply,
  onSkip,
  onNavigate,
  onApplyAll,
  onSkipAll,
  appliedIds,
  skippedIds,
}) => {
  const pendingEdits = edits.filter(e => !appliedIds.has(e.id) && !skippedIds.has(e.id))
  const hasFoundEdits = pendingEdits.some(e => e.found_in_document)
  
  if (edits.length === 0) return null
  
  return (
    <div className="mt-4 space-y-3">
      {/* Заголовок списка */}
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium text-gray-700">
          Предложенные изменения ({edits.length})
        </div>
        {pendingEdits.length > 1 && (
          <div className="flex items-center gap-2">
            <button
              onClick={onApplyAll}
              disabled={!hasFoundEdits}
              className="text-xs px-2 py-1 rounded bg-green-100 text-green-700 hover:bg-green-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Применить все
            </button>
            <button
              onClick={onSkipAll}
              className="text-xs px-2 py-1 rounded bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors"
            >
              Пропустить все
            </button>
          </div>
        )}
      </div>
      
      {/* Список карточек */}
      <div className="space-y-2">
        {edits.map((edit) => (
          <EditSuggestionCard
            key={edit.id}
            edit={edit}
            onApply={onApply}
            onSkip={onSkip}
            onNavigate={onNavigate}
            isApplied={appliedIds.has(edit.id)}
            isSkipped={skippedIds.has(edit.id)}
          />
        ))}
      </div>
    </div>
  )
}

export default EditSuggestionCard





