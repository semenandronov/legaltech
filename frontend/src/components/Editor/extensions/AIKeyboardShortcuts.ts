import { Extension } from '@tiptap/core'
import { aiAssist, RiskItem } from '../../../services/documentEditorApi'
import { toast } from 'sonner'

export interface AIKeyboardShortcutsOptions {
  documentId?: string
  onImproveText?: (text: string) => void
  onSetRisks?: (risks: RiskItem[]) => void
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    aiKeyboardShortcuts: {
      improveSelectedText: () => ReturnType
      checkSelectedTextRisks: () => ReturnType
      simplifySelectedText: () => ReturnType
    }
  }
}

export const AIKeyboardShortcuts = Extension.create<AIKeyboardShortcutsOptions>({
  name: 'aiKeyboardShortcuts',

  addOptions() {
    return {
      documentId: undefined,
      onImproveText: undefined,
      onSetRisks: undefined,
    }
  },

  addCommands() {
    return {
      improveSelectedText: () => ({ editor }) => {
        const { documentId, onImproveText } = this.options
        if (!documentId) {
          toast.error('Сохраните документ для использования AI')
          return false
        }

        const { from, to } = editor.state.selection
        const selectedText = editor.state.doc.textBetween(from, to)

        if (!selectedText) {
          toast.error('Выделите текст для улучшения')
          return false
        }

        // Run async operation
        const improve = async () => {
          const loadingToast = toast.loading('Улучшение текста…')
          try {
            const result = await aiAssist(documentId, 'improve', selectedText, '')
            if (result.result) {
              editor
                .chain()
                .focus()
                .deleteRange({ from, to })
                .insertContent(result.result)
                .run()
              
              if (onImproveText) {
                onImproveText(result.result)
              }
              toast.success('Текст улучшен', { id: loadingToast })
            } else {
              toast.error('Не удалось улучшить текст', { id: loadingToast })
            }
          } catch (error: any) {
            toast.error(error.message || 'Ошибка AI', { id: loadingToast })
          }
        }

        improve()
        return true
      },

      checkSelectedTextRisks: () => ({ editor }) => {
        const { documentId, onSetRisks } = this.options
        if (!documentId) {
          toast.error('Сохраните документ для использования AI')
          return false
        }

        const { from, to } = editor.state.selection
        const selectedText = from !== to 
          ? editor.state.doc.textBetween(from, to)
          : editor.state.doc.textContent

        if (!selectedText) {
          toast.error('Нет текста для проверки')
          return false
        }

        // Run async operation
        const checkRisks = async () => {
          const loadingToast = toast.loading('Проверка рисков…')
          try {
            const result = await aiAssist(documentId, 'check_risks', selectedText, '')
            if (result.risks && result.risks.length > 0 && onSetRisks) {
              onSetRisks(result.risks)
              toast.success(`Найдено ${result.risks.length} риск(ов)`, { id: loadingToast })
            } else {
              toast.success('Рисков не обнаружено', { id: loadingToast })
            }
          } catch (error: any) {
            toast.error(error.message || 'Ошибка AI', { id: loadingToast })
          }
        }

        checkRisks()
        return true
      },

      simplifySelectedText: () => ({ editor }) => {
        const { documentId, onImproveText } = this.options
        if (!documentId) {
          toast.error('Сохраните документ для использования AI')
          return false
        }

        const { from, to } = editor.state.selection
        const selectedText = editor.state.doc.textBetween(from, to)

        if (!selectedText) {
          toast.error('Выделите текст для упрощения')
          return false
        }

        // Run async operation
        const simplify = async () => {
          const loadingToast = toast.loading('Упрощение текста…')
          try {
            const result = await aiAssist(documentId, 'simplify', selectedText, '')
            if (result.result) {
              editor
                .chain()
                .focus()
                .deleteRange({ from, to })
                .insertContent(result.result)
                .run()
              
              if (onImproveText) {
                onImproveText(result.result)
              }
              toast.success('Текст упрощен', { id: loadingToast })
            } else {
              toast.error('Не удалось упростить текст', { id: loadingToast })
            }
          } catch (error: any) {
            toast.error(error.message || 'Ошибка AI', { id: loadingToast })
          }
        }

        simplify()
        return true
      },
    }
  },

  addKeyboardShortcuts() {
    return {
      // Cmd/Ctrl + Shift + I — Improve selected text
      'Mod-Shift-i': () => this.editor.commands.improveSelectedText(),
      
      // Cmd/Ctrl + Shift + R — Check for risks
      'Mod-Shift-r': () => this.editor.commands.checkSelectedTextRisks(),
      
      // Cmd/Ctrl + Shift + S — Simplify selected text
      'Mod-Shift-s': () => this.editor.commands.simplifySelectedText(),
    }
  },
})

