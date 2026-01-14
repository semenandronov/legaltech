import { useState } from 'react'
import { Sparkles, FileText, AlertTriangle, Wand2, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { aiAssist } from '../../services/documentEditorApi'

interface AIAssistantSidebarProps {
  caseId?: string
  documentId?: string
  selectedText: string
  onInsertText: (text: string) => void
  onReplaceText?: (text: string) => void
}

export const AIAssistantSidebar = ({
  documentId,
  selectedText,
  onInsertText,
  onReplaceText
}: AIAssistantSidebarProps) => {
  const [prompt, setPrompt] = useState('')
  const [loading, setLoading] = useState(false)
  const [activeCommand, setActiveCommand] = useState<string | null>(null)

  const handleAICommand = async (command: string, customPrompt: string = '') => {
    if (!documentId) {
      toast.error('Сначала сохраните документ')
      return
    }

    setLoading(true)
    setActiveCommand(command)

    try {
      const result = await aiAssist(documentId, command, selectedText, customPrompt || prompt)
      
      if (result.result) {
        // If text is selected, replace it; otherwise insert
        if (selectedText && onReplaceText) {
          onReplaceText(result.result)
          toast.success('Текст заменен')
        } else {
          onInsertText(result.result)
          toast.success('Текст добавлен в документ')
        }
      } else {
        toast.error('Не удалось получить результат от AI')
      }
    } catch (error: any) {
      toast.error(error.message || 'Ошибка при выполнении AI команды')
    } finally {
      setLoading(false)
      setActiveCommand(null)
      setPrompt('')
    }
  }

  const quickActions = [
    {
      id: 'create_contract',
      label: 'Создать договор',
      icon: FileText,
      command: 'create_contract',
      description: 'Создать договор с помощью AI'
    },
    {
      id: 'check_risks',
      label: 'Проверить на риски',
      icon: AlertTriangle,
      command: 'check_risks',
      description: 'Проверить текст на юридические риски'
    },
    {
      id: 'improve',
      label: 'Улучшить текст',
      icon: Wand2,
      command: 'improve',
      description: 'Улучшить текст профессионально'
    },
  ]

  const textActions = [
    {
      id: 'rewrite',
      label: 'Переписать',
      command: 'rewrite',
      description: 'Переписать текст'
    },
    {
      id: 'simplify',
      label: 'Упростить',
      command: 'simplify',
      description: 'Упростить текст'
    },
  ]

  return (
    <div 
      className="w-80 border-l bg-gray-50 p-4 overflow-y-auto"
      style={{ 
        borderLeftColor: 'var(--color-border)',
        backgroundColor: 'var(--color-bg-secondary)' 
      }}
    >
      <h3 className="font-semibold mb-4 flex items-center gap-2 text-lg" style={{ color: 'var(--color-text-primary)' }}>
        <Sparkles className="w-5 h-5 text-blue-600" />
        AI Помощник
      </h3>

      {/* Quick Actions */}
      <div className="space-y-2 mb-6">
        <p className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
          Быстрые действия:
        </p>
        {quickActions.map(action => (
          <button
            key={action.id}
            onClick={() => handleAICommand(action.command)}
            disabled={loading || !documentId}
            className={`w-full text-left px-3 py-2 rounded-lg transition-all duration-150 flex items-center gap-2 ${
              loading && activeCommand === action.command
                ? 'bg-blue-100 text-blue-700'
                : 'hover:bg-gray-200'
            } disabled:opacity-50 disabled:cursor-not-allowed`}
            style={{ 
              backgroundColor: loading && activeCommand === action.command ? 'var(--color-bg-hover)' : 'transparent',
              color: 'var(--color-text-primary)'
            }}
            title={action.description}
          >
            {loading && activeCommand === action.command ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <action.icon className="w-4 h-4" />
            )}
            <span className="flex-1">{action.label}</span>
          </button>
        ))}
      </div>

      {/* Selected Text */}
      {selectedText && (
        <div className="mb-6 p-3 bg-blue-50 rounded-lg border border-blue-200">
          <p className="text-xs font-medium text-gray-500 mb-2">Выделенный текст:</p>
          <p className="text-sm mb-3 line-clamp-3" style={{ color: 'var(--color-text-primary)' }}>
            {selectedText.slice(0, 150)}{selectedText.length > 150 ? '...' : ''}
          </p>
          <div className="flex flex-wrap gap-2">
            {textActions.map(action => (
              <button
                key={action.id}
                onClick={() => handleAICommand(action.command)}
                disabled={loading || !documentId}
                className="px-3 py-1.5 text-xs bg-white border rounded hover:bg-gray-50 disabled:opacity-50 transition-colors"
                style={{ 
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-primary)'
                }}
                title={action.description}
              >
                {action.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Custom Prompt */}
      <div>
        <p className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
          Кастомный запрос:
        </p>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Что сделать с текстом?"
          className="w-full p-2 border rounded-lg resize-none text-sm"
          style={{ 
            borderColor: 'var(--color-border)',
            backgroundColor: 'var(--color-bg-primary)',
            color: 'var(--color-text-primary)'
          }}
          rows={3}
          disabled={loading || !documentId}
        />
        <button
          onClick={() => handleAICommand('custom', prompt)}
          disabled={!prompt || loading || !documentId}
          className="mt-2 w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
        >
          {loading && activeCommand === 'custom' ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Выполнение...</span>
            </>
          ) : (
            <span>Выполнить</span>
          )}
        </button>
      </div>

      {!documentId && (
        <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
          <p className="text-xs text-yellow-800">
            Сохраните документ, чтобы использовать AI функции
          </p>
        </div>
      )}
    </div>
  )
}

