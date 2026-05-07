import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'

/**
 * Pagination plugin:
 * - Ensures content is distributed across `page` nodes by measuring DOM.
 * - MVP: moves whole block nodes between pages (doesn't split paragraphs).
 */
export const Pagination = Extension.create({
  name: 'pagination',

  addOptions() {
    return {
      pageHeightPx: 1056,
      // Padding is controlled by CSS (.pm-page__content). Keep pagination math padding-free
      // to avoid double-accounting top/bottom margins.
      pagePaddingPx: 0,
      pageGapPx: 32,
      maxOpsPerUpdate: 50,
    }
  },

  addProseMirrorPlugins() {
    const key = new PluginKey('pagination')
    const extension = this

    return [
      new Plugin({
        key,
        view(view) {
          let scheduled = false
          let running = false

          const schedule = () => {
            if (scheduled) return
            scheduled = true
            requestAnimationFrame(() => {
              scheduled = false
              if (running) return
              running = true
              try {
                paginate(view)
              } finally {
                running = false
              }
            })
          }

          const paginate = (v: any) => {
            const { state } = v
            const pageType = state.schema.nodes.page
            if (!pageType) return

            const pageHeight = extension.options.pageHeightPx
            const padding = extension.options.pagePaddingPx
            const maxHeight = Math.max(50, pageHeight - padding * 2)
            const maxOps = extension.options.maxOpsPerUpdate

            const getPages = () => {
              const pages: Array<{ node: any; pos: number }> = []
              state.doc.forEach((child: any, offset: number) => {
                if (child.type === pageType) pages.push({ node: child, pos: offset })
              })
              return pages
            }

            const isEffectivelyEmptyPage = (pageNode: any): boolean => {
              // ProseMirror pages often keep a single empty paragraph, so childCount>0
              // even when the page is visually empty.
              const text = String(pageNode?.textContent || '').replace(/\s+/g, ' ').trim()
              if (text) return false
              // If there are non-text blocks (tables, images, etc.) consider page non-empty.
              let hasNonTrivial = false
              pageNode.descendants((node: any) => {
                if (hasNonTrivial) return false
                if (node.isText) return true
                // Empty paragraph/heading nodes are fine; other leaf/atom nodes count as content.
                const name = node.type?.name
                if (node.isAtom || node.isLeaf) {
                  hasNonTrivial = true
                  return false
                }
                if (name && name !== 'paragraph' && name !== 'heading' && name !== 'text') {
                  // Keep conservative: anything besides basic blocks makes it non-empty.
                  hasNonTrivial = true
                  return false
                }
                return true
              })
              return !hasNonTrivial
            }

            const measureOverflow = (pagePos: number) => {
              const dom = v.nodeDOM(pagePos) as HTMLElement | null
              if (!dom) return { overflow: false, free: 0 }
              const contentEl = dom.querySelector('.pm-page__content') as HTMLElement | null
              if (!contentEl) return { overflow: false, free: 0 }
              const contentHeight = contentEl.scrollHeight
              const free = maxHeight - contentHeight
              return { overflow: contentHeight > maxHeight + 1, free }
            }

            const moveLastBlockToNextPage = (page: { node: any; pos: number }, nextPage: { node: any; pos: number } | null) => {
              const pageNode = page.node
              if (pageNode.childCount === 0) return false

              const idx = pageNode.childCount - 1
              const moved = pageNode.child(idx)

              // Compute moved node range inside page
              let childPos = page.pos + 1
              for (let i = 0; i < idx; i++) {
                childPos += pageNode.child(i).nodeSize
              }
              const from = childPos
              const to = from + moved.nodeSize

              let tr = state.tr.deleteRange(from, to)

              if (nextPage) {
                const insertPos = nextPage.pos + 1
                tr = tr.insert(insertPos, moved)
              } else {
                const newPage = pageType.create(null, moved)
                const insertAfter = page.pos + pageNode.nodeSize
                tr = tr.insert(insertAfter, newPage)
              }

              v.dispatch(tr)
              return true
            }

            const moveFirstBlockFromNextToCurrent = (page: { node: any; pos: number }, nextPage: { node: any; pos: number }) => {
              const nextNode = nextPage.node
              if (nextNode.childCount === 0) return false
              const moved = nextNode.child(0)

              // Range of first child in next page
              const from = nextPage.pos + 1
              const to = from + moved.nodeSize

              // Insert at end of current page content
              const insertPos = page.pos + 1 + page.node.content.size

              const tr = state.tr
                .deleteRange(from, to)
                .insert(insertPos, moved)

              v.dispatch(tr)
              return true
            }

            // Pass 1: push overflow forward
            for (let ops = 0; ops < maxOps; ops++) {
              const pages = getPages()
              let changed = false

              for (let i = 0; i < pages.length; i++) {
                const p = pages[i]
                const { overflow } = measureOverflow(p.pos)
                if (!overflow) continue

                const next = pages[i + 1] || null
                if (moveLastBlockToNextPage(p, next)) {
                  changed = true
                  break
                }
              }

              if (!changed) break
              return // will re-run on next raf after dispatch
            }

            // Pass 2: pull content back if there is free space
            for (let ops = 0; ops < maxOps; ops++) {
              const pages = getPages()
              let changed = false

              for (let i = 0; i < pages.length - 1; i++) {
                const p = pages[i]
                const next = pages[i + 1]
                const m = measureOverflow(p.pos)
                if (m.free <= 24) continue

                // Try pull 1st block from next page if it fits
                const before = measureOverflow(p.pos).free
                if (!moveFirstBlockFromNextToCurrent(p, next)) continue
                const after = measureOverflow(p.pos).free
                // If we made it worse (shouldn't happen), it'll be corrected in push pass
                if (after < before) {
                  changed = true
                  break
                }
                changed = true
                break
              }

              if (!changed) break
              return
            }

            // Cleanup: remove empty trailing pages (keep at least 1)
            const pages = getPages()
            for (let i = pages.length - 1; i >= 1; i--) {
              const p = pages[i]
              if (!isEffectivelyEmptyPage(p.node)) break
              const tr = state.tr.delete(p.pos, p.pos + p.node.nodeSize)
              v.dispatch(tr)
              return
            }
          }

          return {
            update(_view, prevState) {
              if (prevState.doc !== view.state.doc) {
                schedule()
              }
            },
            destroy() {
              scheduled = false
            },
          }
        },
      }),
    ]
  },
})

