/**
 * WorkflowPlanningPhase - Показ плана выполнения workflow перед запуском
 * 
 * Отображает план действий агента, позволяет пользователю
 * одобрить или отклонить план
 */
import { useState, useEffect } from 'react'
import {
  X,
  Play,
  RefreshCw,
  CheckCircle,
  Clock,
  AlertTriangle,
  ChevronRight,
  Loader2,
  Brain,
  Lightbulb,
  Zap,
  FileText,
  Table,
  Globe,
  BookOpen,
  Target,
  Database,
  FileSearch,
  Edit3
} from 'lucide-react'

interface PlanStep {
  id: string
  tool: string
  tool_display_name: string
  description: string
  estimated_time: string
  dependencies: string[]
  reasoning?: string
  parameters?: Record<string, any>
}

interface WorkflowPlan {
  id: string
  workflow_id: string
  workflow_name: string
  goal: string
  strategy: string
  steps: PlanStep[]
  total_estimated_time: string
  confidence_score: number
  created_at: string
}

interface WorkflowPlanningPhaseProps {
  plan: WorkflowPlan | null
  isLoading: boolean
  onApprove: () => void
  onRegenerate: () => void
  onEditStep?: (stepId: string, newParams: Record<string, any>) => void
  onClose: () => void
}

// Иконки для инструментов
const toolIcons: Record<string, React.ReactNode> = {
  'tabular_review': <Table className="w-5 h-5" />,
  'rag_search': <FileSearch className="w-5 h-5" />,
  'web_search': <Globe className="w-5 h-5" />,
  'playbook': <BookOpen className="w-5 h-5" />,
  'summarize': <FileText className="w-5 h-5" />,
  'extract_entities': <Target className="w-5 h-5" />,
  'document_compare': <Database className="w-5 h-5" />,
  'risk_analysis': <AlertTriangle className="w-5 h-5" />,
}

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

export const WorkflowPlanningPhase = ({
  plan,
  isLoading,
  onApprove,
  onRegenerate,
  onEditStep,
  onClose
}: WorkflowPlanningPhaseProps) => {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set())
  const [approving, setApproving] = useState(false)

  const toggleStep = (stepId: string) => {
    setExpandedSteps(prev => {
      const next = new Set(prev)
      if (next.has(stepId)) {
        next.delete(stepId)
      } else {
        next.add(stepId)
      }
      return next
    })
  }

  const handleApprove = async () => {
    setApproving(true)
    try {
      await onApprove()
    } finally {
      setApproving(false)
    }
  }

  const getConfidenceColor = (score: number) => {
    if (score >= 80) return 'text-green-600 bg-green-50'
    if (score >= 60) return 'text-yellow-600 bg-yellow-50'
    return 'text-red-600 bg-red-50'
  }

  if (isLoading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
        <div
          className="w-full max-w-2xl rounded-xl shadow-xl p-8"
          style={{ backgroundColor: 'var(--color-bg-primary)' }}
        >
          <div className="text-center">
            <div className="relative w-20 h-20 mx-auto mb-6">
              <div className="absolute inset-0 rounded-full border-4 border-gray-200"></div>
              <div className="absolute inset-0 rounded-full border-4 border-t-indigo-500 animate-spin"></div>
              <Brain className="absolute inset-0 m-auto w-8 h-8 text-indigo-500" />
            </div>
            <h2 className="text-xl font-semibold mb-2" style={{ color: 'var(--color-text-primary)' }}>
              AI планирует выполнение...
            </h2>
            <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              Анализ документов и создание оптимального плана действий
            </p>
            <div className="mt-6 space-y-2">
              <div className="flex items-center justify-center gap-2 text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                <Loader2 className="w-4 h-4 animate-spin" />
                Определение необходимых инструментов...
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (!plan) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div
        className="w-full max-w-3xl max-h-[90vh] rounded-xl shadow-xl flex flex-col overflow-hidden animate-scaleIn"
        style={{ backgroundColor: 'var(--color-bg-primary)' }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between p-5 border-b shrink-0"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div className="flex items-center gap-3">
            <div
              className="w-12 h-12 rounded-xl flex items-center justify-center"
              style={{ backgroundColor: 'rgba(99, 102, 241, 0.15)' }}
            >
              <Brain className="w-6 h-6" style={{ color: 'var(--color-accent)' }} />
            </div>
            <div>
              <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                План выполнения
              </h2>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {plan.workflow_name}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <X className="w-5 h-5" style={{ color: 'var(--color-text-secondary)' }} />
          </button>
        </div>

        {/* Goal & Strategy */}
        <div className="p-5 border-b space-y-4" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex items-start gap-3">
            <Target className="w-5 h-5 mt-0.5 shrink-0" style={{ color: 'var(--color-accent)' }} />
            <div>
              <h3 className="text-sm font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>
                Цель
              </h3>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {plan.goal}
              </p>
            </div>
          </div>

          <div className="flex items-start gap-3">
            <Lightbulb className="w-5 h-5 mt-0.5 shrink-0" style={{ color: '#f59e0b' }} />
            <div>
              <h3 className="text-sm font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>
                Стратегия
              </h3>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {plan.strategy}
              </p>
            </div>
          </div>

          {/* Stats */}
          <div className="flex items-center gap-6 pt-2">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
              <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                ~{plan.total_estimated_time}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Zap className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
              <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {plan.steps.length} шагов
              </span>
            </div>
            <div className={`flex items-center gap-2 px-2 py-1 rounded-full text-sm font-medium ${getConfidenceColor(plan.confidence_score)}`}>
              <CheckCircle className="w-4 h-4" />
              Уверенность: {plan.confidence_score}%
            </div>
          </div>
        </div>

        {/* Steps */}
        <div className="flex-1 overflow-y-auto p-5">
          <h3 className="text-sm font-medium mb-4" style={{ color: 'var(--color-text-primary)' }}>
            Шаги выполнения
          </h3>

          <div className="relative">
            {/* Timeline line */}
            <div
              className="absolute left-6 top-6 bottom-6 w-0.5"
              style={{ backgroundColor: 'var(--color-border)' }}
            />

            <div className="space-y-4">
              {plan.steps.map((step, index) => {
                const isExpanded = expandedSteps.has(step.id)
                const toolColor = toolColors[step.tool] || 'var(--color-accent)'

                return (
                  <div key={step.id} className="relative flex gap-4">
                    {/* Step number */}
                    <div
                      className="w-12 h-12 rounded-xl flex items-center justify-center shrink-0 relative z-10"
                      style={{ backgroundColor: `${toolColor}20`, color: toolColor }}
                    >
                      {toolIcons[step.tool] || <Zap className="w-5 h-5" />}
                    </div>

                    {/* Step content */}
                    <div
                      className="flex-1 rounded-lg border p-4 transition-colors hover:border-gray-300"
                      style={{
                        backgroundColor: 'var(--color-bg-secondary)',
                        borderColor: 'var(--color-border)'
                      }}
                    >
                      <button
                        onClick={() => toggleStep(step.id)}
                        className="w-full flex items-start justify-between text-left"
                      >
                        <div>
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-xs font-medium px-2 py-0.5 rounded-full"
                              style={{ backgroundColor: `${toolColor}20`, color: toolColor }}
                            >
                              Шаг {index + 1}
                            </span>
                            <span className="font-medium text-sm" style={{ color: 'var(--color-text-primary)' }}>
                              {step.tool_display_name}
                            </span>
                          </div>
                          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                            {step.description}
                          </p>
                        </div>
                        <div className="flex items-center gap-2 shrink-0 ml-4">
                          <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                            ~{step.estimated_time}
                          </span>
                          <ChevronRight
                            className={`w-4 h-4 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                            style={{ color: 'var(--color-text-tertiary)' }}
                          />
                        </div>
                      </button>

                      {/* Expanded content */}
                      {isExpanded && (
                        <div className="mt-4 pt-4 border-t space-y-3" style={{ borderColor: 'var(--color-border)' }}>
                          {step.reasoning && (
                            <div>
                              <h4 className="text-xs font-medium mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
                                Почему этот шаг?
                              </h4>
                              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                                {step.reasoning}
                              </p>
                            </div>
                          )}

                          {step.dependencies.length > 0 && (
                            <div>
                              <h4 className="text-xs font-medium mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
                                Зависит от
                              </h4>
                              <div className="flex items-center gap-2">
                                {step.dependencies.map(dep => (
                                  <span
                                    key={dep}
                                    className="text-xs px-2 py-1 rounded-full"
                                    style={{ backgroundColor: 'var(--color-bg-hover)', color: 'var(--color-text-secondary)' }}
                                  >
                                    Шаг {plan.steps.findIndex(s => s.id === dep) + 1}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}

                          {step.parameters && Object.keys(step.parameters).length > 0 && (
                            <div>
                              <div className="flex items-center justify-between mb-1">
                                <h4 className="text-xs font-medium" style={{ color: 'var(--color-text-tertiary)' }}>
                                  Параметры
                                </h4>
                                {onEditStep && (
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      onEditStep(step.id, step.parameters!)
                                    }}
                                    className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700"
                                  >
                                    <Edit3 className="w-3 h-3" />
                                    Изменить
                                  </button>
                                )}
                              </div>
                              <div className="p-2 rounded-lg font-mono text-xs" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
                                {Object.entries(step.parameters).map(([key, value]) => (
                                  <div key={key} className="flex items-start gap-2">
                                    <span style={{ color: 'var(--color-text-tertiary)' }}>{key}:</span>
                                    <span style={{ color: 'var(--color-text-primary)' }}>
                                      {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div
          className="flex items-center justify-between p-5 border-t shrink-0"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <button
            onClick={onRegenerate}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors hover:bg-gray-100"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <RefreshCw className="w-4 h-4" />
            Перегенерировать план
          </button>

          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm font-medium"
              style={{
                backgroundColor: 'var(--color-bg-secondary)',
                color: 'var(--color-text-primary)'
              }}
            >
              Отмена
            </button>
            <button
              onClick={handleApprove}
              disabled={approving}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
              style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
            >
              {approving ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Play className="w-4 h-4" />
              )}
              Одобрить и запустить
            </button>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes scaleIn {
          from {
            transform: scale(0.95);
            opacity: 0;
          }
          to {
            transform: scale(1);
            opacity: 1;
          }
        }
        .animate-scaleIn {
          animation: scaleIn 0.2s ease-out;
        }
      `}</style>
    </div>
  )
}

export default WorkflowPlanningPhase

