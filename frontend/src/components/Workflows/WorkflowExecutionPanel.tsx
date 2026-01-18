/**
 * WorkflowExecutionPanel - Панель выполнения workflow в реальном времени
 * 
 * Показывает:
 * - Текущий статус выполнения
 * - Какие инструменты используются
 * - Прогресс каждого шага
 * - Результаты в реальном времени
 */
import { useState, useEffect, useRef } from 'react'
import {
  X,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  Loader2,
  Play,
  Pause,
  Square,
  ChevronDown,
  ChevronRight,
  Download,
  Zap,
  FileText,
  Table,
  Globe,
  BookOpen,
  Target,
  Database,
  FileSearch,
  Brain,
  MessageSquare
} from 'lucide-react'

interface ToolExecution {
  id: string
  tool_name: string
  tool_display_name: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  started_at?: string
  completed_at?: string
  progress?: number
  input_summary?: string
  output_summary?: string
  error?: string
  duration?: string
}

interface ExecutionStep {
  id: string
  step_number: number
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  started_at?: string
  completed_at?: string
  tools_used: ToolExecution[]
  result_preview?: string
  thinking?: string[]
}

interface WorkflowExecution {
  id: string
  workflow_id: string
  workflow_name: string
  status: 'planning' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled'
  progress: number
  current_step?: number
  total_steps: number
  steps: ExecutionStep[]
  started_at: string
  completed_at?: string
  elapsed_time?: string
  result_url?: string
  documents_processed: number
  total_documents: number
  ai_thoughts?: string[]
  error?: string
}

interface WorkflowExecutionPanelProps {
  execution: WorkflowExecution
  onClose: () => void
  onPause?: () => void
  onResume?: () => void
  onCancel?: () => void
  onDownloadResult?: () => void
}

// Иконки для инструментов
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

export const WorkflowExecutionPanel = ({
  execution,
  onClose,
  onPause,
  onResume,
  onCancel,
  onDownloadResult
}: WorkflowExecutionPanelProps) => {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set())
  const [showThoughts, setShowThoughts] = useState(false)
  const stepsEndRef = useRef<HTMLDivElement>(null)

  // Auto-expand current step
  useEffect(() => {
    if (execution.current_step !== undefined) {
      const currentStep = execution.steps[execution.current_step]
      if (currentStep) {
        setExpandedSteps(prev => {
          const next = new Set(prev)
          next.add(currentStep.id)
          return next
        })
      }
    }
  }, [execution.current_step])

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    stepsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [execution.steps])

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

  const getStatusIcon = (status: ExecutionStep['status']) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-5 h-5" style={{ color: '#22c55e' }} />
      case 'running':
        return <Loader2 className="w-5 h-5 animate-spin" style={{ color: '#6366f1' }} />
      case 'failed':
        return <XCircle className="w-5 h-5" style={{ color: '#ef4444' }} />
      case 'skipped':
        return <div className="w-5 h-5 rounded-full bg-gray-200" />
      default:
        return <div className="w-5 h-5 rounded-full border-2" style={{ borderColor: 'var(--color-border)' }} />
    }
  }

  const getOverallStatusInfo = () => {
    switch (execution.status) {
      case 'planning':
        return { label: 'Планирование', color: '#8b5cf6', icon: Brain }
      case 'running':
        return { label: 'Выполняется', color: '#6366f1', icon: Loader2 }
      case 'paused':
        return { label: 'Приостановлено', color: '#f59e0b', icon: Pause }
      case 'completed':
        return { label: 'Завершено', color: '#22c55e', icon: CheckCircle }
      case 'failed':
        return { label: 'Ошибка', color: '#ef4444', icon: XCircle }
      case 'cancelled':
        return { label: 'Отменено', color: '#6b7280', icon: Square }
      default:
        return { label: 'Неизвестно', color: '#6b7280', icon: Clock }
    }
  }

  const statusInfo = getOverallStatusInfo()
  const StatusIcon = statusInfo.icon
  const isRunning = execution.status === 'running' || execution.status === 'planning'

  return (
    <div
      className="fixed right-0 top-0 bottom-0 w-[550px] shadow-xl border-l flex flex-col z-40"
      style={{
        backgroundColor: 'var(--color-bg-primary)',
        borderColor: 'var(--color-border)'
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between p-4 border-b shrink-0"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-center gap-3">
          <StatusIcon
            className={`w-6 h-6 ${statusInfo.icon === Loader2 ? 'animate-spin' : ''}`}
            style={{ color: statusInfo.color }}
          />
          <div>
            <h2 className="font-semibold" style={{ color: 'var(--color-text-primary)' }}>
              {execution.workflow_name}
            </h2>
            <p className="text-sm" style={{ color: statusInfo.color }}>
              {statusInfo.label}
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

      {/* Progress Bar */}
      <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
            Прогресс
          </span>
          <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            {execution.progress}%
          </span>
        </div>
        <div className="h-2 rounded-full bg-gray-200 overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500 ease-out"
            style={{
              width: `${execution.progress}%`,
              backgroundColor: statusInfo.color
            }}
          />
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-2 p-4 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <div className="text-center p-2 rounded-lg" style={{ backgroundColor: 'var(--color-bg-secondary)' }}>
          <div className="text-lg font-bold" style={{ color: 'var(--color-accent)' }}>
            {execution.current_step !== undefined ? execution.current_step + 1 : 0}/{execution.total_steps}
          </div>
          <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Шаги</div>
        </div>
        <div className="text-center p-2 rounded-lg" style={{ backgroundColor: 'var(--color-bg-secondary)' }}>
          <div className="text-lg font-bold" style={{ color: 'var(--color-text-primary)' }}>
            {execution.documents_processed}/{execution.total_documents}
          </div>
          <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Документов</div>
        </div>
        <div className="text-center p-2 rounded-lg" style={{ backgroundColor: 'var(--color-bg-secondary)' }}>
          <div className="text-lg font-bold" style={{ color: 'var(--color-text-primary)' }}>
            {execution.elapsed_time || '0:00'}
          </div>
          <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Время</div>
        </div>
        <div className="text-center p-2 rounded-lg" style={{ backgroundColor: 'var(--color-bg-secondary)' }}>
          <div className="text-lg font-bold" style={{ color: 'var(--color-text-primary)' }}>
            {execution.steps.reduce((acc, s) => acc + s.tools_used.length, 0)}
          </div>
          <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Инструментов</div>
        </div>
      </div>

      {/* AI Thoughts (collapsible) */}
      {execution.ai_thoughts && execution.ai_thoughts.length > 0 && (
        <div className="border-b" style={{ borderColor: 'var(--color-border)' }}>
          <button
            onClick={() => setShowThoughts(!showThoughts)}
            className="w-full flex items-center justify-between p-3 hover:bg-gray-50 transition-colors"
          >
            <div className="flex items-center gap-2">
              <Brain className="w-4 h-4" style={{ color: '#8b5cf6' }} />
              <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                Мысли AI агента
              </span>
            </div>
            {showThoughts ? (
              <ChevronDown className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
            ) : (
              <ChevronRight className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
            )}
          </button>
          {showThoughts && (
            <div className="px-4 pb-3 space-y-2">
              {execution.ai_thoughts.map((thought, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-2 p-2 rounded-lg text-sm"
                  style={{ backgroundColor: 'rgba(139, 92, 246, 0.1)' }}
                >
                  <MessageSquare className="w-4 h-4 mt-0.5 shrink-0" style={{ color: '#8b5cf6' }} />
                  <p style={{ color: 'var(--color-text-secondary)' }}>{thought}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Steps Timeline */}
      <div className="flex-1 overflow-y-auto p-4">
        <h3 className="text-sm font-medium mb-4" style={{ color: 'var(--color-text-primary)' }}>
          Ход выполнения
        </h3>

        <div className="relative">
          {/* Timeline line */}
          <div
            className="absolute left-3 top-3 bottom-3 w-0.5"
            style={{ backgroundColor: 'var(--color-border)' }}
          />

          <div className="space-y-3">
            {execution.steps.map((step, index) => {
              const isExpanded = expandedSteps.has(step.id)
              const isCurrent = index === execution.current_step

              return (
                <div key={step.id} className="relative">
                  {/* Step header */}
                  <button
                    onClick={() => toggleStep(step.id)}
                    className={`w-full flex items-start gap-3 p-3 rounded-lg transition-colors text-left ${
                      isCurrent ? 'ring-2 ring-indigo-200' : ''
                    }`}
                    style={{
                      backgroundColor: isCurrent ? 'rgba(99, 102, 241, 0.05)' : 'var(--color-bg-secondary)'
                    }}
                  >
                    <div className="relative z-10 bg-white rounded-full p-0.5">
                      {getStatusIcon(step.status)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium text-sm" style={{ color: 'var(--color-text-primary)' }}>
                          Шаг {step.step_number}: {step.name}
                        </span>
                        {step.status === 'running' && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 animate-pulse">
                            В процессе
                          </span>
                        )}
                      </div>

                      {/* Active tools */}
                      {step.tools_used.length > 0 && (
                        <div className="flex items-center gap-1.5 flex-wrap mt-2">
                          {step.tools_used.map(tool => {
                            const color = toolColors[tool.tool_name] || 'var(--color-accent)'
                            return (
                              <div
                                key={tool.id}
                                className="flex items-center gap-1 px-2 py-1 rounded-full text-xs"
                                style={{
                                  backgroundColor: `${color}15`,
                                  color: color
                                }}
                                title={tool.tool_display_name}
                              >
                                {tool.status === 'running' ? (
                                  <Loader2 className="w-3 h-3 animate-spin" />
                                ) : tool.status === 'completed' ? (
                                  <CheckCircle className="w-3 h-3" />
                                ) : tool.status === 'failed' ? (
                                  <XCircle className="w-3 h-3" />
                                ) : (
                                  toolIcons[tool.tool_name] || <Zap className="w-3 h-3" />
                                )}
                                <span>{tool.tool_display_name}</span>
                                {tool.duration && (
                                  <span className="opacity-60">({tool.duration})</span>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                    <ChevronRight
                      className={`w-4 h-4 shrink-0 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                      style={{ color: 'var(--color-text-tertiary)' }}
                    />
                  </button>

                  {/* Expanded details */}
                  {isExpanded && (
                    <div className="ml-8 mt-2 space-y-3">
                      {/* Thinking */}
                      {step.thinking && step.thinking.length > 0 && (
                        <div className="p-3 rounded-lg" style={{ backgroundColor: 'rgba(139, 92, 246, 0.05)' }}>
                          <h4 className="text-xs font-medium mb-2" style={{ color: '#8b5cf6' }}>
                            🧠 Мышление агента
                          </h4>
                          <div className="space-y-1">
                            {step.thinking.map((thought, i) => (
                              <p key={i} className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                                {thought}
                              </p>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Tools details */}
                      {step.tools_used.map(tool => (
                        <div
                          key={tool.id}
                          className="p-3 rounded-lg border"
                          style={{
                            backgroundColor: 'var(--color-bg-primary)',
                            borderColor: 'var(--color-border)'
                          }}
                        >
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-2">
                              <div
                                className="w-6 h-6 rounded flex items-center justify-center"
                                style={{
                                  backgroundColor: `${toolColors[tool.tool_name] || 'var(--color-accent)'}20`,
                                  color: toolColors[tool.tool_name] || 'var(--color-accent)'
                                }}
                              >
                                {toolIcons[tool.tool_name] || <Zap className="w-3 h-3" />}
                              </div>
                              <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                                {tool.tool_display_name}
                              </span>
                            </div>
                            <div className="flex items-center gap-2">
                              {tool.status === 'running' && tool.progress !== undefined && (
                                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                                  {tool.progress}%
                                </span>
                              )}
                              {tool.duration && (
                                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                                  {tool.duration}
                                </span>
                              )}
                            </div>
                          </div>

                          {tool.input_summary && (
                            <div className="text-xs mb-2">
                              <span style={{ color: 'var(--color-text-tertiary)' }}>Вход: </span>
                              <span style={{ color: 'var(--color-text-secondary)' }}>{tool.input_summary}</span>
                            </div>
                          )}

                          {tool.output_summary && (
                            <div className="text-xs">
                              <span style={{ color: 'var(--color-text-tertiary)' }}>Результат: </span>
                              <span style={{ color: 'var(--color-text-secondary)' }}>{tool.output_summary}</span>
                            </div>
                          )}

                          {tool.error && (
                            <div className="mt-2 p-2 rounded bg-red-50 text-xs text-red-700">
                              {tool.error}
                            </div>
                          )}

                          {tool.status === 'running' && tool.progress !== undefined && (
                            <div className="mt-2 h-1 rounded-full bg-gray-200 overflow-hidden">
                              <div
                                className="h-full rounded-full transition-all duration-300"
                                style={{
                                  width: `${tool.progress}%`,
                                  backgroundColor: toolColors[tool.tool_name] || 'var(--color-accent)'
                                }}
                              />
                            </div>
                          )}
                        </div>
                      ))}

                      {/* Result preview */}
                      {step.result_preview && (
                        <div
                          className="p-3 rounded-lg border"
                          style={{
                            backgroundColor: 'var(--color-bg-secondary)',
                            borderColor: 'var(--color-border)'
                          }}
                        >
                          <h4 className="text-xs font-medium mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
                            Предварительный результат
                          </h4>
                          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                            {step.result_preview}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}

            <div ref={stepsEndRef} />
          </div>
        </div>

        {execution.steps.length === 0 && (
          <div className="text-center py-8">
            <Clock className="w-8 h-8 mx-auto mb-2" style={{ color: 'var(--color-text-tertiary)' }} />
            <p style={{ color: 'var(--color-text-secondary)' }}>
              Ожидание начала выполнения...
            </p>
          </div>
        )}
      </div>

      {/* Error */}
      {execution.error && (
        <div className="mx-4 mb-4 p-3 rounded-lg bg-red-50 border border-red-200">
          <div className="flex items-start gap-2">
            <XCircle className="w-5 h-5 text-red-500 shrink-0" />
            <div>
              <h4 className="text-sm font-medium text-red-700">Ошибка выполнения</h4>
              <p className="text-xs text-red-600 mt-1">{execution.error}</p>
            </div>
          </div>
        </div>
      )}

      {/* Actions */}
      <div
        className="flex items-center justify-between p-4 border-t shrink-0"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-center gap-2">
          {isRunning && onPause && (
            <button
              onClick={onPause}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium hover:bg-gray-100 transition-colors"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <Pause className="w-4 h-4" />
              Пауза
            </button>
          )}
          {execution.status === 'paused' && onResume && (
            <button
              onClick={onResume}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium"
              style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
            >
              <Play className="w-4 h-4" />
              Продолжить
            </button>
          )}
          {isRunning && onCancel && (
            <button
              onClick={onCancel}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium text-red-600 hover:bg-red-50 transition-colors"
            >
              <Square className="w-4 h-4" />
              Отменить
            </button>
          )}
        </div>

        {execution.status === 'completed' && execution.result_url && onDownloadResult && (
          <button
            onClick={onDownloadResult}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium"
            style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
          >
            <Download className="w-4 h-4" />
            Скачать отчёт
          </button>
        )}
      </div>
    </div>
  )
}

export default WorkflowExecutionPanel

