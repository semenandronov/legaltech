/**
 * PlaybookResultsPanel - Панель результатов проверки Playbook
 * 
 * Показывает результаты проверки документа и позволяет
 * навигировать к конкретным местам в документе
 */
import { useState } from 'react'
import {
  X,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  FileText,
  Eye,
  Download,
  RefreshCw,
  Lightbulb,
  Check,
} from 'lucide-react'
import { toast } from 'sonner'

interface RuleResult {
  rule_id: string
  rule_name: string
  rule_type: 'red_line' | 'no_go' | 'fallback' | 'standard' | string
  status: 'passed' | 'violation' | 'warning' | 'not_applicable' | 'not_found' | 'error' | string
  issue_description?: string
  suggestion?: string
  suggested_fix?: string  // Backend uses this field
  severity?: number | string
  found_text?: string
  location?: {
    start?: number
    end?: number
    page?: number
    section?: string
  }
  document_location?: {
    start: number
    end: number
    text: string
  }
  confidence?: number
  reasoning?: string
  ui_status?: 'acceptable' | 'needs_review' | 'not_acceptable' | string
  guidance?: string
  suggested_options?: { label: string; type: 'standard' | 'fallback' | string; text: string }[]
  citations?: string[]
  occurrences?: Array<{
    type: 'unacceptable' | 'fallback' | 'standard' | string
    phrase: string
    char_start: number
    char_end: number
    context: string
  }>
}

interface PlaybookResult {
  id: string
  playbook_id: string
  playbook_name: string
  document_id: string
  compliance_score: number
  total_rules: number
  passed_rules: number
  red_line_violations: number
  no_go_violations: number
  fallback_issues: number
  results: RuleResult[]
  redline_html?: string
  summary?: string
  recommendations?: string[]
  created_at: string
}

interface PlaybookResultsPanelProps {
  result?: PlaybookResult | null
  onClose: () => void
  onNavigateToIssue?: (location: { start: number; end: number }) => void
  onScrollToText?: (text: string, nthOccurrence?: number) => boolean
  onApplyFix?: (foundText: string, fixedText: string) => boolean
  onRerun?: () => void
  onDownloadReport?: () => void
  isChecking?: boolean
  selectedPlaybookName?: string | null
  errorMessage?: string | null
  onSelectPlaybook?: () => void
}

export const PlaybookResultsPanel = ({
  result,
  onClose,
  onScrollToText,
  onApplyFix,
  onRerun,
  onDownloadReport,
  isChecking = false,
  selectedPlaybookName,
  errorMessage,
  onSelectPlaybook
}: PlaybookResultsPanelProps) => {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())
  const [appliedRules, setAppliedRules] = useState<Set<string>>(new Set())
  const [expandedRuleId, setExpandedRuleId] = useState<string | null>(null)

  const effectivePlaybookName =
    result?.playbook_name ||
    selectedPlaybookName ||
    'Проверка по playbook'

  /** Harvey-style classification for a rule result */
  const getHarveyClassification = (rule: RuleResult) => {
    if (rule.status === 'passed') {
      return { label: 'Приемлемо', icon: '✅', color: '#16a34a', bg: 'rgba(22, 163, 74, 0.1)', border: 'rgba(22, 163, 74, 0.25)' }
    }
    if (rule.status === 'warning' || rule.rule_type === 'fallback') {
      return { label: 'Требует проверки', icon: '🔍', color: '#ca8a04', bg: 'rgba(202, 138, 4, 0.08)', border: 'rgba(202, 138, 4, 0.2)' }
    }
    return { label: 'Нарушения', icon: '❌', color: '#dc2626', bg: 'rgba(220, 38, 38, 0.08)', border: 'rgba(220, 38, 38, 0.2)' }
  }

  const getRuleTypeBadge = (type: RuleResult['rule_type']) => {
    const styles: Record<string, { bg: string; text: string }> = {
      red_line: { bg: 'bg-red-100', text: 'text-red-700' },
      no_go: { bg: 'bg-purple-100', text: 'text-purple-700' },
      fallback: { bg: 'bg-yellow-100', text: 'text-yellow-700' },
      standard: { bg: 'bg-blue-100', text: 'text-blue-700' }
    }
    const labels: Record<string, string> = {
      red_line: 'Red Line',
      no_go: 'No-Go',
      fallback: 'Fallback',
      standard: 'Standard'
    }
    const style = styles[type] || styles.standard
    return (
      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${style.bg} ${style.text}`}>
        {labels[type] || type}
      </span>
    )
  }

  const violations = (result?.results || []).filter(r =>
    r.status === 'violation' || r.status === 'not_found' || r.status === 'error'
  )
  const warnings = (result?.results || []).filter(r => r.status === 'warning' || r.rule_type === 'fallback')
  const passed = (result?.results || []).filter(r => r.status === 'passed')

  // Count bar segments by rule status (consistent with group logic)
  let barStandard = 0, barFallback = 0, barUnacceptable = 0
  for (const rule of result?.results || []) {
    if (rule.status === 'passed') barStandard++
    else if (rule.status === 'warning' || rule.rule_type === 'fallback') barFallback++
    else if (rule.status === 'violation' || rule.status === 'not_found' || rule.status === 'error') barUnacceptable++
  }
  const totalForBar = (barStandard + barFallback + barUnacceptable) || 1

  /** Character-level inline diff */
  type DiffPart = { t: 'eq' | 'del' | 'ins'; s: string }
  const computeDiff = (oldTxt: string, newTxt: string): DiffPart[] => {
    if (!oldTxt && !newTxt) return []
    if (!oldTxt) return [{ t: 'ins', s: newTxt }]
    if (!newTxt) return [{ t: 'del', s: oldTxt }]
    let i = 0
    while (i < oldTxt.length && i < newTxt.length && oldTxt[i] === newTxt[i]) i++
    let j = 0
    while (j < oldTxt.length - i && j < newTxt.length - i &&
           oldTxt[oldTxt.length - 1 - j] === newTxt[newTxt.length - 1 - j]) j++
    const parts: DiffPart[] = []
    if (i > 0) parts.push({ t: 'eq', s: oldTxt.slice(0, i) })
    const om = oldTxt.slice(i, j > 0 ? oldTxt.length - j : undefined)
    const nm = newTxt.slice(i, j > 0 ? newTxt.length - j : undefined)
    if (om) parts.push({ t: 'del', s: om })
    if (nm) parts.push({ t: 'ins', s: nm })
    if (j > 0) parts.push({ t: 'eq', s: oldTxt.slice(oldTxt.length - j) })
    return parts
  }

  const renderPreview = (occPhrase: string, occCtx: string, optText: string) => {
    const ctx = occCtx || occPhrase
    const idx = ctx.toLowerCase().indexOf(occPhrase.toLowerCase())
    const before = idx !== -1 ? ctx.slice(0, idx) : ''
    const after = idx !== -1 ? ctx.slice(idx + occPhrase.length) : ''
    const diff = computeDiff(occPhrase, optText)
    return (
      <span>
        {before}
        {diff.map((p, pi) =>
          p.t === 'eq' ? <span key={pi}>{p.s}</span> :
          p.t === 'del' ? <del key={pi} style={{ color: '#dc2626', textDecorationColor: '#dc2626' }}>{p.s}</del> :
          <span key={pi} style={{ color: '#2563eb' }}>{p.s}</span>
        )}
        {after.length > 120 ? after.slice(0, 120) + '…' : after}
      </span>
    )
  }

  return (
    <div
      className="h-full flex flex-col animate-slideInRight"
      style={{
        backgroundColor: 'var(--color-bg-primary)',
        borderColor: 'var(--color-border)',
        boxShadow: '0 0 0 1px var(--color-border)',
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between p-4 border-b shrink-0"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <div>
          <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
            Результаты проверки
          </h2>
          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            {effectivePlaybookName}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {onRerun && (
            <button
              onClick={onRerun}
              className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
              title="Повторить проверку"
            >
              <RefreshCw className="w-4 h-4" style={{ color: 'var(--color-text-secondary)' }} />
            </button>
          )}
          {onDownloadReport && (
            <button
              onClick={onDownloadReport}
              className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
              title="Скачать отчёт"
            >
              <Download className="w-4 h-4" style={{ color: 'var(--color-text-secondary)' }} />
            </button>
          )}
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <X className="w-5 h-5" style={{ color: 'var(--color-text-secondary)' }} />
          </button>
        </div>
      </div>

      {/* Score Section */}
      {result && (
        <div className="p-4 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>
              Соответствие
            </span>
          </div>
          
          {/* Многосегментная линия соответствия: зелёный / жёлтый / красный по вхождениям */}
          <div className="h-2 rounded-full bg-gray-200 overflow-hidden flex">
            {barStandard > 0 && (
              <div
                style={{
                  width: `${(barStandard / totalForBar) * 100}%`,
                  backgroundColor: '#22c55e',
                  transition: 'width 0.5s',
                }}
              />
            )}
            {barFallback > 0 && (
              <div
                style={{
                  width: `${(barFallback / totalForBar) * 100}%`,
                  backgroundColor: '#facc15',
                  transition: 'width 0.5s',
                }}
              />
            )}
            {barUnacceptable > 0 && (
              <div
                style={{
                  width: `${(barUnacceptable / totalForBar) * 100}%`,
                  backgroundColor: '#ef4444',
                  transition: 'width 0.5s',
                }}
              />
            )}
          </div>
        </div>
      )}

      {/* Summary */}
      {result?.summary && (
        <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex items-start gap-2">
            <Lightbulb className="w-4 h-4 mt-0.5 shrink-0" style={{ color: 'var(--color-accent)' }} />
            <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              {result.summary}
            </p>
          </div>
        </div>
      )}

      {/* Группы правил и детальный просмотр правила */}
      <div className="flex-1 overflow-y-auto">
        {!result ? (
          <div className="h-full flex flex-col items-center justify-center px-4 text-center">
            {isChecking ? (
              <>
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mb-3" />
                <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  Идёт проверка документа по playbook…
                </p>
              </>
            ) : errorMessage ? (
              <>
                <FileText className="w-10 h-10 mx-auto mb-3" style={{ color: 'var(--color-text-tertiary)' }} />
                <p className="text-sm mb-3" style={{ color: 'var(--color-text-secondary)' }}>
                  Не удалось выполнить проверку.
                </p>
                <p className="text-xs mb-4 max-w-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                  {errorMessage}
                </p>
                {(onRerun || onSelectPlaybook) && (
                  <button
                    onClick={onRerun || onSelectPlaybook}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white transition-colors hover:opacity-90"
                    style={{ backgroundColor: 'var(--color-accent, #6366f1)' }}
                  >
                    <RefreshCw className="w-3 h-3" />
                    Повторить
                  </button>
                )}
              </>
            ) : (
              <>
                <FileText className="w-10 h-10 mx-auto mb-3" style={{ color: 'var(--color-text-tertiary)' }} />
                <p className="text-sm mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                  {selectedPlaybookName
                    ? `Запустите проверку по playbook «${selectedPlaybookName}».`
                    : 'Выберите playbook, чтобы проверить документ.'}
                </p>
                {onSelectPlaybook && (
                  <button
                    onClick={onSelectPlaybook}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors hover:bg-gray-50"
                    style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                  >
                    <FileText className="w-3 h-3" />
                    Выбрать playbook
                  </button>
                )}
              </>
            )}
          </div>
        ) : (
          /* Accordion: groups → rules expand inline */
          <>
            {violations.length === 0 && warnings.length === 0 && passed.length === 0 ? (
              <div className="text-center py-12">
                <FileText className="w-10 h-10 mx-auto mb-3" style={{ color: 'var(--color-text-tertiary)' }} />
                <p style={{ color: 'var(--color-text-secondary)' }}>Нет результатов для отображения</p>
              </div>
            ) : (
              <div>
                {[
                  { id: 'needs_review', title: 'Требует проверки', dotClass: 'bg-yellow-400', rules: warnings },
                  { id: 'not_acceptable', title: 'Нарушения', dotClass: 'bg-red-500', rules: violations },
                  { id: 'acceptable', title: 'Приемлемо', dotClass: 'bg-green-500', rules: passed },
                ].map(group => {
                  if (group.rules.length === 0) return null
                  const groupOpen = expandedGroups.has(group.id)
                  return (
                    <div key={group.id} className="border-b" style={{ borderColor: 'var(--color-border)' }}>
                      {/* Group header */}
                      <button
                        onClick={() => setExpandedGroups(prev => {
                          const next = new Set(prev)
                          if (next.has(group.id)) next.delete(group.id)
                          else next.add(group.id)
                          return next
                        })}
                        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50"
                      >
                        <div className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${group.dotClass}`} />
                          <span className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                            {group.title}
                          </span>
                          <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                            {group.rules.length} правил
                          </span>
                        </div>
                        {groupOpen
                          ? <ChevronDown className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
                          : <ChevronRight className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />}
                      </button>

                      {groupOpen && (
                        <div>
                          {group.rules.map(rule => {
                            const ruleOpen = expandedRuleId === rule.rule_id
                            const ruleOccs = rule.occurrences && rule.occurrences.length > 0
                              ? rule.occurrences
                              : rule.found_text
                                ? [{ type: 'standard', phrase: rule.found_text, char_start: 0, char_end: 0, context: '' }]
                                : []
                            const ruleSuggestedOptions = rule.suggested_options && rule.suggested_options.length > 0
                              ? rule.suggested_options
                              : (rule.suggestion || rule.suggested_fix)
                                ? [{ label: 'Предлагаемая правка', type: 'standard', text: rule.suggestion || rule.suggested_fix || '' }]
                                : []

                            return (
                              <div key={rule.rule_id} className="border-t" style={{ borderColor: 'var(--color-border)' }}>
                                {/* Rule row — click to expand inline */}
                                <button
                                  onClick={() => setExpandedRuleId(ruleOpen ? null : rule.rule_id)}
                                  className="w-full flex items-start gap-3 px-4 py-3 text-left hover:bg-gray-50/70 transition-colors"
                                >
                                  <div className="flex-1 min-w-0">
                                    <span className="font-medium text-sm" style={{ color: 'var(--color-text-primary)' }}>
                                      {rule.rule_name}
                                    </span>
                                    {rule.issue_description && rule.status !== 'passed' && !ruleOpen && (
                                      <p className="text-xs mt-0.5 line-clamp-2" style={{ color: 'var(--color-text-secondary)' }}>
                                        {rule.issue_description}
                                      </p>
                                    )}
                                  </div>
                                  {ruleOpen
                                    ? <ChevronDown className="w-4 h-4 shrink-0 mt-0.5" style={{ color: 'var(--color-text-tertiary)' }} />
                                    : <ChevronRight className="w-4 h-4 shrink-0 mt-0.5" style={{ color: 'var(--color-text-tertiary)' }} />}
                                </button>

                                {/* Inline expanded detail */}
                                {ruleOpen && (
                                  <div className="border-t" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary, #fafafa)' }}>

                                    {/* AI summary */}
                                    {(rule.reasoning || rule.issue_description) && (
                                      <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
                                        <p className="text-xs font-semibold mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
                                          Анализ системы
                                        </p>
                                        <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                                          {rule.reasoning || rule.issue_description}
                                        </p>
                                      </div>
                                    )}

                                    {/* Lawyer guidance */}
                                    {rule.guidance && (
                                      <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
                                        <p className="text-xs font-semibold mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
                                          Руководство юриста
                                        </p>
                                        <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                                          {rule.guidance}
                                        </p>
                                      </div>
                                    )}

                                    {/* Occurrences */}
                                    {ruleOccs.length > 0 ? ruleOccs.map((occ, occIdx) => {
                                      const occOptions = occ.type === 'standard' ? [] : ruleSuggestedOptions
                                      const occApplyPrefix = `${rule.rule_id}_${occIdx}`
                                      const anyApplied = occOptions.some((_, oi) => appliedRules.has(`${occApplyPrefix}_${oi}`))
                                      const nthOcc = ruleOccs.slice(0, occIdx).filter(o => o.phrase === occ.phrase).length
                                      const ctxDisplay = (occ.context || occ.phrase).slice(0, 280) + ((occ.context || occ.phrase).length > 280 ? '…' : '')

                                      return (
                                        <div key={occIdx} className="border-b" style={{ borderColor: 'var(--color-border)' }}>
                                          {ruleOccs.length > 1 && (
                                            <p className="px-4 pt-3 text-xs font-semibold" style={{ color: 'var(--color-text-tertiary)' }}>
                                              Вхождение #{occIdx + 1}
                                            </p>
                                          )}
                                          <div className="px-4 pt-3 pb-2">
                                            <p className="text-xs font-semibold mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>
                                              Текст для проверки
                                            </p>
                                            <div className="rounded-lg px-3 py-2 text-sm leading-relaxed"
                                              style={{ backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-primary)', border: '1px solid var(--color-border)' }}>
                                              {ctxDisplay}
                                            </div>
                                            {onScrollToText && occ.phrase && (
                                              <button
                                                onClick={() => {
                                                  const found = onScrollToText(occ.phrase, nthOcc)
                                                  if (!found) toast.warning('Текст не найден в документе')
                                                }}
                                                className="flex items-center gap-1 text-xs mt-1.5 hover:opacity-70 transition-colors"
                                                style={{ color: 'var(--color-text-tertiary)' }}
                                              >
                                                <Eye className="w-3 h-3" />
                                                Перейти к тексту
                                              </button>
                                            )}
                                          </div>

                                          {occ.type === 'standard' && (
                                            <div className="px-4 pb-3 flex items-center gap-1.5 text-xs" style={{ color: '#16a34a' }}>
                                              <Check className="w-3.5 h-3.5" />
                                              Соответствует стандарту
                                            </div>
                                          )}

                                          {occOptions.map((opt, optIdx) => {
                                            const applyKey = `${occApplyPrefix}_${optIdx}`
                                            const isApplied = appliedRules.has(applyKey)
                                            const otherApplied = anyApplied && !isApplied
                                            const optLabel = opt.label || (opt.type === 'standard' ? 'Стандартная позиция' : `Запасной вариант ${optIdx + 1}`)
                                            return (
                                              <div key={optIdx} className="px-4 py-3 border-t" style={{ borderColor: 'var(--color-border)' }}>
                                                <p className="text-xs font-semibold mb-0.5" style={{ color: 'var(--color-text-primary)' }}>
                                                  {optLabel}
                                                </p>
                                                {otherApplied && (
                                                  <p className="text-xs italic mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
                                                    Другой вариант уже применён
                                                  </p>
                                                )}
                                                <div className="rounded-lg px-3 py-2 text-sm leading-relaxed mb-2 mt-1"
                                                  style={{ backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-primary)', border: '1px solid var(--color-border)' }}>
                                                  {renderPreview(occ.phrase, occ.context || '', opt.text)}
                                                </div>
                                                <div className="flex justify-end">
                                                  {isApplied ? (
                                                    <span className="flex items-center gap-1 text-xs font-medium" style={{ color: '#16a34a' }}>
                                                      <Check className="w-3 h-3" /> Применено
                                                    </span>
                                                  ) : onApplyFix && occ.phrase && opt.text ? (
                                                    <button
                                                      onClick={() => {
                                                        const success = onApplyFix(occ.phrase, opt.text)
                                                        if (success) {
                                                          setAppliedRules(prev => new Set(prev).add(applyKey))
                                                          toast.success('Правка применена')
                                                        } else {
                                                          toast.error('Не удалось найти текст')
                                                        }
                                                      }}
                                                      className="text-xs font-semibold px-3 py-1 rounded-md hover:opacity-80 transition-colors"
                                                      style={{ backgroundColor: 'var(--color-accent, #6366f1)', color: '#fff' }}
                                                    >
                                                      Применить
                                                    </button>
                                                  ) : null}
                                                </div>
                                              </div>
                                            )
                                          })}
                                        </div>
                                      )
                                    }) : (
                                      <div className="px-4 py-3">
                                        <p className="text-xs font-semibold mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>
                                          Текст для проверки
                                        </p>
                                        <div className="rounded-lg px-3 py-2 text-xs italic"
                                          style={{ backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>
                                          {rule.issue_description || 'Пункт не найден в документе.'}
                                        </div>
                                        {ruleSuggestedOptions.map((opt, optIdx) => (
                                          <div key={optIdx} className="pt-3 mt-3 border-t" style={{ borderColor: 'var(--color-border)' }}>
                                            <p className="text-xs font-semibold mb-1" style={{ color: 'var(--color-text-primary)' }}>
                                              {opt.label || (opt.type === 'standard' ? 'Стандартная позиция' : `Запасной вариант ${optIdx + 1}`)}
                                            </p>
                                            <div className="rounded-lg px-3 py-2 text-sm mt-1"
                                              style={{ backgroundColor: 'var(--color-bg-primary)', color: '#2563eb', border: '1px solid var(--color-border)' }}>
                                              {opt.text.length > 300 ? opt.text.slice(0, 300) + '…' : opt.text}
                                            </div>
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </>
        )}
      </div>

      {/* Recommendations */}
      {result?.recommendations && result.recommendations.length > 0 && (
        <div className="p-4 border-t shrink-0" style={{ borderColor: 'var(--color-border)' }}>
          <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
            Общие рекомендации
          </h3>
          <ul className="space-y-1.5">
            {result.recommendations.slice(0, 3).map((rec, idx) => (
              <li key={idx} className="flex items-start gap-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                <span className="text-blue-500">•</span>
                {rec}
              </li>
            ))}
          </ul>
        </div>
      )}

      <style>{`
        @keyframes slideInRight {
          from {
            transform: translateX(100%);
            opacity: 0;
          }
          to {
            transform: translateX(0);
            opacity: 1;
          }
        }
        .animate-slideInRight {
          animation: slideInRight 0.3s ease-out;
        }
      `}</style>
    </div>
  )
}

export default PlaybookResultsPanel

