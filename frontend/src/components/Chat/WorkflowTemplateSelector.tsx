import React, { useState, useEffect } from 'react'
import { Button } from '@/components/UI/Button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/UI/Card'
import { Loader2, Play, Clock } from 'lucide-react'
import { getApiUrl } from '@/services/api'
import { logger } from '@/lib/logger'

interface WorkflowStep {
  agent: string
  name: string
  description: string
  requires_approval: boolean
}

interface WorkflowTemplate {
  id: string
  name: string
  description: string
  steps: WorkflowStep[]
  estimated_time: string
  output_format: string
}

interface WorkflowTemplateSelectorProps {
  caseId: string
  onSelectTemplate: (templateId: string) => void
  className?: string
}

/**
 * Компонент для выбора workflow template
 */
export const WorkflowTemplateSelector: React.FC<WorkflowTemplateSelectorProps> = ({
  caseId,
  onSelectTemplate,
  className = ''
}) => {
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadTemplates()
  }, [caseId])

  const loadTemplates = async () => {
    if (!caseId) return
    
    setLoading(true)
    setError(null)
    
    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(
        getApiUrl(`/api/cases/${caseId}/workflow-templates`),
        {
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
          }
        }
      )
      
      if (!response.ok) {
        throw new Error(`Failed to load templates: ${response.statusText}`)
      }
      
      const data = await response.json()
      setTemplates(data)
    } catch (err) {
      logger.error('Error loading workflow templates:', err)
      setError(err instanceof Error ? err.message : 'Ошибка загрузки шаблонов')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className={`flex items-center justify-center p-8 ${className}`}>
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        <span className="ml-2 text-muted-foreground">Загрузка шаблонов...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className={`p-4 text-red-600 ${className}`}>
        Ошибка: {error}
      </div>
    )
  }

  if (templates.length === 0) {
    return (
      <div className={`p-4 text-muted-foreground ${className}`}>
        Нет доступных шаблонов workflow
      </div>
    )
  }

  return (
    <div className={`space-y-4 ${className}`}>
      <div className="text-sm font-medium">Готовые сценарии работы</div>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {templates.map((template) => (
          <Card 
            key={template.id} 
            className="cursor-pointer hover:shadow-md transition-shadow"
            onClick={() => onSelectTemplate(template.id)}
          >
            <CardHeader>
              <CardTitle className="text-lg">{template.name}</CardTitle>
              <CardDescription>{template.description}</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div className="flex items-center text-sm text-muted-foreground">
                  <Clock className="h-4 w-4 mr-2" />
                  {template.estimated_time}
                </div>
                
                <div className="text-sm">
                  <div className="font-medium mb-2">Шаги:</div>
                  <ul className="space-y-1">
                    {template.steps.slice(0, 3).map((step, idx) => (
                      <li key={idx} className="text-muted-foreground">
                        {idx + 1}. {step.name}
                      </li>
                    ))}
                    {template.steps.length > 3 && (
                      <li className="text-muted-foreground">
                        ... и еще {template.steps.length - 3}
                      </li>
                    )}
                  </ul>
                </div>
                
                <Button 
                  className="w-full mt-4"
                  onClick={(e) => {
                    e.stopPropagation()
                    onSelectTemplate(template.id)
                  }}
                >
                  <Play className="h-4 w-4 mr-2" />
                  Запустить
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}

export default WorkflowTemplateSelector

