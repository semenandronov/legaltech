import React, { useState, useEffect } from 'react'
import { Button } from '@/components/UI/Button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/UI/Card'
import { Loader2, Lightbulb, ChevronRight } from 'lucide-react'
import { getApiUrl } from '@/services/api'
import { logger } from '@/lib/logger'

interface Suggestion {
  id: string
  text: string
  type: 'question' | 'action' | 'analysis'
  confidence: number
  context?: string
}

interface SmartSuggestionsProps {
  caseId: string
  context?: string
  onSuggestionClick: (suggestion: string) => void
  className?: string
  limit?: number
}

/**
 * Компонент умных подсказок на основе контекста дела
 */
export const SmartSuggestions: React.FC<SmartSuggestionsProps> = ({
  caseId,
  context,
  onSuggestionClick,
  className = '',
  limit = 5
}) => {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (caseId) {
      loadSuggestions()
    }
  }, [caseId, context])

  const loadSuggestions = async () => {
    if (!caseId) return
    
    setLoading(true)
    setError(null)
    
    try {
      const token = localStorage.getItem('access_token')
      const params = new URLSearchParams()
      if (context) {
        params.append('context', context)
      }
      params.append('limit', limit.toString())
      
      const response = await fetch(
        getApiUrl(`/api/cases/${caseId}/suggestions?${params.toString()}`),
        {
          headers: {
            'X-Access-Token': token || '',
            'Content-Type': 'application/json'
          }
        }
      )
      
      if (!response.ok) {
        throw new Error(`Failed to load suggestions: ${response.statusText}`)
      }
      
      const data = await response.json()
      setSuggestions(data)
    } catch (err) {
      logger.error('Error loading suggestions:', err)
      setError(err instanceof Error ? err.message : 'Ошибка загрузки подсказок')
    } finally {
      setLoading(false)
    }
  }

  const getTypeIcon = (type: string) => {
    switch (type) {
      case 'question':
        return '❓'
      case 'action':
        return '⚡'
      case 'analysis':
        return '🔍'
      default:
        return '💡'
    }
  }

  const getTypeLabel = (type: string) => {
    switch (type) {
      case 'question':
        return 'Вопрос'
      case 'action':
        return 'Действие'
      case 'analysis':
        return 'Анализ'
      default:
        return type
    }
  }

  if (loading) {
    return (
      <div className={`flex items-center justify-center p-4 ${className}`}>
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        <span className="ml-2 text-sm text-muted-foreground">Загрузка подсказок...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className={`p-4 text-sm text-red-600 ${className}`}>
        Ошибка: {error}
      </div>
    )
  }

  if (suggestions.length === 0) {
    return null
  }

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle className="flex items-center text-lg">
          <Lightbulb className="h-5 w-5 mr-2" />
          Умные подсказки
        </CardTitle>
        <CardDescription>
          Предложения на основе анализа вашего дела
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {suggestions.map((suggestion) => (
            <Button
              key={suggestion.id}
              variant="outline"
              className="w-full justify-start text-left h-auto py-3 px-4"
              onClick={() => onSuggestionClick(suggestion.text)}
            >
              <div className="flex items-start w-full">
                <span className="text-lg mr-3">{getTypeIcon(suggestion.type)}</span>
                <div className="flex-1">
                  <div className="font-medium">{suggestion.text}</div>
                  <div className="flex items-center mt-1 text-xs text-muted-foreground">
                    <span>{getTypeLabel(suggestion.type)}</span>
                    {suggestion.confidence > 0 && (
                      <span className="ml-2">
                        • Уверенность: {Math.round(suggestion.confidence * 100)}%
                      </span>
                    )}
                  </div>
                </div>
                <ChevronRight className="h-4 w-4 ml-2 text-muted-foreground" />
              </div>
            </Button>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

export default SmartSuggestions

