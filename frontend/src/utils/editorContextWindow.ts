/**
 * Context for document-editor chat:
 * - no selection → full document up to EDITOR_CONTEXT_MAX_CHARS
 * - user selected text → only that fragment (not the whole document)
 */

export const EDITOR_CONTEXT_MAX_CHARS = 80_000

export interface HtmlBlock {
  tag: string
  nodeId: string
  innerHtml: string
  text: string
}

const BLOCK_OPEN_RE =
  /<(p|h[1-6]|li|td|th)([^>]*\sid=["']([^"']+)["'][^>]*)>([\s\S]*?)<\/\1>/gi

function stripTags(html: string): string {
  if (typeof document !== 'undefined') {
    const div = document.createElement('div')
    div.innerHTML = html
    return (div.textContent || '').replace(/\s+/g, ' ').trim()
  }
  return html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
}

/** Parse HTML into blocks that carry TipTap UniqueID (attribute id). */
export function parseHtmlBlocks(html: string): HtmlBlock[] {
  const blocks: HtmlBlock[] = []
  if (!html?.trim()) return blocks

  let match: RegExpExecArray | null
  const re = new RegExp(BLOCK_OPEN_RE.source, BLOCK_OPEN_RE.flags)
  while ((match = re.exec(html)) !== null) {
    const tag = match[1].toLowerCase()
    const nodeId = match[3]
    const innerHtml = match[4] || ''
    blocks.push({
      tag,
      nodeId,
      innerHtml,
      text: stripTags(innerHtml),
    })
  }
  return blocks
}

export interface EditorContextWindowResult {
  html: string
  windowed: boolean
  selectionOnly: boolean
  totalBlocks: number
  fromBlock: number
  toBlock: number
}

/** Only the user selection (plain text), for focused edit/ask on a fragment. */
export function buildSelectionOnlyContext(
  selectedText: string,
  maxChars: number = EDITOR_CONTEXT_MAX_CHARS,
): EditorContextWindowResult {
  const text = (selectedText || '').trim()
  if (!text) {
    return {
      html: '',
      windowed: false,
      selectionOnly: true,
      totalBlocks: 0,
      fromBlock: 0,
      toBlock: 0,
    }
  }
  const clipped = text.length > maxChars ? text.slice(0, maxChars) : text
  const note =
    text.length > maxChars
      ? '<!-- selection truncated to max chars -->\n'
      : '<!-- editor-selection-only -->\n'
  return {
    html: `${note}<p>${escapeHtmlForParagraph(clipped)}</p>`,
    windowed: true,
    selectionOnly: true,
    totalBlocks: 1,
    fromBlock: 0,
    toBlock: 0,
  }
}

function escapeHtmlForParagraph(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

/**
 * Full document for chat (no active selection).
 * Up to maxChars as-is; longer documents are head-truncated (not slice-around-selection).
 */
export function buildEditorContextWindow(
  fullHtml: string,
  options?: {
    maxChars?: number
  },
): EditorContextWindowResult {
  const maxChars = options?.maxChars ?? EDITOR_CONTEXT_MAX_CHARS

  if (!fullHtml?.trim()) {
    return {
      html: '',
      windowed: false,
      selectionOnly: false,
      totalBlocks: 0,
      fromBlock: 0,
      toBlock: 0,
    }
  }

  const blocks = parseHtmlBlocks(fullHtml)

  if (fullHtml.length <= maxChars) {
    return {
      html: fullHtml,
      windowed: false,
      selectionOnly: false,
      totalBlocks: blocks.length,
      fromBlock: 0,
      toBlock: Math.max(0, blocks.length - 1),
    }
  }

  const comment = `<!-- document truncated: first ${maxChars} chars of ${fullHtml.length} -->\n`
  return {
    html: comment + fullHtml.slice(0, maxChars),
    windowed: true,
    selectionOnly: false,
    totalBlocks: blocks.length,
    fromBlock: 0,
    toBlock: Math.max(0, blocks.length - 1),
  }
}

/**
 * Entry point for editor chat requests.
 */
export function buildEditorContextForChat(
  fullHtml: string,
  options?: {
    selectedText?: string
    maxChars?: number
  },
): EditorContextWindowResult {
  const selected = (options?.selectedText || '').trim()
  if (selected) {
    return buildSelectionOnlyContext(selected, options?.maxChars)
  }
  return buildEditorContextWindow(fullHtml, { maxChars: options?.maxChars })
}
