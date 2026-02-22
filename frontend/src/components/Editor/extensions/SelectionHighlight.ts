import { Extension } from '@tiptap/core'
import { Plugin, PluginKey, Transaction } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

export interface SelectionHighlightOptions {
  from: number
  to: number
  active: boolean
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    selectionHighlight: {
      setSelectionHighlight: (from: number, to: number) => ReturnType
      clearSelectionHighlight: () => ReturnType
    }
  }
}

export const SelectionHighlight = Extension.create<SelectionHighlightOptions>({
  name: 'selectionHighlight',

  addOptions() {
    return {
      from: 0,
      to: 0,
      active: false,
    }
  },

  addProseMirrorPlugins() {
    const extension = this

    return [
      new Plugin({
        key: new PluginKey('selectionHighlight'),
        state: {
          init() {
            return DecorationSet.empty
          },
          apply(tr: Transaction) {
            if (!extension.options.active || extension.options.from >= extension.options.to) {
              return DecorationSet.empty
            }
            try {
              const docSize = tr.doc.content.size
              const from = Math.max(0, Math.min(extension.options.from, docSize))
              const to = Math.max(from, Math.min(extension.options.to, docSize))
              if (from >= to) return DecorationSet.empty

              const decoration = Decoration.inline(from, to, {
                class: 'ai-selection-highlight',
                style:
                  'background-color: rgba(59, 130, 246, 0.2); border-bottom: 2px solid rgba(59, 130, 246, 0.5); border-radius: 2px;',
              })
              return DecorationSet.create(tr.doc, [decoration])
            } catch {
              return DecorationSet.empty
            }
          },
        },
        props: {
          decorations(state) {
            return this.getState(state)
          },
        },
      }),
    ]
  },

  addCommands() {
    return {
      setSelectionHighlight:
        (from: number, to: number) =>
        ({ tr, dispatch }: { tr: Transaction; dispatch?: (tr: Transaction) => void }) => {
          if (dispatch) {
            this.options.from = from
            this.options.to = to
            this.options.active = true
            dispatch(tr)
          }
          return true
        },
      clearSelectionHighlight:
        () =>
        ({ tr, dispatch }: { tr: Transaction; dispatch?: (tr: Transaction) => void }) => {
          if (dispatch) {
            this.options.active = false
            this.options.from = 0
            this.options.to = 0
            dispatch(tr)
          }
          return true
        },
    }
  },
})
