/**
 * WorkflowResultsView - Панель просмотра результатов завершённого выполнения
 */
import { useState, useEffect } from 'react'
import {
  X,
  CheckCircle,
  XCircle,
  Clock,
  FileText,
  BarChart3,
  ChevronDown,
  ChevronRight,
  Loader2,
  MessageSquare,
  Download,
  RefreshCw,
  AlertTriangle,
  Zap,
  Table,
  FileSearch,
  Globe,
  BookOpen,
  Target,
  Database,
} from 'lucide-react'
import * as workflowsApi from '../../services/workflowsApi'
import type { WorkflowExecution, WorkflowExecutionStep } from '../../services/workflowsApi'

const toolColors: Record<string, string> = {
  'tabular_review': '#6366f1',
  'rag_search': '#8b5cf6',
  'web_search': '#06b6d4',
  'playbook': '#10b981',
  'summarize': '#f59e0b',
  'extract_entities': '#ec4899',
  'document_compare': '#3b82f6',
  'risk_analysis': '#ef4444',
}

const toolIcons: Record<string, React.ReactNode> = {
  'tabular_review': <Table className="w-4 h-4" />,
  'rag_search': <FileSearch className="w-4 h-4" />,
  'web_search': <Globe className="w-4 h-4" />,
  'playbook': <BookOpen className="w-4 h-4" />,
  'summarize': <FileText className="w-4 h-4" />,
  'extract_entities': <Target className="w-4 h-4" />,
  'document_compare': <Database className="w-4 h-4" />,
  'risk_analysis': <AlertTriangle className="w-4 h-4" />,
}

interface WorkflowResultsViewProps {
  executionId: string
  onClose: () => void
  onOpenInChat?: (executionId: string) => void
  onRerun?: (definitionId: string) => void
}

export const WorkflowResultsView = ({
  executionId,
  onClose,
  onOpenInChat,
  onRerun,
}: WorkflowResultsViewProps) => {
  const [execution, setExecution] = useState<WorkflowExecution | null>(null)
  const [steps, setSteps] = useState<WorkflowExecutionStep[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set())

  useEffect(() => {
    loadData()
  }, [executionId])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [execData, stepsData] = await Promise.all([
        workflowsApi.getExecution(executionId),
        workflowsApi.getExecutionSteps(executionId),
      ])
      setExecution(execData)
      setSteps(stepsData)
    } catch (e: any) {
      console.error('Failed to load execution:', e)
      setError(e.response?.data?.detail || 'Ошибка загрузки результатов')
    } finally {
      setLoading(false)
    }
  }

  const toggleStep = (stepId: string) => {
    setExpandedSteps(prev => {
      const next = new Set(prev)
      if (next.has(stepId)) next.delete(stepId)
      else next.add(stepId)
      return next
    })
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-4 h-4" style={{ color: '#22c55e' }} />
      case 'failed':
        return <XCircle className="w-4 h-4" style={{ color: '#ef4444' }} />
      case 'running':
        return <Loader2 className="w-4 h-4 animate-spin" style={{ color: 'var(--color-accent)' }} />
      case 'skipped':
      case 'cancelled':
        return <AlertTriangle className="w-4 h-4" style={{ color: '#f59e0b' }} />
      default:
        return <Clock className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
    }
  }

  const formatDuration = (seconds?: number) => {
    if (!seconds) return 'н/д'
    if (seconds < 60) return `${seconds} сек`
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return secs > 0 ? `${mins} мин ${secs} сек` : `${mins} мин`
  }

  return (
    <div
      className="fixed inset-y-0 right-0 z-40 w-[550px] border-l flex flex-col shadow-xl"
      style={{
        backgroundColor: 'var(--color-bg-primary)',
        borderColor: 'var(--color-border)',
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between p-5 border-b shrink-0"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-center gap-3 min-w-0">
          {execution && (
            <>
              {execution.status === 'completed' ? (
                <CheckCircle className="w-6 h-6 shrink-0" style={{ color: '#22c55e' }} />
              ) : execution.status === 'failed' ? (
                <XCircle className="w-6 h-6 shrink-0" style={{ color: '#ef4444' }} />
              ) : (
                <Loader2 className="w-6 h-6 animate-spin shrink-0" style={{ color: 'var(--color-accent)' }} />
              )}
            </>
          )}
          <div className="min-w-0">
            <h2 className="text-lg font-semibold truncate" style={{ color: 'var(--color-text-primary)' }}>
              {execution?.workflow_name || 'Результаты'}
            </h2>
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              {execution ? new Date(execution.started_at).toLocaleString('ru-RU') : ''}
            </p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 rounded-lg hover:bg-black/5 shrink-0"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {loading && (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin" style={{ color: 'var(--color-accent)' }} />
          </div>
        )}

        {error && (
          <div
            className="p-4 rounded-lg border"
            style={{ backgroundColor: '#fef2f2', borderColor: '#fecaca', color: '#dc2626' }}
          >
            {error}
          </div>
        )}

        {execution && !loading && (
          <>
            {/* Summary */}
            {execution.summary && (
              <div
                className="p-4 rounded-xl border"
                style={{
                  backgroundColor: 'var(--color-bg-secondary)',
                  borderColor: 'var(--color-border)',
                }}
              >
                <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  Итог
                </h3>
                <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                  {execution.summary}
                </p>
              </div>
            )}

            {/* Stats Grid */}
            <div className="grid grid-cols-2 gap-3">
              <StatCard
                icon={<Zap className="w-4 h-4" />}
                label="Шаги"
                value={`${execution.total_steps_completed} / ${steps.length || execution.total_steps_completed}`}
              />
              <StatCard
                icon={<FileText className="w-4 h-4" />}
                label="Документы"
                value={String(execution.documents_processed || 0)}
              />
              <StatCard
                icon={<Clock className="w-4 h-4" />}
                label="Время"
                value={execution.elapsed_time || 'н/д'}
              />
              <StatCard
                icon={<BarChart3 className="w-4 h-4" />}
                label="Токены"
                value={execution.total_tokens_used ? String(execution.total_tokens_used) : 'н/д'}
              />
            </div>

            {/* Steps Timeline */}
            {steps.length > 0 && (
              <div>
                <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-primary)' }}>
                  Шаги выполнения
                </h3>
                <div className="space-y-2">
                  {steps.map((step, idx) => {
                    const isExpanded = expandedSteps.has(step.id)
                    const color = toolColors[step.tool_name || ''] || 'var(--color-accent)'

                    return (
                      <div
                        key={step.id}
                        className="rounded-xl border overflow-hidden"
                        style={{
                          backgroundColor: 'var(--color-bg-secondary)',
                          borderColor: isExpanded ? color : 'var(--color-border)',
                        }}
                      >
                        {/* Step Header */}
                        <button
                          onClick={() => toggleStep(step.id)}
                          className="w-full flex items-center gap-3 p-3 text-left"
                        >
                          {/* Step number */}
                          <div
                            className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0"
                            style={{ backgroundColor: color }}
                          >
                            {idx + 1}
                          </div>

                          {/* Tool icon */}
                          <div
                            className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
                            style={{ backgroundColor: `${color}20`, color }}
                          >
                            {toolIcons[step.tool_name || ''] || <Zap className="w-4 h-4" />}
                          </div>

                          {/* Name */}
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium truncate" style={{ color: 'var(--color-text-primary)' }}>
                              {step.step_name}
                            </div>
                            {step.duration_seconds !== undefined && step.duration_seconds !== null && (
                              <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                                {formatDuration(step.duration_seconds)}
                              </div>
                            )}
                          </div>

                          {/* Status */}
                          {getStatusIcon(step.status)}

                          {/* Expand */}
                          {isExpanded ? (
                            <ChevronDown className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
                          ) : (
                            <ChevronRight className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
                          )}
                        </button>

                        {/* Expanded Content */}
                        {isExpanded && (
                          <div
                            className="px-4 pb-4 pt-0 space-y-3 border-t"
                            style={{ borderColor: 'var(--color-border)' }}
                          >
                            {step.description && (
                              <div className="pt-3">
                                <label className="text-xs font-medium" style={{ color: 'var(--color-text-tertiary)' }}>
                                  Описание
                                </label>
                                <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
                                  {step.description}
                                </p>
                              </div>
                            )}

                            {step.output_summary && (
                              <div>
                                <label className="text-xs font-medium" style={{ color: 'var(--color-text-tertiary)' }}>
                                  Результат
                                </label>
                                <p className="text-sm mt-1" style={{ color: 'var(--color-text-primary)' }}>
                                  {step.output_summary}
                                </p>
                              </div>
                            )}

                            {step.error && (
                              <div
                                className="p-3 rounded-lg text-sm"
                                style={{ backgroundColor: '#fef2f2', color: '#dc2626' }}
                              >
                                {step.error}
                              </div>
                            )}

                            {step.tool_params && Object.keys(step.tool_params).length > 0 && (
                              <div>
                                <label className="text-xs font-medium" style={{ color: 'var(--color-text-tertiary)' }}>
                                  Параметры
                                </label>
                                <div className="mt-1 space-y-1">
                                  {Object.entries(step.tool_params).map(([k, v]) => (
                                    <div key={k} className="flex gap-2 text-xs">
                                      <span className="font-mono" style={{ color: 'var(--color-text-secondary)' }}>{k}:</span>
                                      <span style={{ color: 'var(--color-text-primary)' }}>{String(v)}</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            <div className="flex gap-4 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                              {step.started_at && (
                                <span>Начало: {new Date(step.started_at).toLocaleTimeString('ru-RU')}</span>
                              )}
                              {step.completed_at && (
                                <span>Конец: {new Date(step.completed_at).toLocaleTimeString('ru-RU')}</span>
                              )}
                              {step.retry_count > 0 && (
                                <span>Повторов: {step.retry_count}</span>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Artifacts */}
            {execution.artifacts && (
              <ArtifactsSection artifacts={execution.artifacts} />
            )}

            {/* Error */}
            {execution.error_message && (
              <div
                className="p-4 rounded-xl border"
                style={{ backgroundColor: '#fef2f2', borderColor: '#fecaca' }}
              >
                <h3 className="text-sm font-medium mb-1" style={{ color: '#dc2626' }}>
                  Ошибка выполнения
                </h3>
                <p className="text-sm" style={{ color: '#b91c1c' }}>
                  {execution.error_message}
                </p>
              </div>
            )}
          </>
        )}
      </div>

      {/* Footer Actions */}
      {execution && !loading && (
        <div
          className="flex items-center justify-end gap-3 p-4 border-t shrink-0"
          style={{ borderColor: 'var(--color-border)' }}
        >
          {onRerun && execution.definition_id && (
            <button
              onClick={() => onRerun(execution.definition_id!)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm"
              style={{
                backgroundColor: 'var(--color-bg-secondary)',
                color: 'var(--color-text-primary)',
              }}
            >
              <RefreshCw className="w-4 h-4" />
              Перезапустить
            </button>
          )}
          {onOpenInChat && (
            <button
              onClick={() => onOpenInChat(executionId)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium"
              style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
            >
              <MessageSquare className="w-4 h-4" />
              Открыть в чате
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// Stat Card component
const StatCard = ({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: string
}) => (
  <div
    className="p-3 rounded-xl border"
    style={{
      backgroundColor: 'var(--color-bg-secondary)',
      borderColor: 'var(--color-border)',
    }}
  >
    <div className="flex items-center gap-2 mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
      {icon}
      <span className="text-xs">{label}</span>
    </div>
    <div className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
      {value}
    </div>
  </div>
)

// Artifacts Section
const ArtifactsSection = ({
  artifacts,
}: {
  artifacts: workflowsApi.WorkflowArtifacts
}) => {
  const hasArtifacts =
    artifacts.reports.length > 0 ||
    artifacts.tables.length > 0 ||
    artifacts.documents.length > 0 ||
    artifacts.checks.length > 0

  if (!hasArtifacts) return null

  return (
    <div>
      <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-primary)' }}>
        Артефакты
      </h3>
      <div className="space-y-2">
        {artifacts.reports.map(r => (
          <ArtifactItem key={r.id} icon={<BarChart3 className="w-4 h-4" />} name={r.name} type={r.type} />
        ))}
        {artifacts.tables.map(t => (
          <ArtifactItem key={t.id} icon={<Table className="w-4 h-4" />} name={t.name} type="table" />
        ))}
        {artifacts.documents.map(d => (
          <ArtifactItem key={d.id} icon={<FileText className="w-4 h-4" />} name={d.name} type="document" />
        ))}
        {artifacts.checks.map(c => (
          <ArtifactItem key={c.id} icon={<BookOpen className="w-4 h-4" />} name={`Check ${c.document_id}`} type="check" />
        ))}
      </div>
    </div>
  )
}

const ArtifactItem = ({
  icon,
  name,
  type,
}: {
  icon: React.ReactNode
  name: string
  type: string
}) => (
  <div
    className="flex items-center gap-3 p-2.5 rounded-lg border"
    style={{
      backgroundColor: 'var(--color-bg-secondary)',
      borderColor: 'var(--color-border)',
    }}
  >
    <div style={{ color: 'var(--color-accent)' }}>{icon}</div>
    <div className="flex-1 min-w-0">
      <div className="text-sm truncate" style={{ color: 'var(--color-text-primary)' }}>
        {name}
      </div>
      <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
        {type}
      </div>
    </div>
    <Download className="w-4 h-4 shrink-0" style={{ color: 'var(--color-text-tertiary)' }} />
  </div>
)
