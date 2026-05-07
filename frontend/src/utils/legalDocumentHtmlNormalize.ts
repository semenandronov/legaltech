/**
 * Нормализация выравнивания юридического документа для TipTap:
 * шапка справа, название по центру, основная часть слева, подпись/футер справа.
 * Логика синхронизирована с backend _enforce_legal_text_alignment (chat_graph.py).
 */

function setTextAlignOnOpenTag(htmlTag: string, align: string): string {
  const styleRe = /style=(["'])(.*?)\1/i
  if (styleRe.test(htmlTag)) {
    return htmlTag.replace(styleRe, (_, quote: string, style: string) => {
      let s = style.replace(/text-align\s*:\s*[^;]+;?/gi, '').replace(/;\s*;/g, ';').trim()
      s = s.replace(/^;|;$/g, '').trim()
      const next = s ? `${s}; text-align: ${align};` : `text-align: ${align};`
      return `style=${quote}${next}${quote}`
    })
  }
  if (htmlTag.endsWith('>')) {
    return htmlTag.slice(0, -1) + ` style="text-align: ${align};">`
  }
  return htmlTag
}

interface ParsedBlock {
  start: number
  end: number
  tag: string
  openTag: string
  inner: string
  plain: string
}

export function normalizeLegalDocumentHtml(html: string): string {
  if (!html?.trim()) return html

  let result = html.trim()
  result = result.replace(/^```(?:html)?\s*/i, '').replace(/\s*```$/i, '')

  const blockRe = /<(h[1-3]|p|div)([^>]*)>([\s\S]*?)<\/\1>/gi
  const blocks: ParsedBlock[] = []
  let m: RegExpExecArray | null
  blockRe.lastIndex = 0
  while ((m = blockRe.exec(result)) !== null) {
    const tag = (m[1] || '').toLowerCase()
    const full = m[0]
    const openEnd = full.indexOf('>')
    const openTag = openEnd >= 0 ? full.slice(0, openEnd + 1) : `<${tag}>`
    const inner = m[3] || ''
    let plain = inner.replace(/<[^>]+>/g, ' ')
    plain = plain.replace(/\s+/g, ' ').trim()
    blocks.push({
      start: m.index,
      end: m.index + full.length,
      tag,
      openTag,
      inner,
      plain,
    })
  }

  if (blocks.length === 0) return result

  const titleMarkers = [
    'исковое заявление',
    'апелляционная жалоба',
    'кассационная жалоба',
    'претензия',
    'ходатайство',
    'заявление',
    'договор',
    'соглашение',
  ]

  let titleIdx = -1
  for (let i = 0; i < blocks.length; i++) {
    const txt = blocks[i].plain.toLowerCase()
    if (!txt) continue
    const isHeading = blocks[i].tag.startsWith('h')
    const isMarker = titleMarkers.some((mk) => txt.includes(mk))
    const isUpperTitle = txt.length > 8 && txt === txt.toUpperCase()
    if (isHeading || isMarker || isUpperTitle) {
      titleIdx = i
      break
    }
  }

  if (titleIdx === -1) {
    for (let i = 0; i < blocks.length; i++) {
      if (blocks[i].plain) {
        titleIdx = i
        break
      }
    }
  }

  // If we still couldn't find any meaningful block (all plain text empty),
  // don't attempt to force alignment — just return the original HTML.
  if (titleIdx === -1) {
    return result
  }

  const signatureMarkers = [
    'подпись',
    'фио',
    'ф.и.о',
    'представитель',
    'м.п.',
    'мп',
    'дата',
    '____________',
    '________________',
    '/',
  ]

  const total = blocks.length
  let tailStart = -1
  for (let i = total - 1; i > titleIdx; i--) {
    const txt = blocks[i].plain.toLowerCase()
    if (signatureMarkers.some((mk) => txt.includes(mk))) {
      tailStart = i
      break
    }
  }
  if (tailStart === -1) {
    tailStart = Math.max(titleIdx + 1, total - 2)
  }

  function renderBlock(block: ParsedBlock, align: string): string {
    let tag = block.tag
    let openTag = block.openTag
    if (tag === 'div') {
      openTag = '<p>'
      tag = 'p'
    }
    const newOpen = setTextAlignOnOpenTag(openTag, align)
    return `${newOpen}${block.inner}</${tag}>`
  }

  const headerBlocks = blocks.slice(0, titleIdx)
  const titleBlock = blocks[titleIdx]
  const bodyBlocks = blocks.slice(titleIdx + 1, tailStart)
  const footerBlocks = blocks.slice(tailStart)

  const parts: string[] = []
  for (const b of headerBlocks) {
    if (b.plain) parts.push(renderBlock(b, 'right'))
  }
  parts.push(renderBlock(titleBlock, 'center'))
  for (const b of bodyBlocks) {
    if (b.plain) parts.push(renderBlock(b, 'left'))
  }
  for (const b of footerBlocks) {
    if (b.plain) parts.push(renderBlock(b, 'right'))
  }

  return parts.join('\n')
}
