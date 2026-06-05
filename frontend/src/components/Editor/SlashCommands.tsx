import React from 'react'
import { Extension } from '@tiptap/core'
import { ReactRenderer } from '@tiptap/react'
import Suggestion from '@tiptap/suggestion'
import tippy, { Instance as TippyInstance } from 'tippy.js'
import { FileText, List, Table, Sparkles, AlertTriangle, Wand2, Quote, Strikethrough, Code } from 'lucide-react'
import { aiAssist, RiskItem } from '../../services/documentEditorApi'
import { toast } from 'sonner'
import { getWordRangeAtPos } from '@/utils/docTextPosition'
import type { Editor } from '@tiptap/react'

function toggleMarkOnWordAfterSlash(
  editor: Editor,
  range: { from: number; to: number },
  applyMark: (chain: ReturnType<Editor['chain']>) => ReturnType<Editor['chain']>,
) {
  editor.chain().focus().deleteRange(range).run()
  const pos = editor.state.selection.from
  const word = getWordRangeAtPos(editor.state.doc, pos)
  let chain = editor.chain().focus()
  if (word) {
    chain = chain.setTextSelection(word)
  }
  applyMark(chain).run()
}

interface SlashCommandsOptions {
  caseId?: string
  documentId?: string
  onInsertText?: (text: string) => void
  onSetRisks?: (risks: RiskItem[]) => void
}

const SlashCommands = Extension.create<SlashCommandsOptions>({
  name: 'slashCommands',

  addOptions() {
    return {
      ...this.parent?.(),
      caseId: undefined,
      documentId: undefined,
      onInsertText: undefined,
      onSetRisks: undefined,
    }
  },

  addProseMirrorPlugins() {
    const options = this.options
    return [
      Suggestion({
        editor: this.editor,
        char: '/',
        command: ({ editor, range, props }: any) => {
          props.command({ editor, range })
        },
        items: ({ query }: any) => {
          return getSuggestionItems({
            query,
            caseId: options.caseId,
            documentId: options.documentId,
            onInsertText: options.onInsertText,
            onSetRisks: options.onSetRisks,
          })
        },
        render: () => {
          let component: ReactRenderer
          let popup: TippyInstance[]

          return {
            onStart: (props: any) => {
              const items = getSuggestionItems({
                query: props.query,
                caseId: options.caseId,
                documentId: options.documentId,
                onInsertText: options.onInsertText,
                onSetRisks: options.onSetRisks,
              })

              component = new ReactRenderer(CommandList, {
                props: { items, command: props.command },
                editor: props.editor,
              })

              if (!props.clientRect) {
                return
              }

              popup = tippy('body', {
                getReferenceClientRect: props.clientRect,
                appendTo: () => document.body,
                content: component.element,
                showOnCreate: true,
                interactive: true,
                trigger: 'manual',
                placement: 'bottom-start',
              })
            },

            onUpdate(props: any) {
              const items = getSuggestionItems({
                query: props.query,
                caseId: options.caseId,
                documentId: options.documentId,
                onInsertText: options.onInsertText,
                onSetRisks: options.onSetRisks,
              })

              component.updateProps({ items, command: props.command })

              if (!props.clientRect) {
                return
              }

              popup[0].setProps({
                getReferenceClientRect: props.clientRect,
              })
            },

            onKeyDown(props: any) {
              if (props.event.key === 'Escape') {
                popup[0].hide()
                return true
              }

              if (component.ref && typeof (component.ref as any).onKeyDown === 'function') {
                return (component.ref as any).onKeyDown(props)
              }
              return false
            },

            onExit() {
              popup[0].destroy()
              component.destroy()
            },
          }
        },
      }),
    ]
  },
})

export const getSuggestionItems = ({ 
  query, 
  caseId: _caseId, 
  documentId,
  onInsertText,
  onSetRisks 
}: { 
  query: string
  caseId?: string
  documentId?: string
  onInsertText?: (text: string) => void
  onSetRisks?: (risks: RiskItem[]) => void
}) => {
  const items = [
    {
      title: 'Заголовок 1',
      description: 'Большой заголовок',
      icon: FileText,
      command: ({ editor, range }: any) => {
        editor
          .chain()
          .focus()
          .deleteRange(range)
          .setNode('heading', { level: 1 })
          .run()
      },
    },
    {
      title: 'Заголовок 2',
      description: 'Средний заголовок',
      icon: FileText,
      command: ({ editor, range }: any) => {
        editor
          .chain()
          .focus()
          .deleteRange(range)
          .setNode('heading', { level: 2 })
          .run()
      },
    },
    {
      title: 'Заголовок 3',
      description: 'Маленький заголовок',
      icon: FileText,
      command: ({ editor, range }: any) => {
        editor
          .chain()
          .focus()
          .deleteRange(range)
          .setNode('heading', { level: 3 })
          .run()
      },
    },
    {
      title: 'Маркированный список',
      description: 'Создать маркированный список',
      icon: List,
      command: ({ editor, range }: any) => {
        editor
          .chain()
          .focus()
          .deleteRange(range)
          .toggleBulletList()
          .run()
      },
    },
    {
      title: 'Нумерованный список',
      description: 'Создать нумерованный список',
      icon: List,
      command: ({ editor, range }: any) => {
        editor
          .chain()
          .focus()
          .deleteRange(range)
          .toggleOrderedList()
          .run()
      },
    },
    {
      title: 'Таблица',
      description: 'Вставить таблицу',
      icon: Table,
      command: ({ editor, range }: any) => {
        editor
          .chain()
          .focus()
          .deleteRange(range)
          .insertTable({ rows: 3, cols: 3, withHeaderRow: true })
          .run()
      },
    },
    {
      title: 'Цитата',
      description: 'Создать цитату',
      icon: Quote,
      command: ({ editor, range }: any) => {
        editor
          .chain()
          .focus()
          .deleteRange(range)
          .toggleBlockquote()
          .run()
      },
    },
    {
      title: 'Зачеркнуть',
      description: 'Применить зачеркивание',
      icon: Strikethrough,
      command: ({ editor, range }: any) => {
        toggleMarkOnWordAfterSlash(editor, range, (c) => c.toggleStrike())
      },
    },
    {
      title: 'Код',
      description: 'Применить форматирование кода',
      icon: Code,
      command: ({ editor, range }: any) => {
        toggleMarkOnWordAfterSlash(editor, range, (c) => c.toggleCode())
      },
    },
  ]

  // AI commands - only show if we have documentId (saved document)
  if (documentId) {
    items.push(
      {
        title: 'Создать договор',
        description: 'Создать договор с помощью AI',
        icon: Sparkles,
        command: async ({ editor, range }: any) => {
          editor.chain().focus().deleteRange(range).run()
          
          // Show loading toast
          const loadingToast = toast.loading('Создание договора…')
          
          try {
            const result = await aiAssist(documentId, 'create_contract', '', '')
            if (result.result && onInsertText) {
              onInsertText(result.result)
              toast.success('Договор создан', { id: loadingToast })
            } else {
              toast.error('Не удалось создать договор', { id: loadingToast })
            }
          } catch (error: any) {
            toast.error(error.message || 'Ошибка AI', { id: loadingToast })
          }
        },
      },
      {
        title: 'Проверить риски',
        description: 'Проверить текст на юридические риски',
        icon: AlertTriangle,
        command: async ({ editor, range }: any) => {
          // Get document content for risk checking
          const docContent = editor.getText()
          
          editor.chain().focus().deleteRange(range).run()
          
          const loadingToast = toast.loading('Проверка рисков…')
          
          try {
            const result = await aiAssist(documentId, 'check_risks', docContent, '')
            
            // Set risks in editor if any found
            if (result.risks && result.risks.length > 0 && onSetRisks) {
              onSetRisks(result.risks)
              toast.success(`Найдено ${result.risks.length} риск(ов). Риски подсвечены.`, { id: loadingToast })
            } else {
              toast.success('Рисков не обнаружено', { id: loadingToast })
            }
          } catch (error: any) {
            toast.error(error.message || 'Ошибка AI', { id: loadingToast })
          }
        },
      },
      {
        title: 'Улучшить текст',
        description: 'Улучшить выделенный текст с помощью AI',
        icon: Wand2,
        command: async ({ editor, range }: any) => {
          // Get selected text or document content
          const { from, to } = editor.state.selection
          const selectedText = from !== to 
            ? editor.state.doc.textBetween(from, to)
            : editor.getText()
          
          editor.chain().focus().deleteRange(range).run()
          
          if (!selectedText) {
            toast.error('Нет текста для улучшения')
            return
          }
          
          const loadingToast = toast.loading('Улучшение текста…')
          
          try {
            const result = await aiAssist(documentId, 'improve', selectedText, '')
            if (result.result && onInsertText) {
              onInsertText(result.result)
              toast.success('Текст улучшен', { id: loadingToast })
            } else {
              toast.error('Не удалось улучшить текст', { id: loadingToast })
            }
          } catch (error: any) {
            toast.error(error.message || 'Ошибка AI', { id: loadingToast })
          }
        },
      }
    )
  }

  return items.filter((item) => {
    if (typeof query === 'string' && query.length > 0) {
      const searchQuery = query.toLowerCase()
      return (
        item.title.toLowerCase().includes(searchQuery) ||
        item.description.toLowerCase().includes(searchQuery)
      )
    }
    return true
  })
}


const CommandList = ({ items, command }: any) => {
  const [selectedIndex, setSelectedIndex] = React.useState(0)

  const selectItem = (index: number) => {
    const item = items[index]
    if (item) {
      command(item)
    }
  }

  const upHandler = () => {
    setSelectedIndex((selectedIndex + items.length - 1) % items.length)
  }

  const downHandler = () => {
    setSelectedIndex((selectedIndex + 1) % items.length)
  }

  const enterHandler = () => {
    selectItem(selectedIndex)
  }

  React.useEffect(() => {
    setSelectedIndex(0)
  }, [items])

  const upHandlerRef = React.useRef(upHandler)
  const downHandlerRef = React.useRef(downHandler)
  const enterHandlerRef = React.useRef(enterHandler)
  
  // Update refs when handlers change
  React.useEffect(() => {
    upHandlerRef.current = upHandler
    downHandlerRef.current = downHandler
    enterHandlerRef.current = enterHandler
  })

  React.useEffect(() => {
    const navigationKeys = ['ArrowUp', 'ArrowDown', 'Enter']
    const onKeyDown = (e: KeyboardEvent) => {
      if (navigationKeys.includes(e.key)) {
        e.preventDefault()
        if (e.key === 'ArrowUp') {
          upHandlerRef.current()
          return true
        }
        if (e.key === 'ArrowDown') {
          downHandlerRef.current()
          return true
        }
        if (e.key === 'Enter') {
          enterHandlerRef.current()
          return true
        }
        return false
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [])

  return (
    <div 
      className="bg-white border rounded-lg shadow-lg p-1 min-w-[280px] max-h-[300px] overflow-y-auto"
      role="listbox"
      aria-label="Команды редактора"
    >
      {items.length ? (
        items.map((item: any, index: number) => (
          <button
            className={`flex items-center gap-2 w-full px-3 py-2 rounded text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
              index === selectedIndex ? 'bg-muted text-foreground' : 'hover:bg-gray-100'
            }`}
            key={index}
            onClick={() => selectItem(index)}
            aria-label={`${item.title}: ${item.description}`}
            aria-selected={index === selectedIndex}
            role="option"
          >
            <item.icon className="w-4 h-4 flex-shrink-0" aria-hidden="true" />
            <div className="flex-1 min-w-0">
              <div className="font-medium">{item.title}</div>
              <div className="text-xs text-gray-500">{item.description}</div>
            </div>
          </button>
        ))
      ) : (
        <div className="px-3 py-2 text-sm text-gray-500">Нет результатов</div>
      )}
    </div>
  )
}

// Export configured extension
export { SlashCommands }

