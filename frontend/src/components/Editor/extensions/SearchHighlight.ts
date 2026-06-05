import { Extension } from '@tiptap/core'
import { Plugin, PluginKey, Transaction } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

export interface SearchHighlightResult {
  from: number
  to: number
}

export interface SearchHighlightState {
  results: SearchHighlightResult[]
  currentIndex: number
}

export const searchHighlightPluginKey = new PluginKey<SearchHighlightState>('searchHighlight')

function buildDecorationSet(
  doc: Transaction['doc'],
  results: SearchHighlightResult[],
  currentIndex: number,
): DecorationSet {
  if (!results.length) return DecorationSet.empty

  const docSize = doc.content.size
  const decorations: Decoration[] = []

  for (let i = 0; i < results.length; i++) {
    const r = results[i]
    const from = Math.max(0, Math.min(r.from, docSize))
    const to = Math.max(from, Math.min(r.to, docSize))
    if (from >= to) continue

    decorations.push(
      Decoration.inline(from, to, {
        class: i === currentIndex ? 'search-highlight-current' : 'search-highlight',
      }),
    )
  }

  return decorations.length ? DecorationSet.create(doc, decorations) : DecorationSet.empty
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    searchHighlight: {
      setSearchHighlights: (results: SearchHighlightResult[], currentIndex: number) => ReturnType
      clearSearchHighlights: () => ReturnType
    }
  }
}

export const SearchHighlight = Extension.create({
  name: 'searchHighlight',

  addProseMirrorPlugins() {
    return [
      new Plugin<SearchHighlightState>({
        key: searchHighlightPluginKey,
        state: {
          init: () => ({ results: [], currentIndex: -1 }),
          apply(tr, prev) {
            const meta = tr.getMeta(searchHighlightPluginKey) as
              | { results: SearchHighlightResult[]; currentIndex: number }
              | { clear: true }
              | undefined

            if (meta && 'clear' in meta) {
              return { results: [], currentIndex: -1 }
            }
            if (meta) {
              return {
                results: meta.results,
                currentIndex: meta.currentIndex,
              }
            }
            if (tr.docChanged) {
              return { results: [], currentIndex: -1 }
            }
            return prev
          },
        },
        props: {
          decorations(state) {
            const pluginState = searchHighlightPluginKey.getState(state)
            if (!pluginState?.results.length) return DecorationSet.empty
            return buildDecorationSet(
              state.doc,
              pluginState.results,
              pluginState.currentIndex,
            )
          },
        },
      }),
    ]
  },

  addCommands() {
    return {
      setSearchHighlights:
        (results: SearchHighlightResult[], currentIndex: number) =>
        ({ tr, dispatch }) => {
          if (dispatch) {
            tr.setMeta(searchHighlightPluginKey, { results, currentIndex })
            dispatch(tr)
          }
          return true
        },
      clearSearchHighlights:
        () =>
        ({ tr, dispatch }) => {
          if (dispatch) {
            tr.setMeta(searchHighlightPluginKey, { clear: true })
            dispatch(tr)
          }
          return true
        },
    }
  },
})
