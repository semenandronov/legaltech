import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { Transaction } from '@tiptap/pm/state'

export interface TrackChangesOptions {
  enabled: boolean
  pendingChanges?: Array<{
    id: string
    from: number
    to: number
    type: 'insertion' | 'deletion'
    content?: string
  }>
}

export const TrackChanges = Extension.create<TrackChangesOptions>({
  name: 'trackChanges',

  addOptions() {
    return {
      enabled: false,
      pendingChanges: [],
    }
  },

  addProseMirrorPlugins() {
    const extension = this

    return [
      new Plugin({
        key: new PluginKey('trackChanges'),
        state: {
          init() {
            return DecorationSet.empty
          },
          apply(tr: Transaction, _set: DecorationSet) {
            if (!extension.options.enabled) {
              return DecorationSet.empty
            }

            const decorations: Decoration[] = []
            const pendingChanges = extension.options.pendingChanges || []

            pendingChanges.forEach((change) => {
              if (change.type === 'insertion' && change.content) {
                // Highlight inserted text in green
                const decoration = Decoration.inline(
                  change.from,
                  change.to,
                  {
                    class: 'track-change-insertion',
                    style: 'background-color: rgba(34, 197, 94, 0.2); border-bottom: 2px solid rgba(34, 197, 94, 0.5);',
                  }
                )
                decorations.push(decoration)
              } else if (change.type === 'deletion') {
                // Highlight deleted text in red (strikethrough)
                const decoration = Decoration.inline(
                  change.from,
                  change.to,
                  {
                    class: 'track-change-deletion',
                    style: 'background-color: rgba(239, 68, 68, 0.2); text-decoration: line-through;',
                  }
                )
                decorations.push(decoration)
              }
            })

            return DecorationSet.create(tr.doc, decorations)
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
      setTrackChangesEnabled: (enabled: boolean) => ({ tr, dispatch }: { tr: Transaction; dispatch?: (tr: Transaction) => void }) => {
        if (dispatch) {
          this.options.enabled = enabled
          dispatch(tr)
        }
        return true
      },
      addPendingChange: (change: NonNullable<TrackChangesOptions['pendingChanges']>[0]) => ({ tr, dispatch }: { tr: Transaction; dispatch?: (tr: Transaction) => void }) => {
        if (dispatch) {
          if (!this.options.pendingChanges) {
            this.options.pendingChanges = []
          }
          this.options.pendingChanges.push(change)
          dispatch(tr)
        }
        return true
      },
      clearPendingChanges: () => ({ tr, dispatch }: { tr: Transaction; dispatch?: (tr: Transaction) => void }) => {
        if (dispatch) {
          this.options.pendingChanges = []
          dispatch(tr)
        }
        return true
      },
    } as any
  },
})

