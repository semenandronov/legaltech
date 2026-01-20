import React, { useState } from 'react'
import { CheckCircle2, XCircle, Edit2 } from 'lucide-react'
import { getApiUrl } from '@/services/api'
import { logger } from '@/lib/logger'
import { Button } from '@/components/UI/Button'
import { Badge } from '@/components/UI/Badge'
import { Reasoning, ReasoningContent, ReasoningTrigger } from '../ai-elements/reasoning'
import { Loader } from '../ai-elements/loader'
import { Plan, PlanHeader, PlanTitle, PlanDescription, PlanContent, PlanTrigger } from '../ai-elements/plan'

interface PlanApprovalCardProps {
  planId: string
  plan: {
    reasoning?: string
    analysis_types?: string[]
    confidence?: number
    goals?: Array<{ description: string }>
    steps?: Array<{ description: string; agent_name?: string; estimated_time?: string }>
    strategy?: string
    tables_to_create?: Array<{
      table_name?: string
      columns?: Array<{
        label?: string
        question?: string
        type?: string
      }>
      doc_types?: string[] | null
    }>
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
    <Plan className="border-2 border-blue-200 bg-blue-50 my-4" defaultOpen={true}>
      <PlanHeader>
        <div className="flex items-start justify-between w-full">
          <div className="flex-1">
            <PlanTitle>План анализа</PlanTitle>
            {plan.confidence !== undefined && (
              <PlanDescription>
                {`Уверенность: ${(plan.confidence * 100).toFixed(0)}%`}
              </PlanDescription>
            )}
          </div>
          <div className="flex items-center gap-2">
            {plan.confidence !== undefined && (
              <Badge variant="outline" className="text-sm">
                {(plan.confidence * 100).toFixed(0)}%
              </Badge>
            )}
            <PlanTrigger />
          </div>
        </div>
      </PlanHeader>
      <PlanContent className="space-y-4">
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
                <li className="text-gray-500">… и ещё {plan.steps.length - 5} шагов</li>
              )}
            </ol>
          </div>
        )}

        {plan.tables_to_create && plan.tables_to_create.length > 0 && (
          <div className="border-t pt-4 mt-4">
            <h4 className="text-sm font-semibold text-gray-700 mb-3">Таблицы для создания:</h4>
            <div className="space-y-4">
              {plan.tables_to_create.map((table, tableIdx) => (
                <div key={tableIdx} className="bg-white border border-gray-200 rounded-lg p-3">
                  <div className="font-medium text-gray-800 mb-2">
                    {table.table_name || `Таблица ${tableIdx + 1}`}
                  </div>
                  
                  {table.doc_types && table.doc_types.length > 0 && table.doc_types[0] !== 'all' && (
                    <div className="mb-2">
                      <span className="text-xs text-gray-600">Типы документов: </span>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {table.doc_types.map((docType, idx) => (
                          <Badge key={idx} variant="outline" className="text-xs">
                            {docType === 'contract' ? 'Договоры' :
                             docType === 'statement_of_claim' ? 'Исковые заявления' :
                             docType === 'court_decision' ? 'Решения суда' :
                             docType === 'correspondence' ? 'Переписка' :
                             docType === 'motion' ? 'Ходатайства' :
                             docType === 'appeal' ? 'Апелляции' :
                             docType}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  {table.columns && table.columns.length > 0 && (
                    <div>
                      <span className="text-xs text-gray-600">Колонки ({table.columns.length}):</span>
                      <ul className="mt-1 space-y-1">
                        {table.columns.map((column, colIdx) => (
                          <li key={colIdx} className="text-xs text-gray-700 flex items-start">
                            <span className="font-medium mr-2">•</span>
                            <span>
                              <span className="font-medium">{column.label || `Колонка ${colIdx + 1}`}</span>
                              {column.type && (
                                <span className="text-gray-500 ml-1">({column.type})</span>
                              )}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {showModifyInput ? (
          <div className="space-y-2">
            <textarea
              value={modifyText}
              onChange={(e) => setModifyText(e.target.value)}
              placeholder="Опишите, какие изменения нужно внести в план…"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              rows={3}
              aria-label="Изменения к плану"
            />
            <div className="flex gap-2">
              <Button
                onClick={handleModify}
                disabled={!modifyText.trim()}
                className="bg-blue-600 hover:bg-blue-700"
                aria-label="Отправить изменения к плану"
              >
                Отправить изменения
              </Button>
              <Button
                onClick={() => {
                  setShowModifyInput(false)
                  setModifyText('')
                }}
                variant="outline"
                aria-label="Отменить изменение плана"
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
              aria-label="Одобрить план и выполнить"
            >
              {isApproving ? (
                <>
                  <Loader size={16} className="mr-2" />
                  Одобряю…
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
              aria-label="Изменить план"
            >
              <Edit2 className="w-4 h-4 mr-2" />
              Изменить
            </Button>
            <Button
              onClick={handleReject}
              disabled={isApproving || isRejecting}
              className="bg-red-600 hover:bg-red-700"
              aria-label="Отклонить план"
            >
              {isRejecting ? (
                <>
                  <Loader size={16} className="mr-2" />
                  Отклоняю…
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
      </PlanContent>
    </Plan>
  )
}

