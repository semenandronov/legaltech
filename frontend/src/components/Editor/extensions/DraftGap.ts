import { Mark, mergeAttributes, getMarkRange } from '@tiptap/core'
import { Plugin, PluginKey, TextSelection } from '@tiptap/pm/state'
import type { EditorView } from '@tiptap/pm/view'
import {
  findStaleDraftGapMarks,
  findUnmarkedDraftGaps,
} from './draftGapUtils'

export const draftGapPluginKey = new PluginKey('draftGapSync')

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    draftGap: {
      syncDraftGapMarks: () => ReturnType
    }
  }
}

function syncMarksInTransaction(view: EditorView): boolean {
  const markType = view.state.schema.marks.draftGap
  if (!markType) return false

  const { doc } = view.state
  const toAdd = findUnmarkedDraftGaps(doc, markType)
  const toRemove = findStaleDraftGapMarks(doc, markType)
  if (!toAdd.length && !toRemove.length) return false

  let tr = view.state.tr
  tr.setMeta(draftGapPluginKey, true)

  for (const { from, to } of toRemove) {
    tr = tr.removeMark(from, to, markType)
  }
  for (const { from, to, label } of toAdd) {
    tr = tr.addMark(from, to, markType.create({ label }))
  }

  view.dispatch(tr)
  return true
}

export const DraftGap = Mark.create({
  name: 'draftGap',

  inclusive: false,
  excludes: '',

  addAttributes() {
    return {
      label: {
        default: '',
        parseHTML: (element) => element.getAttribute('data-draft-gap') || '',
        renderHTML: (attributes) => {
          if (!attributes.label) return {}
          return { 'data-draft-gap': attributes.label }
        },
      },
    }
  },

  parseHTML() {
    return [
      {
        tag: 'span[data-draft-gap]',
      },
    ]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'span',
      mergeAttributes(HTMLAttributes, {
        class: 'draft-gap-bubble',
        title: 'Нажмите, чтобы заполнить поле',
      }),
      0,
    ]
  },

  addCommands() {
    return {
      syncDraftGapMarks:
        () =>
        ({ editor }) => {
          syncMarksInTransaction(editor.view)
          return true
        },
    }
  },

  addProseMirrorPlugins() {
    const markType = this.type

    return [
      new Plugin({
        key: draftGapPluginKey,
        appendTransaction(transactions, _oldState, newState) {
          if (transactions.some((tr) => tr.getMeta(draftGapPluginKey))) {
            return null
          }
          if (!transactions.some((tr) => tr.docChanged)) {
            return null
          }

          const type = newState.schema.marks.draftGap
          if (!type) return null

          const toAdd = findUnmarkedDraftGaps(newState.doc, type)
          const toRemove = findStaleDraftGapMarks(newState.doc, type)
          if (!toAdd.length && !toRemove.length) return null

          let tr = newState.tr
          tr.setMeta(draftGapPluginKey, true)

          for (const { from, to } of toRemove) {
            tr = tr.removeMark(from, to, type)
          }
          for (const { from, to, label } of toAdd) {
            tr = tr.addMark(from, to, type.create({ label }))
          }

          return tr
        },
        props: {
          handleClick(view, _pos, event) {
            const target = event.target
            if (!(target instanceof HTMLElement)) return false
            const bubble = target.closest('.draft-gap-bubble')
            if (!bubble || !view.editable) return false

            const clickPos = view.posAtDOM(bubble, 0)
            const $pos = view.state.doc.resolve(clickPos)
            const range = getMarkRange($pos, markType)
            if (!range) return false

            event.preventDefault()
            const tr = view.state.tr.setSelection(
              TextSelection.create(view.state.doc, range.from, range.to),
            )
            view.dispatch(tr)
            view.focus()
            return true
          },
        },
      }),
    ]
  },
})
