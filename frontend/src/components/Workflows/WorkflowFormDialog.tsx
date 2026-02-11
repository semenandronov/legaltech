/**
 * WorkflowFormDialog - Единый диалог создания/редактирования Workflow
 */
import { useState, useEffect } from 'react'
import {
  X,
  Plus,
  Save,
  Loader2,
  Settings,
  ListOrdered,
  Table,
  FileSearch,
  Globe,
  BookOpen,
  FileText,
  Target,
  Database,
  AlertTriangle,
} from 'lucide-react'
import { toast } from 'sonner'
import * as workflowsApi from '../../services/workflowsApi'
import type { WorkflowDefinition, WorkflowStep } from '../../services/workflowsApi'
import { WorkflowStepBuilder } from './WorkflowStepBuilder'

const AVAILABLE_TOOLS = [
  { name: 'tabular_review', display_name: 'Tabular Review', description: 'Создание таблицы для массового анализа документов', icon: Table },
  { name: 'rag_search', display_name: 'RAG Search', description: 'Поиск по документам с AI', icon: FileSearch },
  { name: 'web_search', display_name: 'Web Search', description: 'Поиск информации в интернете', icon: Globe },
  { name: 'playbook', display_name: 'Playbook Check', description: 'Проверка документов по правилам', icon: BookOpen },
  { name: 'summarize', display_name: 'Summarize', description: 'Создание резюме документов', icon: FileText },
  { name: 'extract_entities', display_name: 'Extract Entities', description: 'Извлечение сущностей (даты, суммы, лица)', icon: Target },
  { name: 'document_compare', display_name: 'Document Compare', description: 'Сравнение документов', icon: Database },
  { name: 'risk_analysis', display_name: 'Risk Analysis', description: 'Анализ рисков', icon: AlertTriangle },
]

const WORKFLOW_CATEGORIES = [
  { name: 'due_diligence', display_name: 'Due Diligence', description: 'Анализ документов для M&A сделок' },
  { name: 'litigation', display_name: 'Litigation Discovery', description: 'Подготовка к судебным разбирательствам' },
  { name: 'compliance', display_name: 'Compliance Update', description: 'Проверка соответствия требованиям' },
  { name: 'research', display_name: 'Legal Research', description: 'Юридическое исследование' },
  { name: 'contract_analysis', display_name: 'Contract Analysis', description: 'Глубокий анализ контрактов' },
  { name: 'custom', display_name: 'Пользовательский', description: 'Произвольный workflow' },
]

interface WorkflowFormDialogProps {
  mode: 'create' | 'edit'
  workflow?: WorkflowDefinition | null
  onClose: () => void
  onSaved: (workflow: WorkflowDefinition) => void
}

export const WorkflowFormDialog = ({
  mode,
  workflow,
  onClose,
  onSaved,
}: WorkflowFormDialogProps) => {
  const [activeTab, setActiveTab] = useState<'settings' | 'steps'>('settings')
  const [saving, setSaving] = useState(false)

  const [form, setForm] = useState({
    display_name: '',
    description: '',
    category: 'custom',
    available_tools: [] as string[],
    is_public: false,
    requires_approval: false,
  })

  const [steps, setSteps] = useState<WorkflowStep[]>([])

  // Initialize form when editing
  useEffect(() => {
    if (mode === 'edit' && workflow) {
      setForm({
        display_name: workflow.display_name || '',
        description: workflow.description || '',
        category: workflow.category || 'custom',
        available_tools: workflow.available_tools || [],
        is_public: workflow.is_public || false,
        requires_approval: workflow.requires_approval || false,
      })
      setSteps(workflow.config?.steps || [])
    }
  }, [mode, workflow])

  const handleToolToggle = (toolName: string) => {
    setForm(prev => ({
      ...prev,
      available_tools: prev.available_tools.includes(toolName)
        ? prev.available_tools.filter(t => t !== toolName)
        : [...prev.available_tools, toolName],
    }))
  }

  const handleSave = async () => {
    if (!form.display_name.trim()) {
      toast.error('Введите название workflow')
      return
    }
    if (form.available_tools.length === 0 && steps.length === 0) {
      toast.error('Выберите инструменты или добавьте шаги')
      return
    }

    setSaving(true)
    try {
      // Derive available_tools from steps if steps are provided
      const toolsFromSteps = [...new Set(steps.map(s => s.tool))]
      const allTools = [...new Set([...form.available_tools, ...toolsFromSteps])]

      // Convert steps to the default_plan format expected by backend
      const defaultPlan = steps.length > 0 ? {
        goals: [{ id: 'goal_1', description: form.description || form.display_name, priority: 1 }],
        steps: steps.map((s, i) => ({
          id: s.id || `step_${i + 1}`,
          name: s.name,
          tool: s.tool,
          tool_name: s.tool,
          description: s.description || '',
          depends_on: s.depends_on || [],
          step_type: 'tool',
          estimated_duration_seconds: 30,
          goal_id: 'goal_1',
        })),
        estimated_total_duration_seconds: steps.length * 30,
        summary: form.description || form.display_name,
      } : undefined

      if (mode === 'edit' && workflow) {
        const updated = await workflowsApi.updateDefinition(workflow.id, {
          display_name: form.display_name,
          description: form.description,
          category: form.category,
          available_tools: allTools,
          is_public: form.is_public,
          requires_approval: form.requires_approval,
          default_plan: defaultPlan,
        })
        toast.success('Workflow обновлён')
        onSaved(updated)
      } else {
        // Generate a clean ASCII name for the backend
        const cleanName = form.display_name
          .toLowerCase()
          .replace(/[а-яё]/gi, (c) => {
            const map: Record<string, string> = {
              'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z','и':'i',
              'й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t',
              'у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y',
              'ь':'','э':'e','ю':'yu','я':'ya'
            }
            return map[c] || c
          })
          .replace(/\s+/g, '_')
          .replace(/[^a-z0-9_]/g, '')
          .replace(/_+/g, '_')
          .replace(/^_|_$/g, '') || 'workflow'

        const created = await workflowsApi.createDefinition({
          name: `${cleanName}_${Date.now()}`,
          display_name: form.display_name,
          description: form.description,
          category: form.category,
          available_tools: allTools,
          is_public: form.is_public,
          requires_approval: form.requires_approval,
          default_plan: defaultPlan,
        })
        toast.success('Workflow создан')
        onSaved(created)
      }
      onClose()
    } catch (error: any) {
      console.error('Failed to save workflow:', error)
      toast.error(error.response?.data?.detail || 'Ошибка сохранения workflow')
    } finally {
      setSaving(false)
    }
  }

  const isEdit = mode === 'edit'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div
        className="w-full max-w-2xl max-h-[90vh] rounded-xl shadow-xl flex flex-col overflow-hidden"
        style={{ backgroundColor: 'var(--color-bg-primary)' }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between p-5 border-b shrink-0"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center"
              style={{ backgroundColor: 'rgba(99, 102, 241, 0.15)' }}
            >
              {isEdit ? (
                <Settings className="w-5 h-5" style={{ color: 'var(--color-accent)' }} />
              ) : (
                <Plus className="w-5 h-5" style={{ color: 'var(--color-accent)' }} />
              )}
            </div>
            <div>
              <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                {isEdit ? 'Редактировать Workflow' : 'Создать Workflow'}
              </h2>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {isEdit ? workflow?.display_name : 'Создайте свой процесс обработки документов'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-black/5"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tabs */}
        <div
          className="flex border-b shrink-0"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <button
            onClick={() => setActiveTab('settings')}
            className="flex items-center gap-2 px-5 py-3 text-sm font-medium border-b-2 transition-colors"
            style={{
              color: activeTab === 'settings' ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
              borderColor: activeTab === 'settings' ? 'var(--color-accent)' : 'transparent',
            }}
          >
            <Settings className="w-4 h-4" />
            Настройки
          </button>
          <button
            onClick={() => setActiveTab('steps')}
            className="flex items-center gap-2 px-5 py-3 text-sm font-medium border-b-2 transition-colors"
            style={{
              color: activeTab === 'steps' ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
              borderColor: activeTab === 'steps' ? 'var(--color-accent)' : 'transparent',
            }}
          >
            <ListOrdered className="w-4 h-4" />
            Шаги
            {steps.length > 0 && (
              <span
                className="px-1.5 py-0.5 rounded-full text-xs"
                style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
              >
                {steps.length}
              </span>
            )}
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5">
          {activeTab === 'settings' && (
            <div className="space-y-6">
              {/* Name */}
              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  Название *
                </label>
                <input
                  type="text"
                  value={form.display_name}
                  onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                  placeholder="Например: Due Diligence для арендных договоров"
                  className="w-full px-4 py-2.5 rounded-lg border text-sm"
                  style={{
                    backgroundColor: 'var(--color-bg-secondary)',
                    borderColor: 'var(--color-border)',
                    color: 'var(--color-text-primary)',
                  }}
                />
              </div>

              {/* Description */}
              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  Описание
                </label>
                <textarea
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="Опишите что делает этот workflow..."
                  rows={3}
                  className="w-full px-4 py-2.5 rounded-lg border text-sm resize-none"
                  style={{
                    backgroundColor: 'var(--color-bg-secondary)',
                    borderColor: 'var(--color-border)',
                    color: 'var(--color-text-primary)',
                  }}
                />
              </div>

              {/* Category */}
              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  Категория
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {WORKFLOW_CATEGORIES.map(cat => (
                    <button
                      key={cat.name}
                      className="p-3 rounded-lg border text-left transition-colors"
                      style={{
                        backgroundColor: form.category === cat.name
                          ? 'rgba(99, 102, 241, 0.1)'
                          : 'var(--color-bg-secondary)',
                        borderColor: form.category === cat.name
                          ? 'var(--color-accent)'
                          : 'var(--color-border)',
                      }}
                      onClick={() => setForm({ ...form, category: cat.name })}
                    >
                      <div className="font-medium text-sm" style={{ color: 'var(--color-text-primary)' }}>
                        {cat.display_name}
                      </div>
                      <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                        {cat.description}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Tools */}
              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  Инструменты{' '}
                  <span className="font-normal" style={{ color: 'var(--color-text-tertiary)' }}>
                    ({form.available_tools.length} выбрано)
                  </span>
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {AVAILABLE_TOOLS.map(tool => {
                    const ToolIcon = tool.icon
                    const isSelected = form.available_tools.includes(tool.name)
                    return (
                      <button
                        key={tool.name}
                        className="flex items-center gap-3 p-3 rounded-lg border text-left transition-colors"
                        style={{
                          backgroundColor: isSelected
                            ? 'rgba(99, 102, 241, 0.1)'
                            : 'var(--color-bg-secondary)',
                          borderColor: isSelected
                            ? 'var(--color-accent)'
                            : 'var(--color-border)',
                        }}
                        onClick={() => handleToolToggle(tool.name)}
                      >
                        <div
                          className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                          style={{
                            backgroundColor: isSelected ? 'var(--color-accent)' : 'var(--color-bg-hover)',
                            color: isSelected ? 'white' : 'var(--color-text-secondary)',
                          }}
                        >
                          <ToolIcon className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <div className="font-medium text-sm truncate" style={{ color: 'var(--color-text-primary)' }}>
                            {tool.display_name}
                          </div>
                          <div className="text-xs truncate" style={{ color: 'var(--color-text-tertiary)' }}>
                            {tool.description}
                          </div>
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Options */}
              <div className="flex items-center gap-6">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.is_public}
                    onChange={(e) => setForm({ ...form, is_public: e.target.checked })}
                    className="w-4 h-4 rounded"
                  />
                  <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                    Публичный workflow
                  </span>
                </label>

                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.requires_approval}
                    onChange={(e) => setForm({ ...form, requires_approval: e.target.checked })}
                    className="w-4 h-4 rounded"
                  />
                  <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                    Требует одобрения плана
                  </span>
                </label>
              </div>
            </div>
          )}

          {activeTab === 'steps' && (
            <WorkflowStepBuilder
              steps={steps}
              availableTools={AVAILABLE_TOOLS}
              onChange={setSteps}
            />
          )}
        </div>

        {/* Footer */}
        <div
          className="flex items-center justify-end gap-3 p-5 border-t shrink-0"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm font-medium"
            style={{
              backgroundColor: 'var(--color-bg-secondary)',
              color: 'var(--color-text-primary)',
            }}
          >
            Отмена
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !form.display_name.trim()}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
          >
            {saving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : isEdit ? (
              <Save className="w-4 h-4" />
            ) : (
              <Plus className="w-4 h-4" />
            )}
            {isEdit ? 'Сохранить' : 'Создать Workflow'}
          </button>
        </div>
      </div>
    </div>
  )
}
