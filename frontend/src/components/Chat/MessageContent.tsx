import React, { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { SourceInfo } from '../../services/api'
import { InlineCitationAdapter } from './InlineCitationAdapter'

interface MessageContentProps {
  content: string
  sources: SourceInfo[]
  onCitationClick?: (source: SourceInfo) => void
  isStreaming?: boolean
}

// Unique marker that won't appear in normal text or markdown
const CITE_PREFIX = '\u200B\u200BCITE_'
const CITE_SUFFIX = '_ENDCITE\u200B\u200B'
const CITE_REGEX = /\u200B\u200BCITE_(\d+)_ENDCITE\u200B\u200B/g

/**
 * Walk React children and replace citation markers with InlineCitationAdapter components.
 * Works recursively so citations inside <strong>, <em>, <li> etc. are handled.
 */
function injectCitations(
  children: React.ReactNode,
  sources: SourceInfo[],
  onCitationClick?: (source: SourceInfo) => void,
  keyPrefix = ''
): React.ReactNode {
  return React.Children.map(children, (child, childIdx) => {
    // String nodes: split by citation markers and inject components
    if (typeof child === 'string') {
      if (!CITE_REGEX.test(child)) return child
      CITE_REGEX.lastIndex = 0

      const parts: (string | React.ReactElement)[] = []
      let lastIdx = 0
      let match: RegExpExecArray | null

      while ((match = CITE_REGEX.exec(child)) !== null) {
        if (match.index > lastIdx) {
          parts.push(child.substring(lastIdx, match.index))
        }
        const citationIndex = parseInt(match[1], 10)
        parts.push(
          <InlineCitationAdapter
            key={`${keyPrefix}c-${childIdx}-${citationIndex}`}
            index={citationIndex}
            sources={sources}
            onClick={onCitationClick}
          />
        )
        lastIdx = match.index + match[0].length
      }
      if (lastIdx < child.length) {
        parts.push(child.substring(lastIdx))
      }
      return <>{parts}</>
    }

    // React elements: recurse into their children
    if (React.isValidElement(child) && child.props?.children != null) {
      return React.cloneElement(
        child,
        { ...child.props },
        injectCitations(child.props.children, sources, onCitationClick, `${keyPrefix}${childIdx}-`)
      )
    }

    return child
  })
}

/**
 * Build markdown component overrides that inject inline citations.
 * Every text-containing element processes its children for citation markers.
 */
function buildMarkdownComponents(
  sources: SourceInfo[],
  onCitationClick?: (source: SourceInfo) => void
): Components {
  // Wrapper: inject citations into children
  const w = (children: React.ReactNode) =>
    injectCitations(children, sources, onCitationClick)

  return {
    p: ({ children }) => (
      <p style={{ margin: '0 0 20px 0', lineHeight: 1.8, display: 'block', color: 'inherit' }}>
        {w(children)}
      </p>
    ),
    h1: ({ children }) => (
      <h1 style={{ fontSize: '28px', fontWeight: 700, color: 'inherit', margin: '40px 0 24px 0', display: 'block', lineHeight: 1.2, letterSpacing: '-0.02em', paddingTop: '8px' }}>
        {w(children)}
      </h1>
    ),
    h2: ({ children }) => (
      <h2 style={{ fontSize: '22px', fontWeight: 600, color: 'inherit', margin: '36px 0 20px 0', display: 'block', lineHeight: 1.3, letterSpacing: '-0.01em', paddingTop: '8px' }}>
        {w(children)}
      </h2>
    ),
    h3: ({ children }) => (
      <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'inherit', margin: '32px 0 16px 0', display: 'block', lineHeight: 1.4, paddingTop: '6px' }}>
        {w(children)}
      </h3>
    ),
    h4: ({ children }) => (
      <h4 style={{ fontSize: '16px', fontWeight: 600, color: 'inherit', margin: '28px 0 14px 0', display: 'block', lineHeight: 1.4, paddingTop: '4px' }}>
        {w(children)}
      </h4>
    ),
    ul: ({ children }) => (
      <ul style={{ margin: '20px 0', paddingLeft: '32px', display: 'block', lineHeight: 1.8, listStyleType: 'disc' }}>
        {children}
      </ul>
    ),
    ol: ({ children }) => (
      <ol style={{ margin: '20px 0', paddingLeft: '32px', display: 'block', lineHeight: 1.8, listStyleType: 'decimal' }}>
        {children}
      </ol>
    ),
    li: ({ children }) => (
      <li style={{ margin: '10px 0', display: 'list-item', lineHeight: 1.8, paddingLeft: '6px' }}>
        {w(children)}
      </li>
    ),
    code: ({ children, className }) => {
      const isInline = !className
      return isInline ? (
        <code style={{ backgroundColor: 'rgba(0, 0, 0, 0.08)', padding: '3px 6px', borderRadius: '4px', fontSize: '0.9em', fontFamily: "'Fira Code', 'Courier New', monospace", color: 'inherit', display: 'inline', fontWeight: 500 }}>
          {children}
        </code>
      ) : (
        <code style={{ backgroundColor: 'rgba(0, 0, 0, 0.06)', padding: '14px 16px', borderRadius: '8px', fontSize: '0.9em', fontFamily: "'Fira Code', 'Courier New', monospace", color: 'inherit', display: 'block', overflowX: 'auto', margin: '16px 0', lineHeight: 1.6 }}>
          {children}
        </code>
      )
    },
    pre: ({ children }) => (
      <pre style={{ backgroundColor: 'rgba(0, 0, 0, 0.04)', padding: '16px', borderRadius: '8px', fontSize: '0.9em', fontFamily: "'Fira Code', 'Courier New', monospace", overflowX: 'auto', margin: '16px 0', display: 'block', lineHeight: 1.6 }}>
        {children}
      </pre>
    ),
    strong: ({ children }) => (
      <strong style={{ fontWeight: 600, display: 'inline', color: 'inherit' }}>
        {w(children)}
      </strong>
    ),
    em: ({ children }) => (
      <em style={{ fontStyle: 'italic', display: 'inline', color: 'inherit' }}>
        {w(children)}
      </em>
    ),
    a: ({ children, href }) => (
      <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'underline', textDecorationColor: 'rgba(0, 0, 0, 0.3)', display: 'inline', textUnderlineOffset: '2px' }}>
        {children}
      </a>
    ),
    blockquote: ({ children }) => (
      <blockquote style={{ borderLeft: '4px solid rgba(0, 0, 0, 0.2)', paddingLeft: '24px', margin: '24px 0', color: 'inherit', fontStyle: 'normal', display: 'block', opacity: 0.85, paddingTop: '8px', paddingBottom: '8px', paddingRight: '16px', backgroundColor: 'rgba(0, 0, 0, 0.02)', borderRadius: '0 4px 4px 0' }}>
        {w(children)}
      </blockquote>
    ),
    table: ({ children }) => (
      <div style={{ margin: '24px 0', overflowX: 'auto', borderRadius: '8px', border: '1px solid rgba(0, 0, 0, 0.12)', display: 'block', boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', display: 'table', minWidth: '100%', backgroundColor: 'transparent' }}>
          {children}
        </table>
      </div>
    ),
    thead: ({ children }) => (
      <thead style={{ display: 'table-header-group', backgroundColor: 'rgba(0, 0, 0, 0.04)' }}>
        {children}
      </thead>
    ),
    tbody: ({ children }) => (
      <tbody style={{ display: 'table-row-group' }}>
        {children}
      </tbody>
    ),
    tr: ({ children }) => (
      <tr style={{ display: 'table-row', borderBottom: '1px solid rgba(0, 0, 0, 0.08)' }}>
        {children}
      </tr>
    ),
    th: ({ children }) => (
      <th style={{ border: '1px solid rgba(0, 0, 0, 0.12)', padding: '14px 18px', textAlign: 'left', fontWeight: 600, backgroundColor: 'rgba(0, 0, 0, 0.05)', display: 'table-cell', verticalAlign: 'middle', fontSize: '0.95em', color: 'inherit' }}>
        {w(children)}
      </th>
    ),
    td: ({ children }) => (
      <td style={{ border: '1px solid rgba(0, 0, 0, 0.1)', padding: '14px 18px', display: 'table-cell', verticalAlign: 'top', lineHeight: 1.7 }}>
        {w(children)}
      </td>
    ),
    hr: () => (
      <hr style={{ border: 'none', borderTop: '2px solid rgba(0, 0, 0, 0.1)', margin: '32px 0', display: 'block' }} />
    ),
  }
}

const MessageContent: React.FC<MessageContentProps> = ({
  content,
  sources,
  onCitationClick,
  isStreaming = false
}) => {
  // Pre-process content: normalize [filename] → [N] and then [N] → citation markers.
  // Also remap [N] occurrences to unique sequential display numbers so no two badges
  // in the same message share a number (footnote-style: [1], [2], [3]…).
  const { processedText, effectiveSources } = useMemo(() => {
    let text = content

    // Normalize LLM citation variants to plain [N]:
    // [документ N], [doc N], [источник N], [Документ N], etc. → [N]
    text = text.replace(/\[(?:документ|doc|источник|файл|file|ref|ссылка)\s*\.?\s*(\d+)\s*\]/gi, '[$1]')

    // Strip [N] from bold headers: **[1] filename:** → **filename:**
    text = text.replace(/(\*{1,3})((?:\[\d+\]\s*)+)/g, '$1')

    // Move leading [N] markers to end of sentence (safety net for backend normalization)
    // '[1] some text.' → 'some text. [1]'
    // '[1][2] some text.' → 'some text. [1][2]'
    text = text.replace(/^(\s*)((?:\[\d+\]\s*)+)(.+)$/gm, (_match, indent, cites, rest) => {
      const c = cites.replace(/\s+/g, '')
      const trimmed = rest.trimEnd()
      // Skip pure header lines like "filename.pdf:"
      if (/^[^:]+:\s*$/.test(trimmed)) return indent + trimmed
      // Don't double if already ends with [N]
      if (/\[\d+\]\s*[.!?]?\s*$/.test(trimmed)) return indent + trimmed + ' ' + '' // no-op
      const punc = trimmed.match(/([.!?])\s*$/)
      if (punc) return indent + trimmed.slice(0, -punc[0].length) + punc[1] + ' ' + c
      return indent + trimmed + ' ' + c
    })

    // Replace lines of repeated decorative symbols (•••, ===, ···, etc.) with ---
    text = text.replace(/^([•·\-=_~*]{3,})\s*$/gm, '---')

    // Remove trailing lines that consist only of citation numbers like [1] [2] [3]
    // These are "footnote rows" the LLM adds at the end despite instructions
    text = text.replace(/(\n+(\s*\[\d+\]\s*)+)+\s*$/, '')

    // Auto-inject [N] for bullet items under numbered document sections.
    // The LLM structures answers as "1. Из файла 'X.pdf':\n  • item" —
    // the section number IS the citation index, so append it to each bullet.
    if (sources.length > 0) {
      const lines = text.split('\n')
      let currentDocNum: number | null = null
      text = lines.map(line => {
        // Detect numbered document section headers: "1. <anything>:" or "1. **<anything>**"
        // Only when N is within the range of available sources
        const sectionMatch = line.match(/^\s*(\d+)\.\s+.+[:\s]*$/)
        if (sectionMatch) {
          const num = parseInt(sectionMatch[1], 10)
          if (num >= 1 && num <= sources.length) {
            currentDocNum = num
            return line
          }
        }
        // Bullet under a document section — inject [N] if no citation yet
        if (currentDocNum !== null && /^\s*[-•*]\s+\S/.test(line) && !/\[\d/.test(line)) {
          return line.trimEnd() + ` [${currentDocNum}]`
        }
        // Blank line — keep section context
        if (/^\s*$/.test(line)) return line
        // Any other non-bullet line resets section context
        currentDocNum = null
        return line
      }).join('\n')
    }

    // Convert [filename.ext, ...] references to [N] using sources
    if (sources.length > 0) {
      const fileToIndex = new Map<string, number>()
      sources.forEach((s, i) => {
        const fname = (s.file || s.title || '').toLowerCase().trim()
        if (fname && !fileToIndex.has(fname)) {
          fileToIndex.set(fname, i + 1)
        }
      })

      for (const [fname, idx] of fileToIndex) {
        const escaped = fname.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        const regex = new RegExp(`\\[${escaped}[^\\]]*\\]`, 'gi')
        text = text.replace(regex, `[${idx}]`)
        const srcRegex = new RegExp(`(Источник:\\s*)${escaped}[^\\n]*`, 'gi')
        text = text.replace(srcRegex, `$1[${idx}]`)
      }
    }

    // Normalize comma-separated citations like [1, 2, 4, 5] → [1][2][4][5]
    if (sources.length > 0) {
      text = text.replace(/\[(\d+(?:\s*,\s*\d+)+)\]/g, (_match, nums) => {
        return nums.split(',').map((n: string) => `[${n.trim()}]`).join('')
      })
    }

    // Remap every [N] occurrence to a unique sequential display number.
    // First occurrence of any valid source → [1], second → [2], etc.
    // This means no two badges share the same number, like proper footnotes.
    const remappedSources: SourceInfo[] = []
    if (sources.length > 0) {
      let counter = 0
      text = text.replace(/\[(\d+)\]/g, (match, num) => {
        const idx = parseInt(num, 10)
        if (idx < 1 || idx > sources.length) return match
        counter++
        remappedSources.push(sources[idx - 1])
        return `[${counter}]`
      })
    }

    const effectiveSources = remappedSources.length > 0 ? remappedSources : sources

    // Convert [N] → unique placeholders (won't be parsed as markdown links)
    if (effectiveSources.length > 0) {
      text = text.replace(/\[(\d+)\]/g, (match, num) => {
        const idx = parseInt(num, 10)
        if (idx >= 1 && idx <= effectiveSources.length) {
          return `${CITE_PREFIX}${idx}${CITE_SUFFIX}`
        }
        return match
      })
    }

    return { processedText: text, effectiveSources }
  }, [content, sources])

  // Build markdown components with citation injection
  const markdownComponents = useMemo(
    () => buildMarkdownComponents(effectiveSources, onCitationClick),
    [effectiveSources, onCitationClick]
  )

  return (
    <div style={{
      maxWidth: '100%',
      wordWrap: 'break-word',
      overflowWrap: 'break-word'
    }}>
      <ReactMarkdown
        components={markdownComponents}
        remarkPlugins={[remarkGfm]}
      >
        {processedText}
      </ReactMarkdown>
      {isStreaming && <span className="streaming-cursor" aria-hidden="true" />}
    </div>
  )
}

export default MessageContent
