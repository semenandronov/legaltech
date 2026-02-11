/**
 * WorkflowStepBuilder - Конфигуратор шагов workflow с drag-and-drop
 */
import { useState } from 'react'
import {
  GripVertical,
  Plus,
  Trash2,
  ChevronDown,
  ChevronRight,
  Table,
  FileSearch,
  Globe,
  BookOpen,
  FileText,
  Target,
  Database,
  AlertTriangle,
  Zap,
} from 'lucide-react'
import type { WorkflowStep } from '../../services/workflowsApi'

export interface ToolOption {
  name: string
  display_name: string
  description: string
  icon: React.ComponentType<{ className?: string }>
}

const DEFAULT_TOOLS: ToolOption[] = [
  { name: 'tabular_review', display_name: 'Tabular Review', description: 'Создание таблицы для массового анализа документов', icon: Table },
  { name: 'rag_search', display_name: 'RAG Search', description: 'Поиск по документам с AI', icon: FileSearch },
  { name: 'web_search', display_name: 'Web Search', description: 'Поиск информации в интернете', icon: Globe },
  { name: 'playbook', display_name: 'Playbook Check', description: 'Проверка документов по правилам', icon: BookOpen },
  { name: 'summarize', display_name: 'Summarize', description: 'Создание резюме документов', icon: FileText },
  { name: 'extract_entities', display_name: 'Extract Entities', description: 'Извлечение сущностей (даты, суммы, лица)', icon: Target },
  { name: 'document_compare', display_name: 'Document Compare', description: 'Сравнение документов', icon: Database },
  { name: 'risk_analysis', display_name: 'Risk Analysis', description: 'Анализ рисков', icon: AlertTriangle },
]

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

interface WorkflowStepBuilderProps {
  steps: WorkflowStep[]
  availableTools?: ToolOption[]
  onChange: (steps: WorkflowStep[]) => void
}

export const WorkflowStepBuilder = ({
  steps,
  availableTools = DEFAULT_TOOLS,
  onChange,
}: WorkflowStepBuilderProps) => {
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set())
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null)

  const toggleExpand = (index: number) => {
    setExpandedSteps(prev => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }

  const addStep = () => {
    const newStep: WorkflowStep = {
      name: `Шаг ${steps.length + 1}`,
      tool: availableTools[0]?.name || 'rag_search',
      description: '',
      params: {},
      depends_on: [],
    }
    onChange([...steps, newStep])
    setExpandedSteps(prev => new Set(prev).add(steps.length))
  }

  const removeStep = (index: number) => {
    const removedId = steps[index].id || `step_${index}`
    const updated = steps.filter((_, i) => i !== index).map(step => ({
      ...step,
      depends_on: step.depends_on?.filter(d => d !== removedId) || [],
    }))
    onChange(updated)
    setExpandedSteps(prev => {
      const next = new Set<number>()
      prev.forEach(i => {
        if (i < index) next.add(i)
        else if (i > index) next.add(i - 1)
      })
      return next
    })
  }

  const updateStep = (index: number, updates: Partial<WorkflowStep>) => {
    const updated = steps.map((step, i) => (i === index ? { ...step, ...updates } : step))
    onChange(updated)
  }

  const updateParam = (stepIndex: number, key: string, value: string) => {
    const params = { ...(steps[stepIndex].params || {}), [key]: value }
    updateStep(stepIndex, { params })
  }

  const addParam = (stepIndex: number) => {
    const params = { ...(steps[stepIndex].params || {}), '': '' }
    updateStep(stepIndex, { params })
  }

  const removeParam = (stepIndex: number, key: string) => {
    const params = { ...(steps[stepIndex].params || {}) }
    delete params[key]
    updateStep(stepIndex, { params })
  }

  // Drag & Drop
  const handleDragStart = (e: React.DragEvent, index: number) => {
    setDraggedIndex(index)
    e.dataTransfer.effectAllowed = 'move'
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }

  const handleDrop = (e: React.DragEvent, dropIndex: number) => {
    e.preventDefault()
    if (draggedIndex === null || draggedIndex === dropIndex) return

    const updated = [...steps]
    const [dragged] = updated.splice(draggedIndex, 1)
    updated.splice(dropIndex, 0, dragged)
    onChange(updated)

    // Adjust expanded indices
    setExpandedSteps(prev => {
      const next = new Set<number>()
      prev.forEach(i => {
        if (i === draggedIndex) {
          next.add(dropIndex)
        } else if (draggedIndex < dropIndex) {
          next.add(i >= draggedIndex && i <= dropIndex ? i - 1 : i)
        } else {
          next.add(i <= draggedIndex && i >= dropIndex ? i + 1 : i)
        }
      })
      return next
    })
    setDraggedIndex(null)
  }

  const handleDragEnd = () => {
    setDraggedIndex(null)
  }

  const getToolInfo = (toolName: string) => {
    return availableTools.find(t => t.name === toolName)
  }

  return (
    <div className="space-y-3">
      {steps.length === 0 && (
        <div
          className="text-center py-8 rounded-lg border border-dashed"
          style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-tertiary)' }}
        >
          <Zap className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">Добавьте шаги для workflow</p>
        </div>
      )}

      {steps.map((step, index) => {
        const isExpanded = expandedSteps.has(index)
        const toolInfo = getToolInfo(step.tool)
        const ToolIcon = toolInfo?.icon || Zap
        const color = toolColors[step.tool] || 'var(--color-accent)'

        return (
          <div
            key={step.id || index}
            draggable
            onDragStart={(e) => handleDragStart(e, index)}
            onDragOver={handleDragOver}
            onDrop={(e) => handleDrop(e, index)}
            onDragEnd={handleDragEnd}
            className={`rounded-xl border transition-all ${draggedIndex === index ? 'opacity-50 scale-[0.98]' : ''}`}
            style={{
              backgroundColor: 'var(--color-bg-secondary)',
              borderColor: isExpanded ? color : 'var(--color-border)',
            }}
          >
            {/* Header */}
            <div className="flex items-center gap-3 p-4">
              <div
                className="cursor-grab active:cursor-grabbing"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                <GripVertical className="w-4 h-4" />
              </div>

              <div
                className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold text-white shrink-0"
                style={{ backgroundColor: color }}
              >
                {index + 1}
              </div>

              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                style={{ backgroundColor: `${color}20`, color }}
              >
                <ToolIcon className="w-4 h-4" />
              </div>

              <div className="flex-1 min-w-0">
                {isExpanded ? (
                  <input
                    type="text"
                    value={step.name}
                    onChange={(e) => updateStep(index, { name: e.target.value })}
                    className="w-full px-2 py-1 rounded border text-sm font-medium"
                    style={{
                      backgroundColor: 'var(--color-bg-primary)',
                      borderColor: 'var(--color-border)',
                      color: 'var(--color-text-primary)',
                    }}
                    placeholder="Название шага"
                  />
                ) : (
                  <div>
                    <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                      {step.name}
                    </span>
                    <span className="text-xs ml-2" style={{ color: 'var(--color-text-tertiary)' }}>
                      {toolInfo?.display_name || step.tool}
                    </span>
                  </div>
                )}
              </div>

              <button
                onClick={() => toggleExpand(index)}
                className="p-1.5 rounded-lg hover:bg-black/5 transition-colors"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
              </button>

              <button
                onClick={() => removeStep(index)}
                className="p-1.5 rounded-lg hover:bg-red-50 transition-colors text-red-400 hover:text-red-600"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>

            {/* Expanded Content */}
            {isExpanded && (
              <div
                className="px-4 pb-4 pt-0 space-y-4 border-t"
                style={{ borderColor: 'var(--color-border)' }}
              >
                {/* Tool Selection */}
                <div className="pt-4">
                  <label className="block text-xs font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                    Инструмент
                  </label>
                  <div className="grid grid-cols-2 gap-1.5">
                    {availableTools.map(tool => {
                      const Icon = tool.icon
                      const isSelected = step.tool === tool.name
                      const clr = toolColors[tool.name] || 'var(--color-accent)'
                      return (
                        <button
                          key={tool.name}
                          onClick={() => updateStep(index, { tool: tool.name })}
                          className="flex items-center gap-2 p-2 rounded-lg border text-left text-xs transition-colors"
                          style={{
                            backgroundColor: isSelected ? `${clr}15` : 'var(--color-bg-primary)',
                            borderColor: isSelected ? clr : 'var(--color-border)',
                          }}
                        >
                          <span style={{ color: isSelected ? clr : 'var(--color-text-tertiary)' }}><Icon className="w-3.5 h-3.5 shrink-0" /></span>
                          <span style={{ color: 'var(--color-text-primary)' }}>{tool.display_name}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>

                {/* Description */}
                <div>
                  <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>
                    Описание
                  </label>
                  <textarea
                    value={step.description || ''}
                    onChange={(e) => updateStep(index, { description: e.target.value })}
                    rows={2}
                    placeholder="Описание шага..."
                    className="w-full px-3 py-2 rounded-lg border text-sm resize-none"
                    style={{
                      backgroundColor: 'var(--color-bg-primary)',
                      borderColor: 'var(--color-border)',
                      color: 'var(--color-text-primary)',
                    }}
                  />
                </div>

                {/* Parameters */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                      Параметры
                    </label>
                    <button
                      onClick={() => addParam(index)}
                      className="text-xs flex items-center gap-1 px-2 py-0.5 rounded hover:bg-black/5"
                      style={{ color: 'var(--color-accent)' }}
                    >
                      <Plus className="w-3 h-3" /> Добавить
                    </button>
                  </div>
                  {Object.entries(step.params || {}).map(([key, value], pIdx) => (
                    <div key={pIdx} className="flex items-center gap-2 mb-1.5">
                      <input
                        type="text"
                        value={key}
                        onChange={(e) => {
                          const params = { ...(step.params || {}) }
                          const val = params[key]
                          delete params[key]
                          params[e.target.value] = val
                          updateStep(index, { params })
                        }}
                        placeholder="Ключ"
                        className="flex-1 px-2 py-1 rounded border text-xs"
                        style={{
                          backgroundColor: 'var(--color-bg-primary)',
                          borderColor: 'var(--color-border)',
                          color: 'var(--color-text-primary)',
                        }}
                      />
                      <input
                        type="text"
                        value={String(value || '')}
                        onChange={(e) => updateParam(index, key, e.target.value)}
                        placeholder="Значение"
                        className="flex-1 px-2 py-1 rounded border text-xs"
                        style={{
                          backgroundColor: 'var(--color-bg-primary)',
                          borderColor: 'var(--color-border)',
                          color: 'var(--color-text-primary)',
                        }}
                      />
                      <button
                        onClick={() => removeParam(index, key)}
                        className="p-1 rounded hover:bg-red-50 text-red-400"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                  {Object.keys(step.params || {}).length === 0 && (
                    <p className="text-xs italic" style={{ color: 'var(--color-text-tertiary)' }}>
                      Нет параметров
                    </p>
                  )}
                </div>

                {/* Dependencies */}
                {steps.length > 1 && (
                  <div>
                    <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>
                      Зависит от шагов
                    </label>
                    <div className="flex flex-wrap gap-1.5">
                      {steps.map((s, i) => {
                        if (i === index) return null
                        const depId = s.id || `step_${i}`
                        const isDependent = step.depends_on?.includes(depId)
                        return (
                          <button
                            key={i}
                            onClick={() => {
                              const deps = step.depends_on || []
                              const updated = isDependent
                                ? deps.filter(d => d !== depId)
                                : [...deps, depId]
                              updateStep(index, { depends_on: updated })
                            }}
                            className="px-2 py-1 rounded-lg border text-xs transition-colors"
                            style={{
                              backgroundColor: isDependent ? 'rgba(99, 102, 241, 0.1)' : 'var(--color-bg-primary)',
                              borderColor: isDependent ? 'var(--color-accent)' : 'var(--color-border)',
                              color: 'var(--color-text-primary)',
                            }}
                          >
                            #{i + 1} {s.name}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}

      {/* Add Step Button */}
      <button
        onClick={addStep}
        className="w-full flex items-center justify-center gap-2 p-3 rounded-xl border border-dashed text-sm font-medium transition-colors hover:border-accent/50"
        style={{
          borderColor: 'var(--color-border)',
          color: 'var(--color-text-secondary)',
        }}
      >
        <Plus className="w-4 h-4" />
        Добавить шаг
      </button>
    </div>
  )
}
