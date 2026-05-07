import React from 'react'
import { describe, expect, it } from 'vitest'
import TestRenderer from 'react-test-renderer'
import type { SourceInfo } from '@/services/api'
import { InlineCitationAdapter, resolveInlineCitationSource } from './InlineCitationAdapter'

describe('resolveInlineCitationSource', () => {
  const sources: SourceInfo[] = [
    { file: 'a.pdf', citation_id: 'cit_aaa0000000001' },
    { file: 'b.pdf', citation_id: 'cit_bbb0000000002' },
  ]

  it('находит по citation_id', () => {
    expect(resolveInlineCitationSource(sources, 'cit_bbb0000000002', undefined)?.file).toBe('b.pdf')
  })

  it('legacy: по индексу в массиве', () => {
    expect(resolveInlineCitationSource(sources, undefined, 0)?.file).toBe('a.pdf')
  })
})

describe('InlineCitationAdapter', () => {
  it('рендерит superscript с displayNumber', () => {
    const sources: SourceInfo[] = [{ file: 'x.pdf', citation_id: 'cit_ccc0000000003' }]
    const el = TestRenderer.create(
      React.createElement(InlineCitationAdapter, {
        displayNumber: 1,
        citationId: 'cit_ccc0000000003',
        sources,
      }),
    )
    const json = el.toJSON()
    const walk = (n: unknown): string => {
      if (n == null) return ''
      if (typeof n === 'string') return n
      if (Array.isArray(n)) return n.map(walk).join('')
      if (typeof n === 'object' && 'children' in (n as any)) return walk((n as any).children)
      return ''
    }
    expect(walk(json)).toContain('1')
  })
})
