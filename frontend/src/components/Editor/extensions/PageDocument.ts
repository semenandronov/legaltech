import { Node } from '@tiptap/core'

/**
 * Document schema for true page-based editing.
 * Top-level contains one or more `page` nodes.
 */
export const PageDocument = Node.create({
  name: 'doc',
  topNode: true,
  content: 'page+',
})

