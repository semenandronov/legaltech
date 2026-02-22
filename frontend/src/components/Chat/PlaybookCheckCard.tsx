/**
 * PlaybookCheckCard — карточка результата проверки Playbook в стиле Harvey.
 * Показывает мультицветный прогресс-бар, правила сгруппированные по статусу.
 */
import { useState } from 'react'
import { ChevronUp, ChevronDown, Shield } from 'lucide-react'

interface RuleResult {
  rule_id: string
  rule_name: string
  rule_type: 'red_line' | 'no_go' | 'fallback' | 'standard' | string
  status: 'passed' | 'violation' | 'not_found' | 'warning' | 'error' | string
  issue_description?: string
  suggested_fix?: string
  found_text?: string
  confidence?: number
}

export interface PlaybookCheckData {
  check_id: string
  playbook_id: string
  playbook_name: string
  document_id: string
  document_name: string
  overall_status: string
  compliance_score: number
  red_line_violations: number
  fallback_issues: number
  no_go_violations: number
  passed_rules: number
  results: RuleResult[]
}

interface PlaybookCheckCardProps {
  check: PlaybookCheckData
}

type FilterTab = 'issues' | 'all'

function getRuleGroup(r: RuleResult): 'violation' | 'warning' | 'passed' {
  if (r.status === 'violation' || r.status === 'not_found' || r.status === 'error') return 'violation'
  if (r.status === 'warning' || (r.rule_type === 'fallback' && r.status !== 'passed')) return 'warning'
  return 'passed'
}

function getRuleDescription(r: RuleResult): string | undefined {
  return r.issue_description || r.found_text || r.suggested_fix
}

// ─── Rule row ────────────────────────────────────────────────────────────────

function RuleRow({ rule }: { rule: RuleResult }) {
  const [open, setOpen] = useState(false)
  const desc = getRuleDescription(rule)
  const group = getRuleGroup(rule)

  const dotColor = group === 'violation' ? '#ef4444' : group === 'warning' ? '#f59e0b' : '#22c55e'

  return (
    <div
      className="py-3 px-4 border-b last:border-b-0 cursor-pointer hover:bg-gray-50 transition-colors"
      style={{ borderColor: 'var(--color-border, #f1f5f9)' }}
      onClick={() => desc && setOpen(o => !o)}
    >
      <div className="flex items-start gap-2.5">
        {/* Color dot */}
        <div
          className="w-2 h-2 rounded-full mt-1.5 flex-shrink-0"
          style={{ backgroundColor: dotColor }}
        />
        <div className="flex-1 min-w-0">
          {/* Rule name */}
          <p
            className="text-sm font-medium leading-snug"
            style={{ color: 'var(--color-text-primary)' }}
          >
            {rule.rule_name}
          </p>

          {/* Description preview (2 lines) */}
          {desc && !open && (
            <p
              className="text-xs mt-0.5 line-clamp-2 leading-relaxed"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {desc}
            </p>
          )}

          {/* Expanded detail */}
          {open && (
            <div className="mt-2 space-y-2">
              {rule.found_text && (
                <blockquote
                  className="text-xs italic px-3 py-2 rounded-md border-l-2"
                  style={{
                    color: 'var(--color-text-secondary)',
                    borderLeftColor: dotColor,
                    background: 'var(--color-bg-primary)',
                    border: '1px solid var(--color-border)',
                  }}
                >
                  «{rule.found_text.length > 300 ? rule.found_text.substring(0, 300) + '…' : rule.found_text}»
                </blockquote>
              )}
              {rule.issue_description && (
                <p className="text-xs" style={{ color: '#dc2626' }}>
                  {rule.issue_description}
                </p>
              )}
              {rule.suggested_fix && (
                <div
                  className="text-xs px-3 py-2 rounded-md"
                  style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', color: '#166534' }}
                >
                  <span className="font-semibold">Рекомендация: </span>
                  {rule.suggested_fix.length > 400 ? rule.suggested_fix.substring(0, 400) + '…' : rule.suggested_fix}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Grouped section ─────────────────────────────────────────────────────────

function RuleSection({
  title,
  dotColor,
  rules,
  defaultOpen = true,
}: {
  title: string
  dotColor: string
  rules: RuleResult[]
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)

  if (rules.length === 0) return null

  return (
    <div className="border-b last:border-b-0" style={{ borderColor: 'var(--color-border, #e2e8f0)' }}>
      {/* Section header */}
      <button
        className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-gray-50 transition-colors text-left"
        onClick={() => setOpen(o => !o)}
      >
        <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: dotColor }} />
        <span className="text-sm font-medium flex-1" style={{ color: 'var(--color-text-primary)' }}>
          {title}
        </span>
        <span className="text-xs mr-2" style={{ color: 'var(--color-text-secondary)' }}>
          {rules.length} {rules.length === 1 ? 'правило' : rules.length < 5 ? 'правила' : 'правил'}
        </span>
        {open
          ? <ChevronUp className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-secondary)' }} />
          : <ChevronDown className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-secondary)' }} />
        }
      </button>

      {/* Rules */}
      {open && (
        <div>
          {rules.map(rule => (
            <RuleRow key={rule.rule_id} rule={rule} />
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Main card ───────────────────────────────────────────────────────────────

export function PlaybookCheckCard({ check }: PlaybookCheckCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [filter, setFilter] = useState<FilterTab>('issues')

  const total = check.results.length
  const violations = check.results.filter(r => getRuleGroup(r) === 'violation')
  const warnings   = check.results.filter(r => getRuleGroup(r) === 'warning')
  const passed     = check.results.filter(r => getRuleGroup(r) === 'passed')

  // Multicolor bar segments (% of total)
  const pctPassed  = total > 0 ? (passed.length / total) * 100 : 0
  const pctWarn    = total > 0 ? (warnings.length / total) * 100 : 0
  const pctViol    = total > 0 ? (violations.length / total) * 100 : 0

  const hasIssues = violations.length > 0 || warnings.length > 0

  const score = check.compliance_score
  const scoreColor = score >= 80 ? '#22c55e' : score >= 50 ? '#f59e0b' : '#ef4444'

  return (
    <div
      className="overflow-hidden rounded-xl border mt-3"
      style={{
        borderColor: 'var(--color-border, #e2e8f0)',
        background: 'var(--color-bg-secondary, #f8fafc)',
        fontSize: 13,
      }}
    >
      {/* ── Header ── */}
      <div
        className="flex items-center gap-2.5 px-4 py-3 cursor-pointer select-none"
        onClick={() => setExpanded(e => !e)}
      >
        <Shield className="w-4 h-4 flex-shrink-0" style={{ color: scoreColor }} />

        <div className="flex-1 min-w-0">
          <p className="font-semibold text-sm truncate" style={{ color: 'var(--color-text-primary)' }}>
            {check.playbook_name}
          </p>
          <p className="text-xs truncate mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
            {check.document_name}
          </p>
        </div>

        {/* Score */}
        <span className="text-base font-bold flex-shrink-0" style={{ color: scoreColor }}>
          {score.toFixed(0)}%
        </span>

        {/* Compact badges */}
        <div className="flex items-center gap-1 flex-shrink-0">
          {violations.length > 0 && (
            <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs font-semibold"
              style={{ background: '#fee2e2', color: '#991b1b' }}>
              ✗ {violations.length}
            </span>
          )}
          {warnings.length > 0 && (
            <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs font-semibold"
              style={{ background: '#fef9c3', color: '#854d0e' }}>
              ! {warnings.length}
            </span>
          )}
          {passed.length > 0 && (
            <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs font-semibold"
              style={{ background: '#dcfce7', color: '#15803d' }}>
              ✓ {passed.length}
            </span>
          )}
        </div>

        {expanded
          ? <ChevronUp className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--color-text-secondary)' }} />
          : <ChevronDown className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--color-text-secondary)' }} />
        }
      </div>

      {/* ── Multicolor progress bar ── */}
      <div className="flex h-1.5" style={{ background: '#e5e7eb' }}>
        {pctPassed > 0 && (
          <div style={{ width: `${pctPassed}%`, background: '#22c55e', transition: 'width 0.5s' }} />
        )}
        {pctWarn > 0 && (
          <div style={{ width: `${pctWarn}%`, background: '#f59e0b', transition: 'width 0.5s' }} />
        )}
        {pctViol > 0 && (
          <div style={{ width: `${pctViol}%`, background: '#ef4444', transition: 'width 0.5s' }} />
        )}
      </div>

      {/* ── Expanded body ── */}
      {expanded && (
        <div style={{ borderTop: '1px solid var(--color-border, #e2e8f0)' }}>
          {/* Filter tabs */}
          {hasIssues && (
            <div
              className="flex border-b"
              style={{ borderColor: 'var(--color-border, #e2e8f0)' }}
            >
              {(['issues', 'all'] as FilterTab[]).map(tab => (
                <button
                  key={tab}
                  onClick={() => setFilter(tab)}
                  className="px-4 py-2 text-xs font-medium transition-colors"
                  style={{
                    color: filter === tab ? 'var(--color-accent, #6366f1)' : 'var(--color-text-secondary)',
                    borderBottom: filter === tab ? '2px solid var(--color-accent, #6366f1)' : '2px solid transparent',
                    marginBottom: -1,
                  }}
                >
                  {tab === 'issues' ? 'Только проблемы' : 'Все правила'}
                </button>
              ))}
            </div>
          )}

          {/* Rule groups */}
          <div className="max-h-[450px] overflow-y-auto">
            {filter === 'issues' || !hasIssues ? (
              <>
                <RuleSection
                  title="Нарушения"
                  dotColor="#ef4444"
                  rules={violations}
                  defaultOpen={true}
                />
                <RuleSection
                  title="Требует внимания"
                  dotColor="#f59e0b"
                  rules={warnings}
                  defaultOpen={true}
                />
                {filter === 'all' && (
                  <RuleSection
                    title="Соответствует"
                    dotColor="#22c55e"
                    rules={passed}
                    defaultOpen={false}
                  />
                )}
              </>
            ) : (
              <>
                <RuleSection title="Нарушения" dotColor="#ef4444" rules={violations} defaultOpen={true} />
                <RuleSection title="Требует внимания" dotColor="#f59e0b" rules={warnings} defaultOpen={true} />
                <RuleSection title="Соответствует" dotColor="#22c55e" rules={passed} defaultOpen={false} />
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
