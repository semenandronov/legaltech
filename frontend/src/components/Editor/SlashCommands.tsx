import React from 'react'
import { Extension } from '@tiptap/core'
import { ReactRenderer } from '@tiptap/react'
import Suggestion from '@tiptap/suggestion'
import tippy, { Instance as TippyInstance } from 'tippy.js'
import { FileText, List, Table, Sparkles, AlertTriangle, Wand2 } from 'lucide-react'

interface SlashCommandsOptions {
  caseId?: string
  onInsertText?: (text: string) => void
}

const SlashCommands = Extension.create<SlashCommandsOptions>({
  name: 'slashCommands',

  addOptions() {
    return {
      ...this.parent?.(),
      caseId: undefined,
      onInsertText: undefined,
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
            onInsertText: options.onInsertText,
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
                onInsertText: options.onInsertText,
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
                onInsertText: options.onInsertText,
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

              return component.ref?.onKeyDown?.(props) ?? false
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

export const getSuggestionItems = ({ query, caseId, onInsertText }: { query: string; caseId?: string; onInsertText?: (text: string) => void }) => {
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
  ]

  // AI commands
  if (caseId) {
    items.push(
      {
        title: 'Создать договор',
        description: 'Создать договор с помощью AI',
        icon: Sparkles,
        command: async ({ editor, range }: any) => {
          editor.chain().focus().deleteRange(range).run()
          // This will trigger AI sidebar action
          if (onInsertText) {
            onInsertText('Создание договора...')
          }
        },
      },
      {
        title: 'Проверить риски',
        description: 'Проверить текст на юридические риски',
        icon: AlertTriangle,
        command: async ({ editor, range }: any) => {
          editor.chain().focus().deleteRange(range).run()
          if (onInsertText) {
            onInsertText('Проверка рисков...')
          }
        },
      },
      {
        title: 'Улучшить текст',
        description: 'Улучшить текст с помощью AI',
        icon: Wand2,
        command: async ({ editor, range }: any) => {
          editor.chain().focus().deleteRange(range).run()
          if (onInsertText) {
            onInsertText('Улучшение текста...')
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

  React.useEffect(() => {
    const navigationKeys = ['ArrowUp', 'ArrowDown', 'Enter']
    const onKeyDown = (e: KeyboardEvent) => {
      if (navigationKeys.includes(e.key)) {
        e.preventDefault()
        if (e.key === 'ArrowUp') {
          upHandler()
          return true
        }
        if (e.key === 'ArrowDown') {
          downHandler()
          return true
        }
        if (e.key === 'Enter') {
          enterHandler()
          return true
        }
        return false
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [items, selectedIndex])

  return (
    <div className="bg-white border rounded-lg shadow-lg p-1 min-w-[280px] max-h-[300px] overflow-y-auto">
      {items.length ? (
        items.map((item: any, index: number) => (
          <button
            className={`flex items-center gap-2 w-full px-3 py-2 rounded text-left transition-colors ${
              index === selectedIndex ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-100'
            }`}
            key={index}
            onClick={() => selectItem(index)}
          >
            <item.icon className="w-4 h-4 flex-shrink-0" />
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

