import { BubbleMenu, Editor } from '@tiptap/react'
import { Wand2, RefreshCw, Minimize2, AlertTriangle, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { aiAssist, RiskItem } from '../../services/documentEditorApi'
import { toast } from 'sonner'

interface SelectionMenuProps {
  editor: Editor
  documentId?: string
  onReplaceSelection?: (text: string) => void
  onSetRisks?: (risks: RiskItem[]) => void
}

type AIAction = 'improve' | 'rewrite' | 'simplify' | 'check_risks'

export const SelectionMenu = ({ 
  editor, 
  documentId,
  onReplaceSelection,
  onSetRisks 
}: SelectionMenuProps) => {
  const [loadingAction, setLoadingAction] = useState<AIAction | null>(null)

  const handleAIAction = async (action: AIAction) => {
    if (!documentId) {
      toast.error('Сначала сохраните документ')
      return
    }

    const { from, to } = editor.state.selection
    const selectedText = editor.state.doc.textBetween(from, to)

    if (!selectedText) {
      toast.error('Выделите текст')
      return
    }

    setLoadingAction(action)

    try {
      const result = await aiAssist(documentId, action, selectedText, '')

      if (action === 'check_risks') {
        if (result.risks && result.risks.length > 0 && onSetRisks) {
          onSetRisks(result.risks)
          toast.success(`Найдено ${result.risks.length} риск(ов)`)
        } else {
          toast.success('Рисков не обнаружено')
        }
      } else if (result.result) {
        // Replace selected text with improved version
        editor
          .chain()
          .focus()
          .deleteRange({ from, to })
          .insertContent(result.result)
          .run()
        
        if (onReplaceSelection) {
          onReplaceSelection(result.result)
        }
        
        toast.success('Текст обновлен')
      } else {
        toast.error('Не удалось обработать текст')
      }
    } catch (error: any) {
      toast.error(error.message || 'Ошибка AI')
    } finally {
      setLoadingAction(null)
    }
  }

  const actions = [
    { id: 'improve' as AIAction, icon: Wand2, label: 'Улучшить', title: 'Улучшить текст' },
    { id: 'rewrite' as AIAction, icon: RefreshCw, label: 'Переписать', title: 'Переписать текст' },
    { id: 'simplify' as AIAction, icon: Minimize2, label: 'Упростить', title: 'Упростить текст' },
    { id: 'check_risks' as AIAction, icon: AlertTriangle, label: 'Риски', title: 'Проверить на риски' },
  ]

  // Only show if document is saved
  if (!documentId) {
    return null
  }

  return (
    <BubbleMenu
      editor={editor}
      tippyOptions={{
        duration: 100,
        placement: 'top',
        hideOnClick: false,
      }}
      className="bg-white rounded-lg shadow-lg border border-gray-200 flex items-center p-1 gap-0.5"
    >
      {actions.map((action) => {
        const Icon = action.icon
        const isLoading = loadingAction === action.id

        return (
          <button
            key={action.id}
            onClick={() => handleAIAction(action.id)}
            disabled={loadingAction !== null}
            className={`
              flex items-center gap-1.5 px-2.5 py-1.5 rounded text-sm font-medium
              transition-colors duration-150
              ${isLoading 
                ? 'bg-blue-100 text-blue-700' 
                : 'hover:bg-gray-100 text-gray-700'
              }
              disabled:opacity-50 disabled:cursor-not-allowed
            `}
            title={action.title}
            aria-label={action.title}
          >
            {isLoading ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Icon className="w-3.5 h-3.5" aria-hidden="true" />
            )}
            <span className="hidden sm:inline">{action.label}</span>
          </button>
        )
      })}
    </BubbleMenu>
  )
}

