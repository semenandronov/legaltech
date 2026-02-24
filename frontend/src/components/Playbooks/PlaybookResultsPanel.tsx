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
  ExternalLink,
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
  citations?: string[]
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
  result: PlaybookResult
  onClose: () => void
  onNavigateToIssue?: (location: { start: number; end: number }) => void
  onScrollToText?: (text: string) => boolean
  onApplyFix?: (foundText: string, fixedText: string) => boolean
  onRerun?: () => void
  onDownloadReport?: () => void
}

export const PlaybookResultsPanel = ({
  result,
  onClose,
  onNavigateToIssue,
  onScrollToText,
  onApplyFix,
  onRerun,
  onDownloadReport
}: PlaybookResultsPanelProps) => {
  const [expandedRules, setExpandedRules] = useState<Set<string>>(new Set())
  const [activeFilter, setActiveFilter] = useState<'all' | 'violations' | 'warnings' | 'passed'>('all')
  const [appliedRules, setAppliedRules] = useState<Set<string>>(new Set())

  const toggleRule = (ruleId: string) => {
    setExpandedRules(prev => {
      const next = new Set(prev)
      if (next.has(ruleId)) {
        next.delete(ruleId)
      } else {
        next.add(ruleId)
      }
      return next
    })
  }

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

  const getScoreColor = (score: number) => {
    if (score >= 80) return 'text-green-600'
    if (score >= 50) return 'text-yellow-600'
    return 'text-red-600'
  }

  const getScoreGradient = (score: number) => {
    if (score >= 80) return 'from-green-500 to-emerald-500'
    if (score >= 50) return 'from-yellow-500 to-orange-500'
    return 'from-red-500 to-rose-500'
  }

  const filteredResults = result.results.filter(r => {
    switch (activeFilter) {
      case 'violations':
        return r.status === 'violation' || r.status === 'not_found' || r.status === 'error'
      case 'warnings':
        return r.status === 'warning'
      case 'passed':
        return r.status === 'passed'
      default:
        return true
    }
  })

  const violationsCount = result.results.filter(r => 
    r.status === 'violation' || r.status === 'not_found' || r.status === 'error'
  ).length
  const warningsCount = result.results.filter(r => r.status === 'warning').length
  const passedCount = result.results.filter(r => r.status === 'passed').length

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
            {result.playbook_name}
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
      <div className="p-4 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>
            Соответствие
          </span>
          <span className={`text-3xl font-bold ${getScoreColor(result.compliance_score)}`}>
            {result.compliance_score.toFixed(1)}%
          </span>
        </div>
        
        {/* Progress bar */}
        <div className="h-2 rounded-full bg-gray-200 overflow-hidden">
          <div
            className={`h-full rounded-full bg-gradient-to-r ${getScoreGradient(result.compliance_score)} transition-all duration-500`}
            style={{ width: `${result.compliance_score}%` }}
          />
        </div>

        {/* Stats — Harvey style */}
        <div className="grid grid-cols-4 gap-2 mt-4">
          <div className="text-center p-2 rounded-lg bg-green-50">
            <div className="text-lg font-bold text-green-600">{result.passed_rules}</div>
            <div className="text-xs text-gray-500">Приемлемо</div>
          </div>
          <div className="text-center p-2 rounded-lg bg-red-50">
            <div className="text-lg font-bold text-red-600">{result.red_line_violations}</div>
            <div className="text-xs text-gray-500">Red Line</div>
          </div>
          <div className="text-center p-2 rounded-lg bg-purple-50">
            <div className="text-lg font-bold text-purple-600">{result.no_go_violations}</div>
            <div className="text-xs text-gray-500">No-Go</div>
          </div>
          <div className="text-center p-2 rounded-lg bg-yellow-50">
            <div className="text-lg font-bold text-yellow-600">{result.fallback_issues}</div>
            <div className="text-xs text-gray-500">На проверке</div>
          </div>
        </div>
      </div>

      {/* Summary */}
      {result.summary && (
        <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex items-start gap-2">
            <Lightbulb className="w-4 h-4 mt-0.5 shrink-0" style={{ color: 'var(--color-accent)' }} />
            <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              {result.summary}
            </p>
          </div>
        </div>
      )}

      {/* Filters — Harvey classifications */}
      <div className="flex items-center gap-1.5 px-4 py-3 border-b flex-wrap" style={{ borderColor: 'var(--color-border)' }}>
        <button
          onClick={() => setActiveFilter('all')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            activeFilter === 'all' ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-100'
          }`}
          style={{ color: activeFilter === 'all' ? undefined : 'var(--color-text-secondary)' }}
        >
          Все правила ({result.results.length})
        </button>
        <button
          onClick={() => setActiveFilter('violations')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            activeFilter === 'violations' ? 'bg-red-100 text-red-700' : 'hover:bg-gray-100'
          }`}
          style={{ color: activeFilter === 'violations' ? undefined : 'var(--color-text-secondary)' }}
        >
          ❌ Неприемлемо ({violationsCount})
        </button>
        <button
          onClick={() => setActiveFilter('warnings')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            activeFilter === 'warnings' ? 'bg-yellow-100 text-yellow-700' : 'hover:bg-gray-100'
          }`}
          style={{ color: activeFilter === 'warnings' ? undefined : 'var(--color-text-secondary)' }}
        >
          🔍 Требует проверки ({warningsCount})
        </button>
        <button
          onClick={() => setActiveFilter('passed')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            activeFilter === 'passed' ? 'bg-green-100 text-green-700' : 'hover:bg-gray-100'
          }`}
          style={{ color: activeFilter === 'passed' ? undefined : 'var(--color-text-secondary)' }}
        >
          ✅ Приемлемо ({passedCount})
        </button>
      </div>

      {/* Results List */}
      <div className="flex-1 overflow-y-auto">
        {filteredResults.length === 0 ? (
          <div className="text-center py-12">
            <FileText className="w-10 h-10 mx-auto mb-3" style={{ color: 'var(--color-text-tertiary)' }} />
            <p style={{ color: 'var(--color-text-secondary)' }}>
              Нет результатов для отображения
            </p>
          </div>
        ) : (
          <div className="divide-y" style={{ borderColor: 'var(--color-border)' }}>
            {filteredResults.map((rule) => {
              const harvey = getHarveyClassification(rule)
              return (
              <div key={rule.rule_id} className="transition-colors hover:bg-gray-50/50">
                {/* Rule Header — Harvey style */}
                <button
                  onClick={() => toggleRule(rule.rule_id)}
                  className="w-full flex items-start gap-3 p-4 text-left"
                >
                  <div className="flex-1 min-w-0">
                    {/* Harvey classification badge */}
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
                    {expandedRules.has(rule.rule_id) ? (
                      <ChevronDown className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
                    ) : (
                      <ChevronRight className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
                    )}
                  </div>
                </button>

                {/* Expanded Details — Harvey layout */}
                {expandedRules.has(rule.rule_id) && (
                  <div className="px-4 pb-4 space-y-3" style={{ borderTop: `1px solid var(--color-border)`, paddingTop: '12px' }}>

                    {/* 1. AI Reasoning — most prominent */}
                    {rule.reasoning && (
                      <div className="p-3 rounded-lg" style={{ backgroundColor: 'var(--color-bg-secondary)' }}>
                        <h4 className="text-xs font-semibold mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>
                          📊 Обоснование AI
                        </h4>
                        <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-primary)' }}>
                          {rule.reasoning}
                        </p>
                      </div>
                    )}

                    {/* 2. Issue description (if different from reasoning) */}
                    {rule.issue_description && rule.issue_description !== rule.reasoning && (
                      <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                        {rule.issue_description}
                      </p>
                    )}

                    {/* 3. Предлагаемая правка (Harvey redline) */}
                    {rule.found_text && (rule.suggestion || rule.suggested_fix) && (
                      <div>
                        <h4 className="text-xs font-semibold mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                          🔄 Предлагаемая правка
                        </h4>
                        <div
                          className="p-3 rounded-lg text-sm leading-relaxed space-y-2"
                          style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)' }}
                        >
                          <div>
                            <span className="text-xs font-medium" style={{ color: '#dc2626' }}>Было:</span>
                            <p className="line-through text-red-500 mt-0.5">
                              {rule.found_text.length > 250 ? rule.found_text.substring(0, 250) + '…' : rule.found_text}
                            </p>
                          </div>
                          <div>
                            <span className="text-xs font-medium" style={{ color: '#2563eb' }}>Стало:</span>
                            <p className="mt-0.5" style={{ color: '#2563eb', textDecoration: 'underline' }}>
                              {(() => {
                                const fix = rule.suggestion || rule.suggested_fix || ''
                                return fix.length > 250 ? fix.substring(0, 250) + '…' : fix
                              })()}
                            </p>
                          </div>
                        </div>

                        {/* Action buttons */}
                        <div className="flex items-center gap-2 mt-2">
                          {(onScrollToText || (onNavigateToIssue && (rule.document_location || rule.location))) && (
                            <button
                              onClick={() => {
                                if (onScrollToText && rule.found_text) {
                                  const found = onScrollToText(rule.found_text)
                                  if (!found) toast.warning('Текст не найден в документе')
                                } else if (onNavigateToIssue && (rule.document_location || rule.location)) {
                                  onNavigateToIssue(
                                    rule.document_location ||
                                    { start: rule.location?.start || 0, end: rule.location?.end || 0 }
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

                          {onApplyFix && rule.found_text && (rule.suggestion || rule.suggested_fix) && (
                            appliedRules.has(rule.rule_id) ? (
                              <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-green-600 bg-green-50">
                                <CheckCheck className="w-3 h-3" />
                                Применено
                              </span>
                            ) : (
                              <button
                                onClick={() => {
                                  const fix = rule.suggestion || rule.suggested_fix || ''
                                  const success = onApplyFix(rule.found_text!, fix)
                                  if (success) {
                                    setAppliedRules(prev => new Set(prev).add(rule.rule_id))
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
                      </div>
                    )}

                    {/* 4. Recommendation (no found_text case) */}
                    {!rule.found_text && (rule.suggestion || rule.suggested_fix) && (
                      <div className="p-3 rounded-lg bg-blue-50 border border-blue-100">
                        <h4 className="text-xs font-semibold text-blue-700 mb-1">💡 Рекомендация</h4>
                        <p className="text-sm text-blue-800">
                          {rule.suggestion || rule.suggested_fix}
                        </p>
                      </div>
                    )}

                    {/* 5. Navigate when no found_text */}
                    {!rule.found_text && onNavigateToIssue && (rule.document_location || rule.location) && (
                      <button
                        onClick={() => onNavigateToIssue(
                          rule.document_location ||
                          { start: rule.location?.start || 0, end: rule.location?.end || 0 }
                        )}
                        className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700"
                      >
                        <Eye className="w-3 h-3" />
                        Перейти к месту в документе
                      </button>
                    )}

                    {/* Citations */}
                    {rule.citations && rule.citations.length > 0 && (
                      <div className="space-y-1">
                        {rule.citations.map((citation, idx) => (
                          <a
                            key={idx}
                            href={citation}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700"
                          >
                            <ExternalLink className="w-3 h-3" />
                            {citation}
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )})}
          </div>
        )}
      </div>

      {/* Recommendations */}
      {result.recommendations && result.recommendations.length > 0 && (
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

