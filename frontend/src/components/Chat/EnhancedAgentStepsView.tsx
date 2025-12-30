import React, { useState } from 'react'
import { 
  CheckCircle2, 
  Clock, 
  AlertCircle, 
  Loader2, 
  ChevronDown, 
  ChevronRight,
  Brain,
  Zap,
  FileText,
  Code
} from 'lucide-react'

export interface EnhancedAgentStep {
  step_id: string
  agent_name: string
  description: string
  status: 'pending' | 'running' | 'completed' | 'error'
  reasoning?: string
  result?: string
  error?: string
  timestamp?: string
  duration?: number // в миллисекундах
  tool_calls?: Array<{
    name: string
    input?: any
    output?: any
  }>
  input?: any
  output?: any
}

interface EnhancedAgentStepsViewProps {
  steps: EnhancedAgentStep[]
  isStreaming?: boolean
  showReasoning?: boolean
  collapsible?: boolean
}

export const EnhancedAgentStepsView: React.FC<EnhancedAgentStepsViewProps> = ({ 
  steps, 
  isStreaming = false,
  showReasoning = true,
  collapsible = true
}) => {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set())
  const [expandedDetails, setExpandedDetails] = useState<Set<string>>(new Set())

  if (steps.length === 0) {
    return null
  }

  const toggleStep = (stepId: string) => {
    if (!collapsible) return
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

  const toggleDetails = (stepId: string) => {
    setExpandedDetails(prev => {
      const next = new Set(prev)
      if (next.has(stepId)) {
        next.delete(stepId)
      } else {
        next.add(stepId)
      }
      return next
    })
  }

  const getStatusIcon = (status: EnhancedAgentStep['status']) => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 className="w-5 h-5 text-green-600" />
      case 'running':
        return <Loader2 className="w-5 h-5 text-blue-600 animate-spin" />
      case 'error':
        return <AlertCircle className="w-5 h-5 text-red-600" />
      case 'pending':
      default:
        return <Clock className="w-5 h-5 text-gray-400" />
    }
  }

  const getStatusColor = (status: EnhancedAgentStep['status']) => {
    switch (status) {
      case 'completed':
        return 'border-green-200 bg-green-50/50'
      case 'running':
        return 'border-blue-200 bg-blue-50/50 animate-pulse'
      case 'error':
        return 'border-red-200 bg-red-50/50'
      case 'pending':
      default:
        return 'border-gray-200 bg-gray-50/50'
    }
  }

  const formatDuration = (ms?: number) => {
    if (!ms) return null
    if (ms < 1000) return `${ms}мс`
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}с`
    return `${(ms / 60000).toFixed(1)}мин`
  }

  const formatTimestamp = (timestamp?: string) => {
    if (!timestamp) return null
    try {
      const date = new Date(timestamp)
      return date.toLocaleTimeString('ru-RU', { 
        hour: '2-digit', 
        minute: '2-digit',
        second: '2-digit'
      })
    } catch {
      return timestamp
    }
  }

  const renderJSON = (data: any) => {
    if (!data) return null
    try {
      return JSON.stringify(data, null, 2)
    } catch {
      return String(data)
    }
  }

  return (
    <div className="mt-4 space-y-2">
      <div className="flex items-center gap-2 mb-3">
        <Brain className="w-4 h-4 text-gray-600" />
        <h4 className="text-sm font-semibold text-gray-700">Цепочка рассуждений и действий:</h4>
        {isStreaming && (
          <span className="text-xs text-blue-600 animate-pulse">Выполняется...</span>
        )}
      </div>
      
      <div className="space-y-2">
        {steps.map((step, idx) => {
          const isExpanded = expandedSteps.has(step.step_id)
          const isDetailsExpanded = expandedDetails.has(step.step_id)
          const hasDetails = step.reasoning || step.result || step.error || step.tool_calls || step.input || step.output
          
          return (
            <div
              key={step.step_id || idx}
              className={`border rounded-lg overflow-hidden transition-all duration-200 ${getStatusColor(step.status)}`}
            >
              {/* Заголовок шага */}
              <div 
                className={`p-4 ${collapsible && hasDetails ? 'cursor-pointer hover:bg-opacity-70' : ''}`}
                onClick={() => collapsible && hasDetails && toggleStep(step.step_id)}
              >
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0 mt-0.5">
                    {getStatusIcon(step.status)}
                  </div>
                  
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="font-semibold text-sm text-gray-800">
                        {step.agent_name || 'Агент'}
                      </span>
                      
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        step.status === 'running' ? 'bg-blue-100 text-blue-700' :
                        step.status === 'completed' ? 'bg-green-100 text-green-700' :
                        step.status === 'error' ? 'bg-red-100 text-red-700' :
                        'bg-gray-100 text-gray-700'
                      }`}>
                        {step.status === 'running' && isStreaming ? 'Выполняется...' :
                         step.status === 'completed' ? 'Завершено' :
                         step.status === 'error' ? 'Ошибка' :
                         'Ожидает'}
                      </span>
                      
                      {step.duration && (
                        <span className="text-xs text-gray-500">
                          {formatDuration(step.duration)}
                        </span>
                      )}
                      
                      {step.timestamp && (
                        <span className="text-xs text-gray-400">
                          {formatTimestamp(step.timestamp)}
                        </span>
                      )}
                    </div>
                    
                    <p className="text-sm text-gray-700 mb-0">{step.description}</p>
                  </div>
                  
                  {collapsible && hasDetails && (
                    <div className="flex-shrink-0">
                      {isExpanded ? (
                        <ChevronDown className="w-4 h-4 text-gray-500" />
                      ) : (
                        <ChevronRight className="w-4 h-4 text-gray-500" />
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Детали шага (раскрывающиеся) */}
              {hasDetails && (isExpanded || !collapsible) && (
                <div className="px-4 pb-4 space-y-2 border-t border-gray-200 pt-3 mt-2">
                  {/* Рассуждения */}
                  {step.reasoning && showReasoning && (
                    <div className="bg-white rounded-lg p-3 border border-gray-200">
                      <div className="flex items-center gap-2 mb-2">
                        <Brain className="w-4 h-4 text-purple-600" />
                        <span className="text-xs font-semibold text-gray-700">Рассуждения:</span>
                      </div>
                      <p className="text-xs text-gray-600 leading-relaxed whitespace-pre-wrap">
                        {step.reasoning}
                      </p>
                    </div>
                  )}

                  {/* Tool Calls */}
                  {step.tool_calls && step.tool_calls.length > 0 && (
                    <div className="space-y-2">
                      {step.tool_calls.map((toolCall, toolIdx) => (
                        <div key={toolIdx} className="bg-white rounded-lg p-3 border border-gray-200">
                          <div className="flex items-center gap-2 mb-2">
                            <Zap className="w-4 h-4 text-yellow-600" />
                            <span className="text-xs font-semibold text-gray-700">
                              Инструмент: {toolCall.name}
                            </span>
                          </div>
                          {toolCall.input && (
                            <details className="mt-2">
                              <summary className="text-xs text-gray-600 cursor-pointer hover:text-gray-800">
                                Входные данные
                              </summary>
                              <pre className="mt-1 text-xs bg-gray-50 p-2 rounded overflow-x-auto">
                                {renderJSON(toolCall.input)}
                              </pre>
                            </details>
                          )}
                          {toolCall.output && (
                            <details className="mt-2">
                              <summary className="text-xs text-gray-600 cursor-pointer hover:text-gray-800">
                                Результат
                              </summary>
                              <pre className="mt-1 text-xs bg-gray-50 p-2 rounded overflow-x-auto">
                                {renderJSON(toolCall.output)}
                              </pre>
                            </details>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Результат */}
                  {step.result && step.status === 'completed' && (
                    <div className="bg-white rounded-lg p-3 border border-green-200">
                      <div className="flex items-center gap-2 mb-2">
                        <FileText className="w-4 h-4 text-green-600" />
                        <span className="text-xs font-semibold text-gray-700">Результат:</span>
                      </div>
                      <p className="text-xs text-gray-700 leading-relaxed whitespace-pre-wrap">
                        {step.result}
                      </p>
                    </div>
                  )}

                  {/* Ошибка */}
                  {step.error && step.status === 'error' && (
                    <div className="bg-red-50 rounded-lg p-3 border border-red-200">
                      <div className="flex items-center gap-2 mb-2">
                        <AlertCircle className="w-4 h-4 text-red-600" />
                        <span className="text-xs font-semibold text-red-700">Ошибка:</span>
                      </div>
                      <p className="text-xs text-red-700 leading-relaxed whitespace-pre-wrap">
                        {step.error}
                      </p>
                    </div>
                  )}

                  {/* Дополнительные детали (input/output) */}
                  {(step.input || step.output) && (
                    <details 
                      className="bg-white rounded-lg p-3 border border-gray-200"
                      open={isDetailsExpanded}
                      onToggle={() => toggleDetails(step.step_id)}
                    >
                      <summary className="text-xs font-semibold text-gray-700 cursor-pointer hover:text-gray-800 flex items-center gap-2">
                        <Code className="w-4 h-4" />
                        Технические детали
                      </summary>
                      <div className="mt-2 space-y-2">
                        {step.input && (
                          <div>
                            <span className="text-xs font-medium text-gray-600">Input:</span>
                            <pre className="mt-1 text-xs bg-gray-50 p-2 rounded overflow-x-auto">
                              {renderJSON(step.input)}
                            </pre>
                          </div>
                        )}
                        {step.output && (
                          <div>
                            <span className="text-xs font-medium text-gray-600">Output:</span>
                            <pre className="mt-1 text-xs bg-gray-50 p-2 rounded overflow-x-auto">
                              {renderJSON(step.output)}
                            </pre>
                          </div>
                        )}
                      </div>
                    </details>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

