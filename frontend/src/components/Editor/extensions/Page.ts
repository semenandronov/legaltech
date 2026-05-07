import { Node, mergeAttributes } from '@tiptap/core'

export const Page = Node.create({
  name: 'page',
  group: 'block',
  content: 'block+',
  defining: true,
  isolating: true,

  parseHTML() {
    return [{ tag: 'div[data-type="page"]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return ['div', mergeAttributes(HTMLAttributes, { 'data-type': 'page' }), 0]
  },

  addNodeView() {
    return ({ HTMLAttributes }) => {
      const dom = document.createElement('div')
      dom.className = 'pm-page'
      dom.setAttribute('data-type', 'page')
      Object.entries(HTMLAttributes || {}).forEach(([k, v]) => {
        if (v == null) return
        dom.setAttribute(k, String(v))
      })

      const content = document.createElement('div')
      content.className = 'pm-page__content'
      dom.appendChild(content)

      return { dom, contentDOM: content }
    }
  },
})

