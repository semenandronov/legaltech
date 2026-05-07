import { Extension } from '@tiptap/core'
import { Plugin, PluginKey, Transaction } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

export interface SearchHighlightResult {
  from: number
  to: number
}

export interface SearchHighlightOptions {
  results: SearchHighlightResult[]
  currentIndex: number
  active: boolean
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    searchHighlight: {
      setSearchHighlights: (results: SearchHighlightResult[], currentIndex: number) => ReturnType
      clearSearchHighlights: () => ReturnType
    }
  }
}

export const SearchHighlight = Extension.create<SearchHighlightOptions>({
  name: 'searchHighlight',

  addOptions() {
    return {
      results: [],
      currentIndex: -1,
      active: false,
    }
  },

  addProseMirrorPlugins() {
    const extension = this

    return [
      new Plugin({
        key: new PluginKey('searchHighlight'),
        state: {
          init() {
            return DecorationSet.empty
          },
          apply(tr: Transaction) {
            if (!extension.options.active || !extension.options.results?.length) {
              return DecorationSet.empty
            }

            const docSize = tr.doc.content.size
            const current = extension.options.currentIndex

            const decorations: Decoration[] = []
            for (let i = 0; i < extension.options.results.length; i++) {
              const r = extension.options.results[i]
              const from = Math.max(0, Math.min(r.from, docSize))
              const to = Math.max(from, Math.min(r.to, docSize))
              if (from >= to) continue

              decorations.push(
                Decoration.inline(from, to, {
                  class: i === current ? 'search-highlight-current' : 'search-highlight',
                })
              )
            }

            return decorations.length ? DecorationSet.create(tr.doc, decorations) : DecorationSet.empty
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
      setSearchHighlights:
        (results: SearchHighlightResult[], currentIndex: number) =>
        ({ tr, dispatch }: { tr: Transaction; dispatch?: (tr: Transaction) => void }) => {
          if (dispatch) {
            this.options.results = results
            this.options.currentIndex = currentIndex
            this.options.active = true
            dispatch(tr)
          }
          return true
        },
      clearSearchHighlights:
        () =>
        ({ tr, dispatch }: { tr: Transaction; dispatch?: (tr: Transaction) => void }) => {
          if (dispatch) {
            this.options.active = false
            this.options.results = []
            this.options.currentIndex = -1
            dispatch(tr)
          }
          return true
        },
    }
  },
})

