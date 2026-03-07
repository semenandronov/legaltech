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
  onScrollToText?: (text: string) => boolean
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
    return { label: 'Неприемлемо', icon: '❌', color: '#dc2626', bg: 'rgba(220, 38, 38, 0.08)', border: 'rgba(220, 38, 38, 0.2)' }
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
  const totalForBar = (result?.results || []).length || 1

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
          
          {/* Многосегментная линия соответствия: зелёный / жёлтый / красный */}
          <div className="h-2 rounded-full bg-gray-200 overflow-hidden flex">
            {passed.length > 0 && (
              <div
                style={{
                  width: `${(passed.length / totalForBar) * 100}%`,
                  backgroundColor: '#22c55e',
                  transition: 'width 0.5s',
                }}
              />
            )}
            {warnings.length > 0 && (
              <div
                style={{
                  width: `${(warnings.length / totalForBar) * 100}%`,
                  backgroundColor: '#facc15',
                  transition: 'width 0.5s',
                }}
              />
            )}
            {violations.length > 0 && (
              <div
                style={{
                  width: `${(violations.length / totalForBar) * 100}%`,
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

              {/* Текст для проверки и предлагаемые изменения */}
              {selectedRule.found_text && (
                <div className="space-y-3">
                  <h3 className="text-xs font-semibold" style={{ color: 'var(--color-text-secondary)' }}>
                    Текст для проверки и предлагаемые изменения
                  </h3>

                  {/* Блок с исходным текстом */}
                  <div
                    className="p-3 rounded-lg text-sm leading-relaxed"
                    style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)' }}
                  >
                    <span className="text-xs font-medium" style={{ color: '#dc2626' }}>Найденная формулировка:</span>
                    <p className="mt-0.5 font-mono" style={{ color: '#dc2626' }}>
                      «{selectedRule.found_text}»
                    </p>
                    {/* Surrounding context for readability (from direct scan) */}
                    {selectedRule.occurrences?.[0]?.context && (
                      <p className="mt-2 text-xs leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                        <span className="font-medium">Контекст: </span>
                        {selectedRule.occurrences[0].context.length > 300
                          ? selectedRule.occurrences[0].context.substring(0, 300) + '…'
                          : selectedRule.occurrences[0].context}
                      </p>
                    )}
                  </div>

                  {/* Варианты правок (standard + fallbacks) — только если статус не passed */}
                  {selectedRule.status !== 'passed' && (selectedRule.suggested_options && selectedRule.suggested_options.length > 0
                    ? selectedRule.suggested_options
                    : (selectedRule.suggestion || selectedRule.suggested_fix)
                      ? [{ label: 'Suggested fix', type: 'standard', text: selectedRule.suggestion || selectedRule.suggested_fix || '' }]
                      : []
                  ).map((opt, idx) => (
                    <div
                      key={idx}
                      className="p-3 rounded-lg text-sm leading-relaxed space-y-2"
                      style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)' }}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold" style={{ color: 'var(--color-text-secondary)' }}>
                          {opt.label || (opt.type === 'fallback' ? `Fallback ${idx}` : 'Standard position')}
                        </span>
                      </div>
                      <div>
                        <span className="text-xs font-medium" style={{ color: '#2563eb' }}>Предлагаемый текст:</span>
                        <p className="mt-0.5" style={{ color: '#2563eb' }}>
                          {opt.text.length > 400 ? opt.text.substring(0, 400) + '…' : opt.text}
                        </p>
                      </div>

                      {onApplyFix && selectedRule.found_text && opt.text && (
                        <div className="mt-2 flex items-center gap-2">
                          {appliedRules.has(`${selectedRule.rule_id}_${idx}`) ? (
                            <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-green-600 bg-green-50">
                              <CheckCheck className="w-3 h-3" />
                              Применено
                            </span>
                          ) : (
                            <button
                              onClick={() => {
                                const success = onApplyFix(selectedRule.found_text!, opt.text)
                                if (success) {
                                  setAppliedRules(prev => new Set(prev).add(`${selectedRule.rule_id}_${idx}`))
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
                          )}
                        </div>
                      )}
                    </div>
                  ))}

                  <div className="flex items-center gap-2 mt-1">
                    {((onScrollToText && selectedRule.found_text) || (onNavigateToIssue && (selectedRule.document_location || selectedRule.location))) && (
                      <button
                        onClick={() => {
                          if (onScrollToText && selectedRule.found_text) {
                            const found = onScrollToText(selectedRule.found_text)
                            if (!found) toast.warning('Текст не найден в документе')
                          } else if (onNavigateToIssue && (selectedRule.document_location || selectedRule.location)) {
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
                    )}
                  </div>
                </div>
              )}

              {/* Все вхождения фраз в документе (из прямого сканирования) */}
              {selectedRule.occurrences && selectedRule.occurrences.length > 1 && (
                <div className="space-y-2">
                  <h3 className="text-xs font-semibold" style={{ color: 'var(--color-text-secondary)' }}>
                    Все вхождения в документе ({selectedRule.occurrences.length})
                  </h3>
                  {selectedRule.occurrences.map((occ, idx) => {
                    const typeColors: Record<string, { bg: string; border: string; label: string; labelColor: string }> = {
                      unacceptable: { bg: 'rgba(220,38,38,0.05)', border: 'rgba(220,38,38,0.2)', label: 'Недопустимая', labelColor: '#dc2626' },
                      fallback: { bg: 'rgba(202,138,4,0.05)', border: 'rgba(202,138,4,0.2)', label: 'Запасная', labelColor: '#ca8a04' },
                      standard: { bg: 'rgba(22,163,74,0.05)', border: 'rgba(22,163,74,0.2)', label: 'Стандартная', labelColor: '#16a34a' },
                    }
                    const tc = typeColors[occ.type] || typeColors.fallback
                    return (
                      <div
                        key={idx}
                        className="p-3 rounded-lg text-sm"
                        style={{ background: tc.bg, border: `1px solid ${tc.border}` }}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-semibold" style={{ color: tc.labelColor }}>
                            {tc.label} формулировка #{idx + 1}
                          </span>
                          <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                            символ {occ.char_start}
                          </span>
                        </div>
                        <p className="text-xs font-mono mb-1.5" style={{ color: tc.labelColor }}>
                          «{occ.phrase}»
                        </p>
                        <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                          {occ.context.length > 200 ? occ.context.substring(0, 200) + '…' : occ.context}
                        </p>
                        {onScrollToText && (
                          <button
                            onClick={() => {
                              const found = onScrollToText(occ.phrase)
                              if (!found) toast.warning('Текст не найден в документе')
                            }}
                            className="mt-2 flex items-center gap-1 text-xs hover:underline"
                            style={{ color: tc.labelColor }}
                          >
                            <Eye className="w-3 h-3" />
                            Перейти
                          </button>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}

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
                  { id: 'not_acceptable', title: 'Неприемлемо', dotClass: 'bg-red-500', rules: violations },
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

