import React, { useState } from 'react'
import { CheckCircle2, AlertCircle, Send } from 'lucide-react'
import { logger } from '@/lib/logger'
import { Button } from '@/components/UI/Button'
import { Badge } from '@/components/UI/Badge'
import { Textarea } from '@/components/UI/Textarea'
import { Loader } from '../ai-elements/loader'

interface HumanFeedbackRequestCardProps {
  requestId: string
  message: string
  options?: Array<{ id: string; label: string }>
  inputSchema?: any // JSON Schema for structured input
  agentName?: string
  onResponse: (response: string) => Promise<void>
}

export const HumanFeedbackRequestCard: React.FC<HumanFeedbackRequestCardProps> = ({
  requestId,
  message,
  options,
  inputSchema,
  agentName,
  onResponse,
}) => {
  const [selectedOption, setSelectedOption] = useState<string | null>(null)
  const [customResponse, setCustomResponse] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    if (isSubmitting) return

    let responseValue: string

    // Determine response value based on input type
    if (options && options.length > 0) {
      // Options-based response
      if (!selectedOption) {
        setError('Пожалуйста, выберите вариант ответа')
        return
      }
      responseValue = selectedOption
    } else if (inputSchema) {
      // Structured input based on JSON Schema
      if (!customResponse.trim()) {
        setError('Пожалуйста, заполните поле ответа')
        return
      }
      // Validate JSON if schema expects object
      if (inputSchema.type === 'object') {
        try {
          JSON.parse(customResponse)
        } catch (e) {
          setError('Ответ должен быть валидным JSON объектом')
          return
        }
      }
      responseValue = customResponse
    } else {
      // Free text response
      if (!customResponse.trim()) {
        setError('Пожалуйста, введите ответ')
        return
      }
      responseValue = customResponse
    }

    setIsSubmitting(true)
    setError(null)

    try {
      await onResponse(responseValue)
      logger.info(`Human feedback response submitted for ${requestId}: ${responseValue}`)
    } catch (err) {
      logger.error(`Error submitting human feedback response: ${err}`)
      setError('Ошибка при отправке ответа. Попробуйте еще раз.')
      setIsSubmitting(false)
    }
  }

  const handleOptionSelect = (optionId: string) => {
    setSelectedOption(optionId)
    setError(null)
  }

  return (
    <div className="border-2 border-amber-200 bg-amber-50 rounded-lg p-4 my-4">
      <div className="flex items-start gap-3 mb-4">
        <div className="flex-shrink-0 mt-1">
          <AlertCircle className="w-5 h-5 text-amber-600" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-2">
            <h4 className="text-sm font-semibold text-gray-900">
              Требуется ваш ответ
            </h4>
            {agentName && (
              <Badge variant="outline" className="text-xs">
                {agentName}
              </Badge>
            )}
          </div>
          <p className="text-sm text-gray-700 mb-4">{message}</p>

          {/* Options-based input */}
          {options && options.length > 0 && (
            <div className="space-y-2 mb-4">
              {options.map((option) => (
                <button
                  key={option.id}
                  onClick={() => handleOptionSelect(option.id)}
                  disabled={isSubmitting}
                  className={`w-full text-left px-4 py-2 rounded-lg border-2 transition-colors ${
                    selectedOption === option.id
                      ? 'border-blue-500 bg-blue-50 text-blue-900'
                      : 'border-gray-200 bg-white hover:border-gray-300 text-gray-700'
                  } ${isSubmitting ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
                >
                  <div className="flex items-center gap-2">
                    {selectedOption === option.id ? (
                      <CheckCircle2 className="w-4 h-4 text-blue-600" />
                    ) : (
                      <div className="w-4 h-4 rounded-full border-2 border-gray-300" />
                    )}
                    <span className="text-sm font-medium">{option.label}</span>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Structured input based on JSON Schema */}
          {inputSchema && !options && (
            <div className="mb-4">
              <label className="block text-xs font-semibold text-gray-600 mb-2">
                {inputSchema.title || 'Введите ответ'}
                {inputSchema.required && <span className="text-red-500 ml-1">*</span>}
              </label>
              {inputSchema.description && (
                <p className="text-xs text-gray-500 mb-2">{inputSchema.description}</p>
              )}
              {inputSchema.type === 'object' ? (
                <Textarea
                  value={customResponse}
                  onChange={(e) => {
                    setCustomResponse(e.target.value)
                    setError(null)
                  }}
                  placeholder='{"key": "value"}'
                  className="font-mono text-xs"
                  rows={6}
                  disabled={isSubmitting}
                />
              ) : inputSchema.type === 'string' && inputSchema.format === 'multiline' ? (
                <Textarea
                  value={customResponse}
                  onChange={(e) => {
                    setCustomResponse(e.target.value)
                    setError(null)
                  }}
                  placeholder={inputSchema.placeholder || 'Введите ответ...'}
                  rows={4}
                  disabled={isSubmitting}
                />
              ) : (
                <input
                  type={inputSchema.type === 'number' ? 'number' : 'text'}
                  value={customResponse}
                  onChange={(e) => {
                    setCustomResponse(e.target.value)
                    setError(null)
                  }}
                  placeholder={inputSchema.placeholder || 'Введите ответ...'}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  disabled={isSubmitting}
                />
              )}
            </div>
          )}

          {/* Free text input (fallback) */}
          {!options && !inputSchema && (
            <div className="mb-4">
              <Textarea
                value={customResponse}
                onChange={(e) => {
                  setCustomResponse(e.target.value)
                  setError(null)
                }}
                placeholder="Введите ваш ответ..."
                rows={4}
                disabled={isSubmitting}
              />
            </div>
          )}

          {/* Error message */}
          {error && (
            <div className="mb-4 p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">
              {error}
            </div>
          )}

          {/* Submit button */}
          <div className="flex gap-2">
            <Button
              onClick={handleSubmit}
              disabled={isSubmitting || (!selectedOption && !customResponse.trim())}
              className="bg-blue-600 hover:bg-blue-700"
            >
              {isSubmitting ? (
                <>
                  <Loader size={16} className="mr-2" />
                  Отправка...
                </>
              ) : (
                <>
                  <Send className="w-4 h-4 mr-2" />
                  Отправить ответ
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

