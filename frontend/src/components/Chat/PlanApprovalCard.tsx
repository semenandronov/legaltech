import React, { useState } from 'react'
import { CheckCircle2, XCircle, Edit2, Loader2 } from 'lucide-react'
import { getApiUrl } from '@/services/api'
import { logger } from '@/lib/logger'

interface PlanApprovalCardProps {
  planId: string
  plan: {
    reasoning?: string
    analysis_types?: string[]
    confidence?: number
    goals?: Array<{ description: string }>
    steps?: Array<{ description: string; agent_name?: string; estimated_time?: string }>
    strategy?: string
  }
  onApproved?: () => void
  onRejected?: () => void
  onModified?: (modifications: string) => void
}

export const PlanApprovalCard: React.FC<PlanApprovalCardProps> = ({
  planId,
  plan,
  onApproved,
  onRejected,
  onModified,
}) => {
  const [isApproving, setIsApproving] = useState(false)
  const [isRejecting, setIsRejecting] = useState(false)
  const [showModifyInput, setShowModifyInput] = useState(false)
  const [modifyText, setModifyText] = useState('')

  const handleApprove = async () => {
    setIsApproving(true)
    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(getApiUrl('/api/chat/approve-plan'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          plan_id: planId,
          approved: true,
        }),
      })

      if (!response.ok) {
        throw new Error('Failed to approve plan')
      }

      const data = await response.json()
      logger.info('Plan approved:', data)
      // Call onApproved with planId to start streaming
      onApproved?.()
    } catch (error) {
      logger.error('Error approving plan:', error)
      alert('Ошибка при одобрении плана')
    } finally {
      setIsApproving(false)
    }
  }

  const handleReject = async () => {
    setIsRejecting(true)
    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(getApiUrl('/api/chat/approve-plan'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          plan_id: planId,
          approved: false,
        }),
      })

      if (!response.ok) {
        throw new Error('Failed to reject plan')
      }

      onRejected?.()
    } catch (error) {
      logger.error('Error rejecting plan:', error)
      alert('Ошибка при отклонении плана')
    } finally {
      setIsRejecting(false)
    }
  }

  const handleModify = () => {
    if (modifyText.trim()) {
      onModified?.(modifyText)
      setShowModifyInput(false)
      setModifyText('')
    }
  }

  const strategyNames: Record<string, string> = {
    comprehensive_analysis: 'Комплексный анализ',
    parallel_optimized: 'Параллельная оптимизация',
    sequential_dependent: 'Последовательное выполнение с зависимостями',
    simple_sequential: 'Простое последовательное выполнение',
    dependent_sequential: 'Последовательное выполнение зависимых анализов',
    parallel_independent: 'Параллельное выполнение независимых анализов',
  }

  return (
    <div className="border-2 border-blue-200 rounded-xl bg-blue-50 p-5 my-4">
      <div className="flex items-start justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-800">План анализа</h3>
        {plan.confidence !== undefined && (
          <span className="text-sm text-gray-600">
            Уверенность: {(plan.confidence * 100).toFixed(0)}%
          </span>
        )}
      </div>

      {plan.reasoning && (
        <div className="mb-4">
          <p className="text-sm text-gray-700 whitespace-pre-wrap">{plan.reasoning}</p>
        </div>
      )}

      {plan.analysis_types && plan.analysis_types.length > 0 && (
        <div className="mb-4">
          <h4 className="text-sm font-semibold text-gray-700 mb-2">Типы анализов:</h4>
          <div className="flex flex-wrap gap-2">
            {plan.analysis_types.map((type, idx) => (
              <span
                key={idx}
                className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium"
              >
                {type}
              </span>
            ))}
          </div>
        </div>
      )}

      {plan.goals && plan.goals.length > 0 && (
        <div className="mb-4">
          <h4 className="text-sm font-semibold text-gray-700 mb-2">Цели:</h4>
          <ul className="list-disc list-inside space-y-1 text-sm text-gray-700">
            {plan.goals.map((goal, idx) => (
              <li key={idx}>{goal.description}</li>
            ))}
          </ul>
        </div>
      )}

      {plan.strategy && (
        <div className="mb-4">
          <h4 className="text-sm font-semibold text-gray-700 mb-1">Стратегия:</h4>
          <p className="text-sm text-gray-700">
            {strategyNames[plan.strategy] || plan.strategy}
          </p>
        </div>
      )}

      {plan.steps && plan.steps.length > 0 && (
        <div className="mb-4">
          <h4 className="text-sm font-semibold text-gray-700 mb-2">Шаги выполнения:</h4>
          <ol className="list-decimal list-inside space-y-2 text-sm text-gray-700">
            {plan.steps.slice(0, 5).map((step, idx) => (
              <li key={idx} className="ml-2">
                <span className="font-medium">{step.agent_name || 'Агент'}:</span>{' '}
                {step.description}
                {step.estimated_time && (
                  <span className="text-gray-500 ml-2">(~{step.estimated_time})</span>
                )}
              </li>
            ))}
            {plan.steps.length > 5 && (
              <li className="text-gray-500">... и еще {plan.steps.length - 5} шагов</li>
            )}
          </ol>
        </div>
      )}

      {showModifyInput ? (
        <div className="mt-4 space-y-2">
          <textarea
            value={modifyText}
            onChange={(e) => setModifyText(e.target.value)}
            placeholder="Опишите, какие изменения нужно внести в план..."
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={3}
          />
          <div className="flex gap-2">
            <button
              onClick={handleModify}
              disabled={!modifyText.trim()}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium transition-colors"
            >
              Отправить изменения
            </button>
            <button
              onClick={() => {
                setShowModifyInput(false)
                setModifyText('')
              }}
              className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 text-sm font-medium transition-colors"
            >
              Отмена
            </button>
          </div>
        </div>
      ) : (
        <div className="flex gap-3 mt-4">
          <button
            onClick={handleApprove}
            disabled={isApproving || isRejecting}
            className="flex items-center gap-2 px-5 py-2.5 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium transition-colors"
          >
            {isApproving ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Одобряю...
              </>
            ) : (
              <>
                <CheckCircle2 className="w-4 h-4" />
                Одобрить и выполнить
              </>
            )}
          </button>
          <button
            onClick={() => setShowModifyInput(true)}
            disabled={isApproving || isRejecting}
            className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium transition-colors"
          >
            <Edit2 className="w-4 h-4" />
            Изменить
          </button>
          <button
            onClick={handleReject}
            disabled={isApproving || isRejecting}
            className="flex items-center gap-2 px-5 py-2.5 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium transition-colors"
          >
            {isRejecting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Отклоняю...
              </>
            ) : (
              <>
                <XCircle className="w-4 h-4" />
                Отклонить
              </>
            )}
          </button>
        </div>
      )}
    </div>
  )
}

