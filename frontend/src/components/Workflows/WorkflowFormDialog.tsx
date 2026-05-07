/**
 * WorkflowFormDialog - Единый диалог создания/редактирования Workflow
 */
import { useState, useEffect } from 'react'
import {
  X,
  Plus,
  Save,
  Loader2,
} from 'lucide-react'
import { toast } from 'sonner'
import * as workflowsApi from '../../services/workflowsApi'
import type { WorkflowDefinition } from '../../services/workflowsApi'

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
  const [saving, setSaving] = useState(false)

  const [form, setForm] = useState({
    display_name: '',
    description: '',
    is_public: false,
    requires_approval: false,
  })

  // Initialize form when editing
  useEffect(() => {
    if (mode === 'edit' && workflow) {
      setForm({
        display_name: workflow.display_name || '',
        description: workflow.description || '',
        is_public: workflow.is_public || false,
        requires_approval: workflow.requires_approval || false,
      })
    }
  }, [mode, workflow])

  const handleSave = async () => {
    if (!form.display_name.trim()) {
      toast.error('Введите название workflow')
      return
    }
    if (!form.description.trim()) {
      toast.error('Опишите задачу для автоматического планирования')
      return
    }

    setSaving(true)
    try {
      if (mode === 'edit' && workflow) {
        const updated = await workflowsApi.updateDefinition(workflow.id, {
          display_name: form.display_name,
          description: form.description,
          category: 'custom',
          available_tools: [],
          is_public: form.is_public,
          requires_approval: form.requires_approval,
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
          category: 'custom',
          available_tools: [],
          is_public: form.is_public,
          requires_approval: form.requires_approval,
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
              {isEdit ? <Save className="w-5 h-5" style={{ color: 'var(--color-accent)' }} /> : <Plus className="w-5 h-5" style={{ color: 'var(--color-accent)' }} />}
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

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5">
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
                placeholder="Например: Анализ договора аренды"
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
                Описание задачи *
              </label>
              <textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="Опишите задачу подробно. Система сама подберёт инструменты и построит план выполнения."
                rows={5}
                className="w-full px-4 py-2.5 rounded-lg border text-sm resize-none"
                style={{
                  backgroundColor: 'var(--color-bg-secondary)',
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-primary)',
                }}
              />
              <p className="mt-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                Категория и инструменты определяются автоматически на этапе планирования.
              </p>
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
            disabled={saving || !form.display_name.trim() || !form.description.trim()}
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
