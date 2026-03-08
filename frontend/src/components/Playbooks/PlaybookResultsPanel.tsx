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
  CheckCheck,
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
  onNavigateToIssue,
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
  const [selectedRule, setSelectedRule] = useState<RuleResult | null>(null)
  const [selectedGroupTitle, setSelectedGroupTitle] = useState<string | null>(null)

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

  // Count occurrences by type across all rules for the compliance bar
  let barStandard = 0, barFallback = 0, barUnacceptable = 0
  for (const rule of result?.results || []) {
    if (rule.occurrences && rule.occurrences.length > 0) {
      for (const occ of rule.occurrences) {
        if (occ.type === 'standard') barStandard++
        else if (occ.type === 'fallback') barFallback++
        else if (occ.type === 'unacceptable') barUnacceptable++
      }
    } else {
      if (rule.status === 'passed') barStandard++
      else if (rule.status === 'warning') barFallback++
      else if (rule.status === 'violation' || rule.status === 'error') barUnacceptable++
    }
  }
  const totalForBar = (barStandard + barFallback + barUnacceptable) || 1

  const openRuleDetails = (rule: RuleResult, groupTitle: string) => {
    setSelectedRule(rule)
    setSelectedGroupTitle(groupTitle)
  }

  const closeRuleDetails = () => {
    setSelectedRule(null)
    setSelectedGroupTitle(null)
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
        ) : selectedRule ? (
          /* Детальное окно по одному правилу, как на экране Harvey */
          <div className="flex flex-col h-full">
            <div className="px-4 py-3 border-b flex items-center justify-between" style={{ borderColor: 'var(--color-border)' }}>
              <button
                onClick={closeRuleDetails}
                className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-800"
              >
                <ChevronLeft className="w-4 h-4" />
                Назад к списку
              </button>
              <div className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                {selectedGroupTitle || 'Результат правила'}
              </div>
            </div>

            <div className="p-4 space-y-4 overflow-y-auto">
              {/* Название правила и краткое описание */}
              <div>
                <h2 className="text-base font-semibold mb-1" style={{ color: 'var(--color-text-primary)' }}>
                  {selectedRule.rule_name}
                </h2>
                {selectedRule.issue_description && (
                  <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                    {selectedRule.issue_description}
                  </p>
                )}
              </div>

              {/* Summary / Резюме — почему это правило сработало */}
              {selectedRule.reasoning && (
                <div className="p-3 rounded-lg" style={{ backgroundColor: 'var(--color-bg-secondary)' }}>
                  <h3 className="text-xs font-semibold mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>
                    Резюме
                  </h3>
                  <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-primary)' }}>
                    {selectedRule.reasoning}
                  </p>
                </div>
              )}

              {/* Guidance — как трактовать правило (оригинальное правило и советы) */}
              {(selectedRule.guidance || selectedRule.suggestion || selectedRule.suggested_fix) && (
                <div className="p-3 rounded-lg border" style={{ borderColor: 'var(--color-border)' }}>
                  <h3 className="text-xs font-semibold mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>
                    Guidance
                  </h3>
                  <p className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                    {selectedRule.guidance || selectedRule.suggestion || selectedRule.suggested_fix}
                  </p>
                </div>
              )}

              {/* Вхождения в документе — единый раздел */}
              {(() => {
                const occs = selectedRule.occurrences && selectedRule.occurrences.length > 0
                  ? selectedRule.occurrences
                  : selectedRule.found_text
                    ? [{ type: 'standard', phrase: selectedRule.found_text, char_start: 0, char_end: 0, context: '' }]
                    : null
                if (!occs) return null

                const statusLabel = 'Текст для проверки и предлагаемые изменения'
                // Colors are always per-type — standard is always green regardless of overall status
                const typeColors: Record<string, string> = {
                  unacceptable: '#dc2626',
                  fallback: '#ca8a04',
                  standard: '#16a34a',
                }
                // Suggested fix options (only used for non-standard occurrences)
                const allSuggestedOptions = selectedRule.suggested_options && selectedRule.suggested_options.length > 0
                  ? selectedRule.suggested_options
                  : (selectedRule.suggestion || selectedRule.suggested_fix)
                    ? [{ label: 'Suggested fix', type: 'standard', text: selectedRule.suggestion || selectedRule.suggested_fix || '' }]
                    : []

                return (
                  <div className="space-y-3">
                    <h3 className="text-xs font-semibold" style={{ color: 'var(--color-text-secondary)' }}>
                      {statusLabel}{occs.length > 1 ? ` — ${occs.length} вхождения` : ''}
                    </h3>

                    {occs.map((occ, occIdx) => {
                      const color = typeColors[occ.type] || '#b45309'
                      // Standard occurrences are already correct — no fix needed
                      const occSuggestedOptions = occ.type === 'standard' ? [] : allSuggestedOptions
                      const phraseLabel = occ.type === 'standard'
                        ? 'Найденная формулировка (соответствует стандарту):'
                        : occ.type === 'fallback'
                          ? 'Найденная формулировка (запасной вариант):'
                          : 'Найденная формулировка (недопустимая):'
                      // Highlight the phrase within the context
                      const renderContext = (ctx: string, phrase: string) => {
                        const idx = ctx.toLowerCase().indexOf(phrase.toLowerCase())
                        if (idx === -1) return <>{ctx}</>
                        return <>
                          {ctx.slice(0, idx)}
                          <mark style={{ backgroundColor: `${color}22`, color, fontWeight: 600, borderRadius: 2, padding: '0 2px' }}>
                            {ctx.slice(idx, idx + phrase.length)}
                          </mark>
                          {ctx.slice(idx + phrase.length)}
                        </>
                      }
                      return (
                        <div key={occIdx} className="rounded-lg text-sm leading-relaxed overflow-hidden"
                          style={{ border: '1px solid var(--color-border)' }}>
                          {/* Header фразы */}
                          <div className="p-3" style={{ background: 'var(--color-bg-primary)' }}>
                            {occs.length > 1 && (
                              <div className="mb-1">
                                <span className="text-xs font-semibold" style={{ color }}>
                                  Вхождение #{occIdx + 1}
                                </span>
                              </div>
                            )}
                            <span className="text-xs font-medium" style={{ color }}>{phraseLabel}</span>
                            <p className="mt-0.5 font-mono text-sm" style={{ color }}>«{occ.phrase}»</p>
                            {occ.context && (
                              <p className="mt-2 text-xs leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                                {renderContext(occ.context, occ.phrase)}
                              </p>
                            )}
                            {/* Перейти к тексту */}
                            <div className="mt-2">
                              <button
                                onClick={() => {
                                  if (onScrollToText) {
                                    // Count how many times this same phrase appeared before
                                    // to navigate to the correct (nth) occurrence in the editor
                                    const nthOccurrence = occs.slice(0, occIdx).filter(o => o.phrase === occ.phrase).length
                                    const found = onScrollToText(occ.phrase, nthOccurrence)
                                    if (!found) toast.warning('Текст не найден в документе')
                                  } else if (onNavigateToIssue && occIdx === 0 && (selectedRule.document_location || selectedRule.location)) {
                                    onNavigateToIssue(
                                      selectedRule.document_location ||
                                      { start: selectedRule.location?.start || 0, end: selectedRule.location?.end || 0 }
                                    )
                                  }
                                }}
                                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors hover:bg-gray-50"
                                style={{ color: 'var(--color-text-secondary)', borderColor: 'var(--color-border)' }}
                              >
                                <Eye className="w-3 h-3" />
                                Перейти к тексту
                              </button>
                            </div>
                          </div>

                          {/* Варианты правок для этого вхождения (только для fallback/unacceptable) */}
                          {occSuggestedOptions.length > 0 && (
                            <div className="border-t space-y-2 p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-secondary, #f9fafb)' }}>
                              {occSuggestedOptions.map((opt, optIdx) => {
                                const applyKey = `${selectedRule.rule_id}_${occIdx}_${optIdx}`
                                return (
                                  <div key={optIdx} className="space-y-1">
                                    <span className="text-xs font-semibold" style={{ color: 'var(--color-text-secondary)' }}>
                                      {opt.label || (opt.type === 'fallback' ? `Fallback ${optIdx}` : 'Standard position')}
                                    </span>
                                    <p className="text-xs" style={{ color: '#2563eb' }}>
                                      {opt.text.length > 400 ? opt.text.substring(0, 400) + '…' : opt.text}
                                    </p>
                                    {onApplyFix && occ.phrase && opt.text && (
                                      appliedRules.has(applyKey) ? (
                                        <span className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-green-600 bg-green-50">
                                          <CheckCheck className="w-3 h-3" />
                                          Применено
                                        </span>
                                      ) : (
                                        <button
                                          onClick={() => {
                                            const success = onApplyFix(occ.phrase, opt.text)
                                            if (success) {
                                              setAppliedRules(prev => new Set(prev).add(applyKey))
                                              toast.success('Правка применена')
                                            } else {
                                              toast.error('Не удалось найти текст в документе')
                                            }
                                          }}
                                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white transition-colors hover:opacity-90"
                                          style={{ backgroundColor: 'var(--color-accent, #6366f1)' }}
                                        >
                                          Применить правку
                                        </button>
                                      )
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
                )
              })()}

              {/* Рекомендация без конкретного текста */}
              {!selectedRule.found_text && (selectedRule.suggestion || selectedRule.suggested_fix) && (
                <div className="p-3 rounded-lg bg-blue-50 border border-blue-100">
                  <h3 className="text-xs font-semibold text-blue-700 mb-1">Рекомендация</h3>
                  <p className="text-sm text-blue-800">
                    {selectedRule.suggestion || selectedRule.suggested_fix}
                  </p>
                </div>
              )}
            </div>
          </div>
        ) : (
          /* Сводный список групп и правил, как на первом экране Harvey */
          <>
            {violations.length === 0 && warnings.length === 0 && passed.length === 0 ? (
              <div className="text-center py-12">
                <FileText className="w-10 h-10 mx-auto mb-3" style={{ color: 'var(--color-text-tertiary)' }} />
                <p style={{ color: 'var(--color-text-secondary)' }}>
                  Нет результатов для отображения
                </p>
              </div>
            ) : (
              <div style={{ borderColor: 'var(--color-border)' }}>
                {[
                  { id: 'needs_review', title: 'Требует проверки', dotClass: 'bg-yellow-400', rules: warnings },
                  { id: 'not_acceptable', title: 'Нарушения', dotClass: 'bg-red-500', rules: violations },
                  { id: 'acceptable', title: 'Приемлемо', dotClass: 'bg-green-500', rules: passed },
                ].map(group => {
                  if (group.rules.length === 0) return null
                  const open = expandedGroups.has(group.id)
                  return (
                    <div key={group.id} className="border-b" style={{ borderColor: 'var(--color-border)' }}>
                      <button
                        onClick={() => {
                          setExpandedGroups(prev => {
                            const next = new Set(prev)
                            if (next.has(group.id)) next.delete(group.id)
                            else next.add(group.id)
                            return next
                          })
                        }}
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
                        {open ? (
                          <ChevronDown className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
                        ) : (
                          <ChevronRight className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
                        )}
                      </button>

                      {open && (
                        <div className="divide-y" style={{ borderColor: 'var(--color-border)' }}>
                          {group.rules.map((rule) => {
                            const harvey = getHarveyClassification(rule)
                            return (
                              <div key={rule.rule_id} className="transition-colors hover:bg-gray-50/50">
                                {/* Rule Header — краткий список как в Harvey */}
                                <button
                                  onClick={() => openRuleDetails(rule, group.title)}
                                  className="w-full flex items-start gap-3 p-4 text-left"
                                >
                                  <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                                      <span
                                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-semibold"
                                        style={{ color: harvey.color, backgroundColor: harvey.bg, border: `1px solid ${harvey.border}` }}
                                      >
                                        {harvey.icon} {harvey.label}
                                      </span>
                                      {getRuleTypeBadge(rule.rule_type)}
                                    </div>
                                    <span className="font-medium text-sm" style={{ color: 'var(--color-text-primary)' }}>
                                      {rule.rule_name}
                                    </span>
                                    {rule.issue_description && rule.status !== 'passed' && (
                                      <p className="text-xs mt-1 line-clamp-2" style={{ color: 'var(--color-text-secondary)' }}>
                                        {rule.issue_description}
                                      </p>
                                    )}
                                  </div>
                                  <div className="shrink-0 mt-1">
                                    <ChevronRight className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
                                  </div>
                                </button>
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

