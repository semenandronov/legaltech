import React, { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { SourceInfo } from '../../services/api'
import { InlineCitationAdapter } from './InlineCitationAdapter'
import { linkCitationsInline } from './citationLinker'
import type { AnswerBlockItem } from './AnswerBlocks'

interface MessageContentProps {
  content: string
  sources: SourceInfo[]
  onCitationClick?: (source: SourceInfo) => void
  isStreaming?: boolean
  /** Ограничение кандидатов для линкера (Phase 2 answer_blocks). */
  answerBlocks?: AnswerBlockItem[]
}

const ZW = '\u200B\u200B'
/** cit_<hex> + displayN; либо legacy CITE_<digits>_ENDCITE без id. */
const CITE_REGEX = new RegExp(
  `${ZW}(?:CITE_(cit_[a-f0-9]{12})_(\\d+)_ENDCITE|CITE_(\\d+)_ENDCITE)${ZW}`,
  'gi',
)

/**
 * Walk React children and replace citation markers with InlineCitationAdapter components.
 */
function injectCitations(
  children: React.ReactNode,
  sources: SourceInfo[],
  onCitationClick?: (source: SourceInfo) => void,
  keyPrefix = '',
): React.ReactNode {
  return React.Children.map(children, (child, childIdx) => {
    if (typeof child === 'string') {
      CITE_REGEX.lastIndex = 0
      if (!CITE_REGEX.test(child)) return child
      CITE_REGEX.lastIndex = 0

      const parts: (string | React.ReactElement)[] = []
      let lastIdx = 0
      let match: RegExpExecArray | null
      let occ = 0

      while ((match = CITE_REGEX.exec(child)) !== null) {
        if (match.index > lastIdx) {
          parts.push(child.substring(lastIdx, match.index))
        }
        const citId = match[1]
        const displayWithId = match[2]
        const legacyOnly = match[3]
        occ += 1

        if (citId && displayWithId) {
          parts.push(
            <InlineCitationAdapter
              key={`${keyPrefix}c-${childIdx}-${occ}`}
              displayNumber={parseInt(displayWithId, 10)}
              citationId={citId}
              sources={sources}
              onClick={onCitationClick}
            />,
          )
        } else if (legacyOnly) {
          const displayN = parseInt(legacyOnly, 10)
          parts.push(
            <InlineCitationAdapter
              key={`${keyPrefix}c-${childIdx}-${occ}`}
              displayNumber={displayN}
              legacySourceIndex={displayN - 1}
              sources={sources}
              onClick={onCitationClick}
            />,
          )
        }

        lastIdx = match.index + match[0].length
      }
      if (lastIdx < child.length) {
        parts.push(child.substring(lastIdx))
      }
      return <>{parts}</>
    }

    if (React.isValidElement(child) && child.props?.children != null) {
      return React.cloneElement(
        child,
        { ...child.props },
        injectCitations(child.props.children, sources, onCitationClick, `${keyPrefix}${childIdx}-`),
      )
    }

    return child
  })
}

function extractChildText(children: React.ReactNode): string {
  if (typeof children === 'string') return children
  if (typeof children === 'number') return String(children)
  if (Array.isArray(children)) return children.map(extractChildText).join('')
  if (React.isValidElement(children) && (children.props as any)?.children != null)
    return extractChildText((children.props as any).children)
  return ''
}

function buildMarkdownComponents(
  sources: SourceInfo[],
  onCitationClick?: (source: SourceInfo) => void,
): Components {
  const w = (children: React.ReactNode) => injectCitations(children, sources, onCitationClick)

  const tbl = { headers: [] as string[], col: 0, inHead: false }

  return {
    p: ({ children }) => (
      <p
        style={{
          margin: '0 0 0.75rem 0',
          lineHeight: 1.65,
          display: 'block',
          color: 'var(--color-text-primary, inherit)',
        }}
      >
        {w(children)}
      </p>
    ),
    h1: ({ children }) => (
      <h1
        style={{
          fontSize: '1.2rem',
          fontWeight: 650,
          color: 'var(--color-text-primary, inherit)',
          margin: '1.25rem 0 0.5rem 0',
          display: 'block',
          lineHeight: 1.35,
          letterSpacing: '-0.015em',
        }}
      >
        {w(children)}
      </h1>
    ),
    h2: ({ children }) => (
      <h2
        style={{
          fontSize: '1.08rem',
          fontWeight: 650,
          color: 'var(--color-text-primary, inherit)',
          margin: '1.1rem 0 0.45rem 0',
          display: 'block',
          lineHeight: 1.4,
          letterSpacing: '-0.01em',
        }}
      >
        {w(children)}
      </h2>
    ),
    h3: ({ children }) => (
      <h3
        style={{
          fontSize: '1.02rem',
          fontWeight: 600,
          color: 'var(--color-text-primary, inherit)',
          margin: '1rem 0 0.4rem 0',
          display: 'block',
          lineHeight: 1.45,
        }}
      >
        {w(children)}
      </h3>
    ),
    h4: ({ children }) => (
      <h4
        style={{
          fontSize: '0.98rem',
          fontWeight: 600,
          color: 'var(--color-text-secondary, inherit)',
          margin: '0.85rem 0 0.35rem 0',
          display: 'block',
          lineHeight: 1.45,
        }}
      >
        {w(children)}
      </h4>
    ),
    ul: ({ children }) => (
      <ul
        style={{
          margin: '0.5rem 0 0.75rem 0',
          paddingLeft: '1.25rem',
          display: 'block',
          lineHeight: 1.65,
          listStyleType: 'disc',
          color: 'var(--color-text-primary, inherit)',
        }}
      >
        {children}
      </ul>
    ),
    ol: ({ children }) => (
      <ol
        style={{
          margin: '0.5rem 0 0.75rem 0',
          paddingLeft: '1.25rem',
          display: 'block',
          lineHeight: 1.65,
          listStyleType: 'decimal',
          color: 'var(--color-text-primary, inherit)',
        }}
      >
        {children}
      </ol>
    ),
    li: ({ children }) => (
      <li style={{ margin: '0.35rem 0', display: 'list-item', lineHeight: 1.65, paddingLeft: '4px' }}>
        {w(children)}
      </li>
    ),
    code: ({ children, className }) => {
      const isInline = !className
      return isInline ? (
        <code
          style={{
            backgroundColor: 'rgba(0, 0, 0, 0.08)',
            padding: '3px 6px',
            borderRadius: '4px',
            fontSize: '0.9em',
            fontFamily: "'Fira Code', 'Courier New', monospace",
            color: 'inherit',
            display: 'inline',
            fontWeight: 500,
          }}
        >
          {children}
        </code>
      ) : (
        <code
          style={{
            backgroundColor: 'rgba(0, 0, 0, 0.06)',
            padding: '14px 16px',
            borderRadius: '8px',
            fontSize: '0.9em',
            fontFamily: "'Fira Code', 'Courier New', monospace",
            color: 'inherit',
            display: 'block',
            overflowX: 'auto',
            margin: '16px 0',
            lineHeight: 1.6,
          }}
        >
          {children}
        </code>
      )
    },
    pre: ({ children }) => (
      <pre
        style={{
          backgroundColor: 'rgba(0, 0, 0, 0.04)',
          padding: '16px',
          borderRadius: '8px',
          fontSize: '0.9em',
          fontFamily: "'Fira Code', 'Courier New', monospace",
          overflowX: 'auto',
          margin: '16px 0',
          display: 'block',
          lineHeight: 1.6,
        }}
      >
        {children}
      </pre>
    ),
    strong: ({ children }) => (
      <strong style={{ fontWeight: 600, display: 'inline', color: 'inherit' }}>{w(children)}</strong>
    ),
    em: ({ children }) => (
      <em style={{ fontStyle: 'italic', display: 'inline', color: 'inherit' }}>{w(children)}</em>
    ),
    a: ({ children, href }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          color: 'var(--color-accent, #2563eb)',
          textDecoration: 'underline',
          textDecorationColor: 'color-mix(in srgb, var(--color-accent, #2563eb) 35%, transparent)',
          display: 'inline',
          textUnderlineOffset: '3px',
          fontWeight: 500,
        }}
      >
        {children}
      </a>
    ),
    blockquote: ({ children }) => (
      <blockquote
        style={{
          borderLeft: '3px solid color-mix(in srgb, var(--color-accent, #2563eb) 45%, var(--color-border, #ccc))',
          paddingLeft: '1rem',
          margin: '0.65rem 0',
          color: 'var(--color-text-secondary, inherit)',
          fontStyle: 'normal',
          display: 'block',
          paddingTop: '0.35rem',
          paddingBottom: '0.35rem',
          paddingRight: '0.75rem',
          backgroundColor: 'var(--color-bg-secondary, rgba(0,0,0,0.02))',
          borderRadius: '0 6px 6px 0',
        }}
      >
        {w(children)}
      </blockquote>
    ),
    table: ({ children }) => {
      tbl.headers = []
      tbl.col = 0
      tbl.inHead = false
      return <div style={{ margin: '20px 0' }}>{children}</div>
    },
    thead: ({ children }) => {
      tbl.inHead = true
      tbl.headers = []
      return <div style={{ display: 'none' }}>{children}</div>
    },
    tbody: ({ children }) => {
      tbl.inHead = false
      return <>{children}</>
    },
    tr: ({ children }) => {
      if (tbl.inHead) return null
      tbl.col = 0
      return (
        <div
          style={{
            borderLeft: '3px solid rgba(0,0,0,0.12)',
            paddingLeft: '14px',
            margin: '14px 0',
            display: 'flex',
            flexDirection: 'column',
            gap: '6px',
          }}
        >
          {children}
        </div>
      )
    },
    th: ({ children }) => {
      tbl.headers.push(extractChildText(children))
      return null
    },
    td: ({ children }) => {
      const label = tbl.headers[tbl.col] ?? ''
      tbl.col++
      return (
        <div style={{ lineHeight: 1.7, display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          {label && (
            <span style={{ fontWeight: 600, flexShrink: 0, color: 'inherit' }}>{label}:</span>
          )}
          <span style={{ color: 'inherit' }}>{w(children)}</span>
        </div>
      )
    },
    hr: () => (
      <hr
        style={{
          border: 'none',
          borderTop: '1px solid var(--color-border, rgba(0,0,0,0.1))',
          margin: '1rem 0',
          display: 'block',
        }}
      />
    ),
  }
}

function lightNormalizeForLegacyCitations(text: string, sources: SourceInfo[]): string {
  let t = text
  t = t.replace(/\[(?:документ|doc|источник|файл|file|ref|ссылка)\s*\.?\s*(\d+)\s*\]/gi, '[$1]')
  t = t.replace(/(\*{1,3})((?:\[\d+\]\s*)+)/g, '$1')
  t = t.replace(/^(\s*)((?:\[\d+\]\s*)+)(.+)$/gm, (_match, indent, cites, rest) => {
    const c = cites.replace(/\s+/g, '')
    const trimmed = rest.trimEnd()
    if (/^[^:]+:\s*$/.test(trimmed)) return indent + trimmed
    if (/\[\d+\]\s*[.!?]?\s*$/.test(trimmed)) return indent + trimmed + ' '
    const punc = trimmed.match(/([.!?])\s*$/)
    if (punc) return indent + trimmed.slice(0, -punc[0].length) + punc[1] + ' ' + c
    return indent + trimmed + ' ' + c
  })
  t = t.replace(/^([•·\-=_~*]{3,})\s*$/gm, '---')
  t = t.replace(/(\n+(\s*\[\d+\]\s*)+)+\s*$/, '')

  if (sources.length > 0) {
    const lines = t.split('\n')
    let currentDocNum: number | null = null
    t = lines
      .map((line) => {
        const sectionMatch = line.match(/^\s*(\d+)\.\s+.+[:\s]*$/)
        if (sectionMatch) {
          const num = parseInt(sectionMatch[1], 10)
          if (num >= 1 && num <= sources.length) {
            currentDocNum = num
            return line
          }
        }
        if (currentDocNum !== null && /^\s*[-•*]\s+\S/.test(line) && !/\[\d/.test(line)) {
          return line.trimEnd() + ` [${currentDocNum}]`
        }
        if (/^\s*$/.test(line)) return line
        currentDocNum = null
        return line
      })
      .join('\n')
  }

  if (sources.length > 0) {
    const fileToIndex = new Map<string, number>()
    sources.forEach((s, i) => {
      const fname = (s.file || s.title || '').toLowerCase().trim()
      if (fname && !fileToIndex.has(fname)) fileToIndex.set(fname, i + 1)
    })
    for (const [fname, idx] of fileToIndex) {
      const escaped = fname.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const regex = new RegExp(`\\[${escaped}[^\\]]*\\]`, 'gi')
      t = t.replace(regex, `[${idx}]`)
      const srcRegex = new RegExp(`(Источник:\\s*)${escaped}[^\\n]*`, 'gi')
      t = t.replace(srcRegex, `$1[${idx}]`)
    }
  }

  if (sources.length > 0) {
    t = t.replace(/\[(\d+(?:\s*,\s*\d+)+)\]/g, (_match, nums) =>
      nums.split(',').map((n: string) => `[${n.trim()}]`).join(''),
    )
  }
  return t
}

/** Legacy: [N] → CITE_N_ENDCITE и сжатый порядок sources по первому появлению. */
function legacyBracketToMarkers(text: string, sources: SourceInfo[]): { text: string; ordered: SourceInfo[] } {
  const remappedSources: SourceInfo[] = []
  if (sources.length === 0) return { text, ordered: sources }

  const srcIdxToDisplayNum = new Map<number, number>()
  let counter = 0
  const replaced = text.replace(/\[(\d+)\]/g, (match, num) => {
    const idx = parseInt(num, 10)
    if (idx < 1 || idx > sources.length) return match
    const srcIdx = idx - 1
    if (srcIdxToDisplayNum.has(srcIdx)) return ''
    counter++
    srcIdxToDisplayNum.set(srcIdx, counter)
    remappedSources.push(sources[srcIdx])
    return `[${counter}]`
  })

  const effectiveSources = remappedSources.length > 0 ? remappedSources : sources
  const ZW = '\u200B\u200B'
  const withMarkers = effectiveSources.length
    ? replaced.replace(/\[(\d+)\]/g, (match, num) => {
        const idx = parseInt(num, 10)
        if (idx >= 1 && idx <= effectiveSources.length) {
          return `${ZW}CITE_${idx}_ENDCITE${ZW}`
        }
        return match
      })
    : replaced

  return { text: withMarkers, ordered: effectiveSources }
}

const MessageContent: React.FC<MessageContentProps> = ({
  content,
  sources,
  onCitationClick,
  isStreaming = false,
  answerBlocks,
}) => {
  const { processedText, effectiveSources } = useMemo(() => {
    const hasCitationIds = sources.some((s) => s.citation_id)
    const useLinker = hasCitationIds && sources.length > 0 && !isStreaming

    if (useLinker) {
      const { markdown, orderedSources } = linkCitationsInline({
        markdown: content,
        sources,
        answerBlocks,
      })
      return { processedText: markdown, effectiveSources: orderedSources }
    }

    let text = lightNormalizeForLegacyCitations(content, sources)
    const { text: withMarkers, ordered } = legacyBracketToMarkers(text, sources)
    return { processedText: withMarkers, effectiveSources: ordered }
  }, [content, sources, isStreaming, answerBlocks])

  const markdownComponents = useMemo(
    () => buildMarkdownComponents(effectiveSources, onCitationClick),
    [effectiveSources, onCitationClick],
  )

  return (
    <div
      className="assistant-markdown"
      style={{
        maxWidth: '100%',
        wordWrap: 'break-word',
        overflowWrap: 'break-word',
        fontSize: '0.9375rem',
        color: 'var(--color-text-primary)',
      }}
    >
      <ReactMarkdown components={markdownComponents} remarkPlugins={[remarkGfm]}>
        {processedText}
      </ReactMarkdown>
      {isStreaming && <span className="streaming-cursor" aria-hidden="true" />}
    </div>
  )
}

export default MessageContent
