import React, { useState } from 'react'
import { CheckCircle2, XCircle, Edit2, Loader2 } from 'lucide-react'
import { getApiUrl } from '@/services/api'
import { logger } from '@/lib/logger'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/UI/Card'
import { Button } from '@/components/UI/Button'
import { Badge } from '@/components/UI/Badge'
import { Reasoning, ReasoningContent, ReasoningTrigger } from '../ai-elements/reasoning'

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
    <Card className="border-2 border-blue-200 bg-blue-50 my-4">
      <CardHeader>
        <div className="flex items-start justify-between">
          <CardTitle className="text-lg font-semibold text-gray-800">План анализа</CardTitle>
          {plan.confidence !== undefined && (
            <Badge variant="outline" className="text-sm">
              Уверенность: {(plan.confidence * 100).toFixed(0)}%
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {plan.reasoning && (
          <div>
            <Reasoning isStreaming={false}>
              <ReasoningTrigger />
              <ReasoningContent>{plan.reasoning}</ReasoningContent>
            </Reasoning>
          </div>
        )}

        {plan.analysis_types && plan.analysis_types.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold text-gray-700 mb-2">Типы анализов:</h4>
            <div className="flex flex-wrap gap-2">
              {plan.analysis_types.map((type, idx) => (
                <Badge key={idx} variant="secondary" className="bg-blue-100 text-blue-800">
                  {type}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {plan.goals && plan.goals.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold text-gray-700 mb-2">Цели:</h4>
            <ul className="list-disc list-inside space-y-1 text-sm text-gray-700">
              {plan.goals.map((goal, idx) => (
                <li key={idx}>{goal.description}</li>
              ))}
            </ul>
          </div>
        )}

        {plan.strategy && (
          <div>
            <h4 className="text-sm font-semibold text-gray-700 mb-1">Стратегия:</h4>
            <p className="text-sm text-gray-700">
              {strategyNames[plan.strategy] || plan.strategy}
            </p>
          </div>
        )}

        {plan.steps && plan.steps.length > 0 && (
          <div>
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
          <div className="space-y-2">
            <textarea
              value={modifyText}
              onChange={(e) => setModifyText(e.target.value)}
              placeholder="Опишите, какие изменения нужно внести в план..."
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              rows={3}
            />
            <div className="flex gap-2">
              <Button
                onClick={handleModify}
                disabled={!modifyText.trim()}
                className="bg-blue-600 hover:bg-blue-700"
              >
                Отправить изменения
              </Button>
              <Button
                onClick={() => {
                  setShowModifyInput(false)
                  setModifyText('')
                }}
                variant="outline"
              >
                Отмена
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex gap-3">
            <Button
              onClick={handleApprove}
              disabled={isApproving || isRejecting}
              className="bg-green-600 hover:bg-green-700"
            >
              {isApproving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  Одобряю...
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4 mr-2" />
                  Одобрить и выполнить
                </>
              )}
            </Button>
            <Button
              onClick={() => setShowModifyInput(true)}
              disabled={isApproving || isRejecting}
              className="bg-blue-600 hover:bg-blue-700"
            >
              <Edit2 className="w-4 h-4 mr-2" />
              Изменить
            </Button>
            <Button
              onClick={handleReject}
              disabled={isApproving || isRejecting}
              className="bg-red-600 hover:bg-red-700"
            >
              {isRejecting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  Отклоняю...
                </>
              ) : (
                <>
                  <XCircle className="w-4 h-4 mr-2" />
                  Отклонить
                </>
              )}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

