import React from 'react'
import { CheckCircle2, Clock, AlertCircle, Loader2 } from 'lucide-react'

export interface AgentStep {
  step_id: string
  agent_name: string
  description: string
  status: 'pending' | 'running' | 'completed' | 'error'
  reasoning?: string
  result?: string
  error?: string
  timestamp?: string
}

interface AgentStepsViewProps {
  steps: AgentStep[]
  isStreaming?: boolean
}

export const AgentStepsView: React.FC<AgentStepsViewProps> = ({ steps, isStreaming }) => {
  if (steps.length === 0) {
    return null
  }

  const getStatusIcon = (status: AgentStep['status']) => {
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

  const getStatusColor = (status: AgentStep['status']) => {
    switch (status) {
      case 'completed':
        return 'border-green-200 bg-green-50'
      case 'running':
        return 'border-blue-200 bg-blue-50'
      case 'error':
        return 'border-red-200 bg-red-50'
      case 'pending':
      default:
        return 'border-gray-200 bg-gray-50'
    }
  }

  return (
    <div className="mt-4 space-y-3">
      <h4 className="text-sm font-semibold text-gray-700 mb-3">Ход выполнения:</h4>
      {steps.map((step, idx) => (
        <div
          key={step.step_id || idx}
          className={`border rounded-lg p-4 ${getStatusColor(step.status)} transition-all`}
        >
          <div className="flex items-start gap-3">
            <div className="flex-shrink-0 mt-0.5">{getStatusIcon(step.status)}</div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-semibold text-sm text-gray-800">
                  {step.agent_name || 'Агент'}
                </span>
                <span className="text-xs text-gray-500">
                  {step.status === 'running' && isStreaming ? 'Выполняется...' : ''}
                  {step.status === 'completed' ? 'Завершено' : ''}
                  {step.status === 'error' ? 'Ошибка' : ''}
                  {step.status === 'pending' ? 'Ожидает' : ''}
                </span>
              </div>
              <p className="text-sm text-gray-700 mb-2">{step.description}</p>
              {step.reasoning && (
                <div className="mt-2 p-2 bg-white rounded border border-gray-200">
                  <p className="text-xs text-gray-600 italic">{step.reasoning}</p>
                </div>
              )}
              {step.result && step.status === 'completed' && (
                <div className="mt-2 p-2 bg-white rounded border border-gray-200">
                  <p className="text-xs text-gray-700">{step.result}</p>
                </div>
              )}
              {step.error && step.status === 'error' && (
                <div className="mt-2 p-2 bg-red-50 rounded border border-red-200">
                  <p className="text-xs text-red-700">{step.error}</p>
                </div>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

