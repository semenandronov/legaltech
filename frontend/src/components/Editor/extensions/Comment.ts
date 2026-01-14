import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { Transaction } from '@tiptap/pm/state'

export interface CommentOptions {
  comments: Array<{
    id: string
    from: number
    to: number
    text: string
    author?: string
    createdAt?: string
  }>
}

export const Comment = Extension.create<CommentOptions>({
  name: 'comment',

  addOptions() {
    return {
      comments: [],
    }
  },

  addProseMirrorPlugins() {
    const extension = this

    return [
      new Plugin({
        key: new PluginKey('comment'),
        state: {
          init() {
            return DecorationSet.empty
          },
          apply(tr: Transaction, _set: DecorationSet) {
            const decorations: Decoration[] = []
            const comments = extension.options.comments || []

            comments.forEach((comment) => {
              const decoration = Decoration.inline(
                comment.from,
                comment.to,
                {
                  class: 'document-comment',
                  style: 'background-color: rgba(251, 191, 36, 0.2); border-bottom: 2px dotted rgba(251, 191, 36, 0.6); cursor: help;',
                  'data-comment-id': comment.id,
                  'data-comment-text': comment.text,
                  title: `Комментарий: ${comment.text}`,
                }
              )
              decorations.push(decoration)
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
      addComment: (from: number, to: number, text: string, id?: string) => ({ tr, dispatch }: { tr: Transaction; dispatch?: (tr: Transaction) => void }) => {
        if (dispatch) {
          if (!this.options.comments) {
            this.options.comments = []
          }
          const commentId = id || `comment-${Date.now()}`
          this.options.comments.push({
            id: commentId,
            from,
            to,
            text,
            createdAt: new Date().toISOString(),
          })
          dispatch(tr)
        }
        return true
      },
      removeComment: (id: string) => ({ tr, dispatch }: { tr: Transaction; dispatch?: (tr: Transaction) => void }) => {
        if (dispatch) {
          if (this.options.comments) {
            this.options.comments = this.options.comments.filter((c) => c.id !== id)
            dispatch(tr)
          }
        }
        return true
      },
      setComments: (comments: CommentOptions['comments']) => ({ tr, dispatch }: { tr: Transaction; dispatch?: (tr: Transaction) => void }) => {
        if (dispatch) {
          this.options.comments = comments
          dispatch(tr)
        }
        return true
      },
    } as any
  },
})

