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
  rule_standard_phrases?: string[]
  rule_fallback_phrases?: string[]
  rule_unacceptable_phrases?: string[]
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
  const [appliedRules, setAppliedRules] = useState<Set<string>>(new Set())
  const [selectedRule, setSelectedRule] = useState<RuleResult | null>(null)
  const [fullRuleOpen, setFullRuleOpen] = useState(false)

  const openRule = (rule: RuleResult) => {
    setSelectedRule(rule)
    setFullRuleOpen(false)
  }

  const effectivePlaybookName =
    result?.playbook_name ||
    selectedPlaybookName ||
    'Проверка по playbook'

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

  const renderPreview = (occPhrase: string, occCtx: string, optText: string, delColor = '#dc2626') => {
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
          p.t === 'del' ? <del key={pi} style={{ color: delColor, textDecorationColor: delColor }}>{p.s}</del> :
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
        ) : selectedRule ? (
          /* Rule detail panel */
          (() => {
            const rule = selectedRule
            const ruleOccs = rule.occurrences && rule.occurrences.length > 0
              ? rule.occurrences
              : rule.found_text
                ? (() => {
                    // When found_text is the entire clause (LLM path), try to extract
                    // the specific fallback/standard phrase from it for a useful diff
                    const ft = rule.found_text
                    if (ft.length > 200) {
                      const fbPhrasesList = rule.rule_fallback_phrases || []
                      const stdPhrasesList = rule.rule_standard_phrases || []
                      const unacPhrasesList = rule.rule_unacceptable_phrases || []
                      const allPhrases: Array<{ phrase: string; type: string }> = [
                        ...unacPhrasesList.map(p => ({ phrase: p, type: 'unacceptable' })),
                        ...fbPhrasesList.map(p => ({ phrase: p, type: 'fallback' })),
                        ...stdPhrasesList.map(p => ({ phrase: p, type: 'standard' })),
                      ]
                      for (const { phrase, type } of allPhrases) {
                        if (!phrase) continue
                        const idx = ft.toLowerCase().indexOf(phrase.toLowerCase())
                        if (idx !== -1) {
                          const ctxStart = Math.max(0, idx - 80)
                          const ctxEnd = Math.min(ft.length, idx + phrase.length + 80)
                          return [{ type, phrase: ft.slice(idx, idx + phrase.length), char_start: idx, char_end: idx + phrase.length, context: ft.slice(ctxStart, ctxEnd) }]
                        }
                      }
                    }
                    return [{ type: rule.status === 'passed' ? 'standard' : 'unacceptable', phrase: ft, char_start: 0, char_end: 0, context: '' }]
                  })()
                : []
            const ruleSuggestedOptions = rule.suggested_options && rule.suggested_options.length > 0
              ? rule.suggested_options
              : (rule.suggestion || rule.suggested_fix)
                ? [{ label: 'Предлагаемая правка', type: 'standard', text: rule.suggestion || rule.suggested_fix || '' }]
                : []
            const stdPhrases = rule.rule_standard_phrases || []
            const fbPhrases = rule.rule_fallback_phrases || []
            const unacPhrases = rule.rule_unacceptable_phrases || []

            return (
              <div className="flex flex-col h-full">
                {/* Back button */}
                <button
                  onClick={() => { setSelectedRule(null); setFullRuleOpen(false) }}
                  className="flex items-center gap-1.5 px-4 py-3 text-sm border-b hover:bg-gray-50 transition-colors shrink-0"
                  style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}
                >
                  <ChevronRight className="w-4 h-4 rotate-180" />
                  Назад
                </button>

                <div className="flex-1 overflow-y-auto">
                  {/* Rule name */}
                  <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
                    <p className="font-semibold text-sm" style={{ color: 'var(--color-text-primary)' }}>{rule.rule_name}</p>
                  </div>

                  {/* AI analysis */}
                  {(rule.reasoning || rule.issue_description) && (
                    <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
                      <p className="text-xs font-semibold mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Анализ системы</p>
                      <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                        {rule.reasoning || rule.issue_description}
                      </p>
                    </div>
                  )}

                  {/* Full rule phrases — collapsible */}
                  {(stdPhrases.length > 0 || fbPhrases.length > 0 || unacPhrases.length > 0) && (
                    <div className="border-b" style={{ borderColor: 'var(--color-border)' }}>
                      <button
                        onClick={() => setFullRuleOpen(prev => !prev)}
                        className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors"
                      >
                        <p className="text-xs font-semibold" style={{ color: 'var(--color-text-secondary)' }}>Полное правило</p>
                        {fullRuleOpen
                          ? <ChevronDown className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
                          : <ChevronRight className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />}
                      </button>
                      {fullRuleOpen && (
                        <div className="px-4 pb-3 space-y-3">
                          {stdPhrases.map((phrase, i) => (
                            <div key={i}>
                              <p className="text-xs font-semibold mb-1" style={{ color: 'var(--color-text-secondary)' }}>Стандартная формулировка</p>
                              <div className="rounded-lg px-3 py-2 text-xs leading-relaxed"
                                style={{ backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-primary)', border: '1px solid var(--color-border)' }}>
                                {phrase}
                              </div>
                            </div>
                          ))}
                          {fbPhrases.map((phrase, i) => (
                            <div key={i}>
                              <p className="text-xs font-semibold mb-1" style={{ color: 'var(--color-text-secondary)' }}>Запасной вариант {fbPhrases.length > 1 ? i + 1 : ''}</p>
                              <div className="rounded-lg px-3 py-2 text-xs leading-relaxed"
                                style={{ backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-primary)', border: '1px solid var(--color-border)' }}>
                                {phrase}
                              </div>
                            </div>
                          ))}
                          {unacPhrases.map((phrase, i) => (
                            <div key={i}>
                              <p className="text-xs font-semibold mb-1" style={{ color: 'var(--color-text-secondary)' }}>Недопустимая формулировка</p>
                              <div className="rounded-lg px-3 py-2 text-xs leading-relaxed"
                                style={{ backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-primary)', border: '1px solid var(--color-border)' }}>
                                {phrase}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Lawyer guidance */}
                  {rule.guidance && (
                    <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
                      <p className="text-xs font-semibold mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Руководство юриста</p>
                      <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>{rule.guidance}</p>
                    </div>
                  )}

                  {/* Occurrences + fix options */}
                  {ruleOccs.length > 0 ? ruleOccs.map((occ, occIdx) => {
                    const baseOptions = (occ.type === 'standard' && rule.status === 'passed') ? [] : ruleSuggestedOptions
                    // Skip options that would replace the phrase with itself (no-op diff)
                    const occOptions = baseOptions.filter(opt =>
                      opt.text.toLowerCase().trim() !== occ.phrase.toLowerCase().trim()
                    )
                    const occApplyPrefix = `${rule.rule_id}_${occIdx}`
                    const anyApplied = occOptions.some((_, oi) => appliedRules.has(`${occApplyPrefix}_${oi}`))
                    const nthOcc = ruleOccs.slice(0, occIdx).filter(o => o.phrase === occ.phrase).length
                    const ctxDisplay = (occ.context || occ.phrase).slice(0, 280) + ((occ.context || occ.phrase).length > 280 ? '…' : '')
                    // Yellow for fallback occurrences, red for unacceptable
                    const delColor = occ.type === 'fallback' ? '#ca8a04' : '#dc2626'
                    return (
                      <div key={occIdx} className="border-b" style={{ borderColor: 'var(--color-border)' }}>
                        {ruleOccs.length > 1 && (
                          <p className="px-4 pt-3 text-xs font-semibold" style={{ color: 'var(--color-text-tertiary)' }}>Вхождение #{occIdx + 1}</p>
                        )}
                        <div className="px-4 pt-3 pb-2">
                          <p className="text-xs font-semibold mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>Текст для проверки</p>
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
                        {occ.type === 'standard' && rule.status === 'passed' && (
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
                              <p className="text-xs font-semibold mb-0.5" style={{ color: 'var(--color-text-primary)' }}>{optLabel}</p>
                              {otherApplied && (
                                <p className="text-xs italic mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Другой вариант уже применён</p>
                              )}
                              <div className="rounded-lg px-3 py-2 text-sm leading-relaxed mb-2 mt-1"
                                style={{ backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-primary)', border: '1px solid var(--color-border)' }}>
                                {renderPreview(occ.phrase, occ.context || '', opt.text, delColor)}
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
                      <p className="text-xs font-semibold mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>Текст для проверки</p>
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
              </div>
            )
          })()
        ) : (
          /* Group list */
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
                  return (
                    <div key={group.id} className="border-b" style={{ borderColor: 'var(--color-border)' }}>
                      {/* Group label (non-clickable) */}
                      <div className="flex items-center gap-2 px-4 py-2 border-b" style={{ borderColor: 'var(--color-border)' }}>
                        <span className={`w-2 h-2 rounded-full ${group.dotClass}`} />
                        <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-secondary)' }}>
                          {group.title}
                        </span>
                        <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                          {group.rules.length}
                        </span>
                      </div>
                      {/* Rules — always visible */}
                      <div>
                        {group.rules.map(rule => (
                          <div key={rule.rule_id} className="border-b" style={{ borderColor: 'var(--color-border)' }}>
                            <button
                              onClick={() => openRule(rule)}
                              className="w-full flex items-start gap-3 px-4 py-3 text-left hover:bg-gray-50/70 transition-colors"
                            >
                              <div className="flex-1 min-w-0">
                                <span className="font-medium text-sm" style={{ color: 'var(--color-text-primary)' }}>
                                  {rule.rule_name}
                                </span>
                                {rule.issue_description && rule.status !== 'passed' && (
                                  <p className="text-xs mt-0.5 line-clamp-2" style={{ color: 'var(--color-text-secondary)' }}>
                                    {rule.issue_description}
                                  </p>
                                )}
                              </div>
                              <ChevronRight className="w-4 h-4 shrink-0 mt-0.5" style={{ color: 'var(--color-text-tertiary)' }} />
                            </button>
                          </div>
                        ))}
                      </div>
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

