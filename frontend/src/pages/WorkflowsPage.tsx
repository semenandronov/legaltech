/**
 * Workflows Dashboard Page
 * 
 * Workflows — это сложные многоэтапные процессы обработки документов.
 * В отличие от Playbooks, они работают с множеством документов 
 * и могут занимать от минут до часов.
 */
import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Workflow,
  Play,
  Clock,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Loader2,
  ChevronRight,
  Plus,
  FolderUp,
  File,
  FileText,
  X,
  Zap,
  BarChart3,
  Search,
  Eye,
  Download,
  MessageSquare,
  Table,
  FileEdit,
  BookOpen,
  Target,
  Globe,
  Database,
  FileSearch
} from 'lucide-react'
import { toast } from 'sonner'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import * as workflowsApi from '../services/workflowsApi'
import type { WorkflowDefinition, WorkflowExecution, WorkflowEvent } from '../services/workflowsApi'
import { WorkflowPlanningPhase } from '../components/Workflows/WorkflowPlanningPhase'
import { WorkflowExecutionPanel } from '../components/Workflows/WorkflowExecutionPanel'
import { savePendingWorkflowResult, WorkflowResultData } from '../services/workflowResultsService'

// Иконки для инструментов workflow
const toolIcons: Record<string, React.ReactNode> = {
  'tabular_review': <Table className="w-5 h-5" />,
  'rag_search': <FileSearch className="w-5 h-5" />,
  'web_search': <Globe className="w-5 h-5" />,
  'playbook': <BookOpen className="w-5 h-5" />,
  'summarize': <FileText className="w-5 h-5" />,
  'extract_entities': <Target className="w-5 h-5" />,
  'document_compare': <Database className="w-5 h-5" />,
  'risk_analysis': <AlertTriangle className="w-5 h-5" />,
}

// Карточка Workflow Definition
const WorkflowCard = ({
  workflow,
  onRun,
  stats
}: {
  workflow: WorkflowDefinition
  onRun: () => void
  stats?: { runs: number; avgTime: string; lastRun?: string }
}) => {
  return (
    <div 
      className="rounded-xl border p-5 transition-all hover:border-accent/50 hover:shadow-lg"
      style={{ 
        backgroundColor: 'var(--color-bg-secondary)',
        borderColor: 'var(--color-border)'
      }}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div 
            className="w-12 h-12 rounded-xl flex items-center justify-center"
            style={{ backgroundColor: 'rgba(99, 102, 241, 0.15)' }}
          >
            <Workflow className="w-6 h-6" style={{ color: 'var(--color-accent)' }} />
          </div>
          <div>
            <h3 className="font-semibold" style={{ color: 'var(--color-text-primary)' }}>
              {workflow.display_name}
            </h3>
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              {workflow.is_system ? 'Системный' : 'Пользовательский'}
            </p>
          </div>
        </div>
      </div>

      {/* Description */}
      {workflow.description && (
        <p 
          className="text-sm mb-4 line-clamp-2"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {workflow.description}
        </p>
      )}

      {/* Tools */}
      {workflow.config?.steps && workflow.config.steps.length > 0 && (
        <div className="flex items-center gap-2 mb-4 flex-wrap">
          {workflow.config.steps.slice(0, 5).map((step, idx) => (
            <div 
              key={idx}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs"
              style={{ 
                backgroundColor: 'var(--color-bg-primary)',
                color: 'var(--color-text-secondary)' 
              }}
              title={step.tool}
            >
              {toolIcons[step.tool] || <Zap className="w-3.5 h-3.5" />}
              <span>{step.name || step.tool}</span>
            </div>
          ))}
          {workflow.config.steps.length > 5 && (
            <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              +{workflow.config.steps.length - 5}
            </span>
          )}
        </div>
      )}

      {/* Stats */}
      <div 
        className="flex items-center gap-4 text-xs py-3 border-t mb-4"
        style={{ 
          borderColor: 'var(--color-border)',
          color: 'var(--color-text-tertiary)' 
        }}
      >
        <span className="flex items-center gap-1">
          <Clock className="w-3.5 h-3.5" />
          {stats?.avgTime || workflow.estimated_time || '~5 мин'}
        </span>
        <span className="flex items-center gap-1">
          <BarChart3 className="w-3.5 h-3.5" />
          {stats?.runs || workflow.usage_count || 0} запусков
        </span>
      </div>

      {/* Actions */}
      <button
        onClick={onRun}
        className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors"
        style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
      >
        <Play className="w-4 h-4" />
        Запустить
      </button>
    </div>
  )
}

// Диалог запуска workflow
const RunWorkflowDialog = ({
  workflow,
  onClose,
  onRun
}: {
  workflow: WorkflowDefinition
  onClose: () => void
  onRun: (documents: string[], options: Record<string, any>) => void
}) => {
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([])
  const [options, setOptions] = useState({
    detailLevel: 'comprehensive',
    includeWebSearch: true,
    priority: 'normal',
    notifyOnComplete: true
  })
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const files = Array.from(e.dataTransfer.files)
    setUploadedFiles(prev => [...prev, ...files])
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    setUploadedFiles(prev => [...prev, ...files])
  }

  const removeFile = (index: number) => {
    setUploadedFiles(prev => prev.filter((_, i) => i !== index))
  }

  const handleRun = async () => {
    // Здесь можно добавить загрузку файлов
    // Для простоты передаём названия файлов
    const docIds = uploadedFiles.map(f => f.name)
    onRun(docIds, options)
  }

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
              <Workflow className="w-5 h-5" style={{ color: 'var(--color-accent)' }} />
            </div>
            <div>
              <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                Запуск: {workflow.display_name}
              </h2>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                Настройте параметры и загрузите документы
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-bg-hover"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          {/* Upload Area */}
          <div>
            <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-primary)' }}>
              Документы для обработки
            </h3>
            
            <div
              className="border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors hover:border-accent/50"
              style={{ borderColor: 'var(--color-border)' }}
              onDrop={handleDrop}
              onDragOver={(e) => e.preventDefault()}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={handleFileSelect}
                accept=".pdf,.doc,.docx,.txt,.rtf"
              />
              <FolderUp className="w-12 h-12 mx-auto mb-3" style={{ color: 'var(--color-text-tertiary)' }} />
              <p className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                Перетащите файлы или нажмите для выбора
              </p>
              <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                PDF, DOC, DOCX, TXT • до 100 файлов
              </p>
            </div>

            {/* Uploaded files list */}
            {uploadedFiles.length > 0 && (
              <div className="mt-4 space-y-2">
                {uploadedFiles.map((file, idx) => (
                  <div 
                    key={idx}
                    className="flex items-center justify-between px-3 py-2 rounded-lg"
                    style={{ backgroundColor: 'var(--color-bg-secondary)' }}
                  >
                    <div className="flex items-center gap-2">
                      <File className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
                      <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                        {file.name}
                      </span>
                      <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                        ({(file.size / 1024).toFixed(1)} KB)
                      </span>
                    </div>
                    <button
                      onClick={() => removeFile(idx)}
                      className="p-1 rounded hover:bg-bg-hover"
                      style={{ color: 'var(--color-text-secondary)' }}
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Options */}
          <div>
            <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-primary)' }}>
              Параметры выполнения
            </h3>
            
            <div className="space-y-4">
              {/* Detail Level */}
              <div>
                <label className="block text-sm mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                  Уровень детализации
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { value: 'quick', label: 'Быстрый', desc: '~2 мин' },
                    { value: 'comprehensive', label: 'Полный', desc: '~10 мин' },
                    { value: 'deep_dive', label: 'Глубокий', desc: '~30 мин' }
                  ].map(opt => (
                    <button
                      key={opt.value}
                      className="p-3 rounded-lg border text-left transition-colors"
                      style={{ 
                        backgroundColor: options.detailLevel === opt.value 
                          ? 'rgba(99, 102, 241, 0.1)' 
                          : 'var(--color-bg-secondary)',
                        borderColor: options.detailLevel === opt.value 
                          ? 'var(--color-accent)' 
                          : 'var(--color-border)'
                      }}
                      onClick={() => setOptions({ ...options, detailLevel: opt.value })}
                    >
                      <div className="font-medium text-sm" style={{ color: 'var(--color-text-primary)' }}>
                        {opt.label}
                      </div>
                      <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                        {opt.desc}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Toggles */}
              <div className="flex items-center gap-6">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={options.includeWebSearch}
                    onChange={(e) => setOptions({ ...options, includeWebSearch: e.target.checked })}
                    className="w-4 h-4 rounded"
                  />
                  <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                    Включить веб-поиск
                  </span>
                </label>

                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={options.notifyOnComplete}
                    onChange={(e) => setOptions({ ...options, notifyOnComplete: e.target.checked })}
                    className="w-4 h-4 rounded"
                  />
                  <span className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                    Уведомить по завершении
                  </span>
                </label>
              </div>

              {/* Priority */}
              <div>
                <label className="block text-sm mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                  Приоритет
                </label>
                <div className="flex items-center gap-2">
                  {[
                    { value: 'normal', label: 'Обычный' },
                    { value: 'high', label: 'Высокий', premium: true }
                  ].map(opt => (
                    <button
                      key={opt.value}
                      className="px-4 py-2 rounded-lg border text-sm transition-colors"
                      style={{ 
                        backgroundColor: options.priority === opt.value 
                          ? 'rgba(99, 102, 241, 0.1)' 
                          : 'var(--color-bg-secondary)',
                        borderColor: options.priority === opt.value 
                          ? 'var(--color-accent)' 
                          : 'var(--color-border)',
                        color: 'var(--color-text-primary)'
                      }}
                      onClick={() => setOptions({ ...options, priority: opt.value })}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div 
          className="flex items-center justify-between p-5 border-t shrink-0"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            {uploadedFiles.length} файлов выбрано
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm font-medium"
              style={{ 
                backgroundColor: 'var(--color-bg-secondary)',
                color: 'var(--color-text-primary)' 
              }}
            >
              Отмена
            </button>
            <button
              onClick={handleRun}
              disabled={uploadedFiles.length === 0}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
              style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
            >
              <Play className="w-4 h-4" />
              Запустить Workflow
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// Панель мониторинга выполнения
const ExecutionMonitor = ({
  execution,
  events,
  onClose
}: {
  execution: WorkflowExecution
  events: WorkflowEvent[]
  onClose: () => void
}) => {
  const getOverallStatus = () => {
    if (execution.status === 'completed') return { icon: CheckCircle, color: '#22c55e', label: 'Завершено' }
    if (execution.status === 'failed') return { icon: XCircle, color: '#ef4444', label: 'Ошибка' }
    if (execution.status === 'running') return { icon: Loader2, color: '#6366f1', label: 'Выполняется' }
    return { icon: Clock, color: 'var(--color-text-tertiary)', label: 'Ожидание' }
  }

  const status = getOverallStatus()
  const StatusIcon = status.icon

  return (
    <div
      className="fixed right-0 top-0 bottom-0 w-[520px] shadow-xl border-l overflow-hidden flex flex-col z-40"
      style={{
        backgroundColor: 'var(--color-bg-primary)',
        borderColor: 'var(--color-border)'
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between p-4 border-b shrink-0"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-center gap-3">
          <StatusIcon 
            className={`w-6 h-6 ${status.icon === Loader2 ? 'animate-spin' : ''}`} 
            style={{ color: status.color }} 
          />
          <div>
            <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
              {execution.workflow_name}
            </h2>
            <p className="text-sm" style={{ color: status.color }}>
              {status.label}
            </p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 rounded-lg hover:bg-bg-hover"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Progress Stats */}
      <div className="p-4 grid grid-cols-3 gap-3">
        <div
          className="rounded-lg p-3"
          style={{ backgroundColor: 'var(--color-bg-secondary)' }}
        >
          <div className="text-2xl font-bold" style={{ color: 'var(--color-accent)' }}>
            {execution.progress || 0}%
          </div>
          <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Прогресс
          </div>
        </div>
        <div
          className="rounded-lg p-3"
          style={{ backgroundColor: 'var(--color-bg-secondary)' }}
        >
          <div className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>
            {execution.documents_processed || 0}
          </div>
          <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Документов
          </div>
        </div>
        <div
          className="rounded-lg p-3"
          style={{ backgroundColor: 'var(--color-bg-secondary)' }}
        >
          <div className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>
            {execution.elapsed_time || '0m'}
          </div>
          <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Время
          </div>
        </div>
      </div>

      {/* Steps Timeline */}
      <div className="flex-1 overflow-y-auto p-4">
        <h3 className="text-sm font-medium mb-4" style={{ color: 'var(--color-text-primary)' }}>
          Ход выполнения
        </h3>
        
        <div className="space-y-4">
          {events.map((event, idx) => (
            <div key={idx} className="flex gap-3">
              <div className="flex flex-col items-center">
                {event.type === 'step_completed' ? (
                  <CheckCircle className="w-5 h-5" style={{ color: '#22c55e' }} />
                ) : event.type === 'step_started' ? (
                  <Loader2 className="w-5 h-5 animate-spin" style={{ color: '#6366f1' }} />
                ) : event.type === 'error' ? (
                  <XCircle className="w-5 h-5" style={{ color: '#ef4444' }} />
                ) : (
                  <div className="w-5 h-5 rounded-full border-2" style={{ borderColor: 'var(--color-border)' }} />
                )}
                {idx < events.length - 1 && (
                  <div className="w-0.5 flex-1 mt-2" style={{ backgroundColor: 'var(--color-border)' }} />
                )}
              </div>
              <div className="flex-1 pb-4">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm" style={{ color: 'var(--color-text-primary)' }}>
                    {event.message}
                  </span>
                </div>
                {event.details && (
                  <p className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>
                    {typeof event.details === 'string' ? event.details : JSON.stringify(event.details)}
                  </p>
                )}
                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  {new Date(event.timestamp).toLocaleTimeString('ru-RU')}
                </span>
              </div>
            </div>
          ))}

          {events.length === 0 && (
            <div className="text-center py-8">
              <Clock className="w-8 h-8 mx-auto mb-2" style={{ color: 'var(--color-text-tertiary)' }} />
              <p style={{ color: 'var(--color-text-secondary)' }}>
                Ожидание событий...
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Actions */}
      {execution.status === 'completed' && execution.result_url && (
        <div 
          className="p-4 border-t shrink-0"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <a
            href={execution.result_url}
            target="_blank"
            rel="noopener noreferrer"
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium"
            style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
          >
            <Download className="w-4 h-4" />
            Скачать отчёт
          </a>
        </div>
      )}
    </div>
  )
}

// Доступные инструменты Workflow
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

// Диалог создания Workflow
const CreateWorkflowDialog = ({
  onClose,
  onCreated
}: {
  onClose: () => void
  onCreated: (workflow: WorkflowDefinition) => void
}) => {
  const [form, setForm] = useState({
    name: '',
    display_name: '',
    description: '',
    category: 'custom',
    available_tools: [] as string[],
    is_public: false,
    requires_approval: false,
    max_steps: 50,
    timeout_minutes: 60
  })
  const [saving, setSaving] = useState(false)

  const handleToolToggle = (toolName: string) => {
    setForm(prev => ({
      ...prev,
      available_tools: prev.available_tools.includes(toolName)
        ? prev.available_tools.filter(t => t !== toolName)
        : [...prev.available_tools, toolName]
    }))
  }

  const handleSave = async () => {
    if (!form.display_name.trim()) {
      toast.error('Введите название workflow')
      return
    }
    if (form.available_tools.length === 0) {
      toast.error('Выберите хотя бы один инструмент')
      return
    }

    setSaving(true)
    try {
      const name = form.name || form.display_name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '')
      const workflow = await workflowsApi.createDefinition({
        name: `${name}_${Date.now()}`,
        display_name: form.display_name,
        description: form.description,
        category: form.category,
        available_tools: form.available_tools,
        is_public: form.is_public
      })
      toast.success('Workflow создан')
      onCreated(workflow)
      onClose()
    } catch (error: any) {
      console.error('Failed to create workflow:', error)
      toast.error(error.response?.data?.detail || 'Ошибка создания workflow')
    } finally {
      setSaving(false)
    }
  }

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
              <Plus className="w-5 h-5" style={{ color: 'var(--color-accent)' }} />
            </div>
            <div>
              <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                Создать Workflow
              </h2>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                Создайте свой процесс обработки документов
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-bg-hover"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-6">
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
                color: 'var(--color-text-primary)'
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
                color: 'var(--color-text-primary)'
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
                      : 'var(--color-border)'
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
              Инструменты * <span className="font-normal" style={{ color: 'var(--color-text-tertiary)' }}>({form.available_tools.length} выбрано)</span>
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
                        : 'var(--color-border)'
                    }}
                    onClick={() => handleToolToggle(tool.name)}
                  >
                    <div 
                      className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                      style={{ 
                        backgroundColor: isSelected ? 'var(--color-accent)' : 'var(--color-bg-hover)',
                        color: isSelected ? 'white' : 'var(--color-text-secondary)'
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
              color: 'var(--color-text-primary)' 
            }}
          >
            Отмена
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !form.display_name.trim() || form.available_tools.length === 0}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
          >
            {saving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Plus className="w-4 h-4" />
            )}
            Создать Workflow
          </button>
        </div>
      </div>
    </div>
  )
}

// Главная страница
export default function WorkflowsPage() {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()

  const [workflows, setWorkflows] = useState<WorkflowDefinition[]>([])
  const [executions, setExecutions] = useState<WorkflowExecution[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'templates' | 'running' | 'history'>('templates')
  const [searchQuery, setSearchQuery] = useState('')
  
  // Dialogs
  const [selectedWorkflow, setSelectedWorkflow] = useState<WorkflowDefinition | null>(null)
  const [runningExecution, setRunningExecution] = useState<WorkflowExecution | null>(null)
  const [executionEvents, setExecutionEvents] = useState<WorkflowEvent[]>([])
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  
  // Planning Phase
  const [showPlanningPhase, setShowPlanningPhase] = useState(false)
  const [planningLoading, setPlanningLoading] = useState(false)
  const [workflowPlan, setWorkflowPlan] = useState<any>(null)
  const [pendingDocuments, setPendingDocuments] = useState<string[]>([])
  const [pendingOptions, setPendingOptions] = useState<Record<string, any>>({})
  const [pendingWorkflow, setPendingWorkflow] = useState<WorkflowDefinition | null>(null)
  
  // Enhanced Execution Panel
  const [showExecutionPanel, setShowExecutionPanel] = useState(false)
  const [executionDetails, setExecutionDetails] = useState<any>(null)

  // Навигация
  const navItems = [
    { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
    { id: 'documents', label: 'Документы', icon: FileText, path: `/cases/${caseId}/documents` },
    { id: 'editor', label: 'Редактор', icon: FileEdit, path: `/cases/${caseId}/editor` },
    { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
    { id: 'playbooks', label: 'Playbooks', icon: BookOpen, path: `/cases/${caseId}/playbooks` },
    { id: 'workflows', label: 'Workflows', icon: Workflow, path: `/cases/${caseId}/workflows` },
  ]

  // Загрузка данных
  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true)

        const [workflowsData, executionsData] = await Promise.all([
          workflowsApi.getWorkflowDefinitions(),
          workflowsApi.getWorkflowExecutions({ case_id: caseId, limit: 50 })
        ])

        setWorkflows(workflowsData)
        setExecutions(executionsData)
      } catch (error) {
        console.error('Failed to load data:', error)
        toast.error('Ошибка загрузки данных')
      } finally {
        setLoading(false)
      }
    }

    if (caseId) {
      loadData()
    }
  }, [caseId])

  // Запуск workflow - сначала показываем Planning Phase
  const handleRunWorkflow = async (documents: string[], options: Record<string, any>) => {
    if (!selectedWorkflow || !caseId) return

    // Сохраняем параметры для последующего запуска
    const workflowToRun = selectedWorkflow
    setPendingWorkflow(workflowToRun)
    setPendingDocuments(documents)
    setPendingOptions(options)
    
    // Закрываем диалог выбора документов и показываем Planning Phase
    setSelectedWorkflow(null)
    setShowPlanningPhase(true)
    setPlanningLoading(true)

    try {
      // Генерируем план выполнения (mock для демонстрации)
      const plan = await generateWorkflowPlan(workflowToRun, documents, options)
      setWorkflowPlan(plan)
    } catch (error) {
      console.error('Failed to generate plan:', error)
      toast.error('Ошибка генерации плана')
      setShowPlanningPhase(false)
    } finally {
      setPlanningLoading(false)
    }
  }

  // Генерация плана (в реальности это будет API вызов)
  const generateWorkflowPlan = async (workflow: WorkflowDefinition, documents: string[], options: Record<string, any>) => {
    // Симуляция задержки
    await new Promise(resolve => setTimeout(resolve, 2000))
    
    const tools = workflow.available_tools || ['rag_search', 'summarize']
    const steps = tools.map((tool, idx) => ({
      id: `step_${idx + 1}`,
      tool: tool,
      tool_display_name: AVAILABLE_TOOLS.find(t => t.name === tool)?.display_name || tool,
      description: getToolDescription(tool, documents),
      estimated_time: getEstimatedTime(tool),
      dependencies: idx > 0 ? [`step_${idx}`] : [],
      reasoning: getToolReasoning(tool),
      parameters: getToolParameters(tool, documents, options)
    }))

    return {
      id: `plan_${Date.now()}`,
      workflow_id: workflow.id,
      workflow_name: workflow.display_name,
      goal: `Обработка ${documents.length} документов с помощью ${workflow.display_name}`,
      strategy: `Последовательное выполнение ${steps.length} шагов для комплексного анализа документов`,
      steps,
      total_estimated_time: calculateTotalTime(steps),
      confidence_score: 85 + Math.floor(Math.random() * 10),
      created_at: new Date().toISOString()
    }
  }

  // Вспомогательные функции для генерации плана
  const getToolDescription = (tool: string, documents: string[]) => {
    const descriptions: Record<string, string> = {
      'tabular_review': `Создание сводной таблицы для анализа ${documents.length} документов`,
      'rag_search': 'Семантический поиск по загруженным документам',
      'web_search': 'Поиск актуальной информации в интернете',
      'playbook': 'Проверка документов по правилам playbook',
      'summarize': `Создание резюме для ${documents.length} документов`,
      'extract_entities': 'Извлечение ключевых сущностей: даты, суммы, стороны',
      'document_compare': 'Сравнительный анализ документов',
      'risk_analysis': 'Анализ юридических рисков'
    }
    return descriptions[tool] || 'Обработка документов'
  }

  const getEstimatedTime = (tool: string) => {
    const times: Record<string, string> = {
      'tabular_review': '3-5 мин',
      'rag_search': '1-2 мин',
      'web_search': '2-3 мин',
      'playbook': '5-10 мин',
      'summarize': '2-4 мин',
      'extract_entities': '1-2 мин',
      'document_compare': '3-5 мин',
      'risk_analysis': '5-8 мин'
    }
    return times[tool] || '2-5 мин'
  }

  const getToolReasoning = (tool: string) => {
    const reasons: Record<string, string> = {
      'tabular_review': 'Структурированное представление данных упрощает анализ большого количества документов',
      'rag_search': 'Семантический поиск позволяет найти релевантную информацию даже при неточных запросах',
      'web_search': 'Внешние источники помогают верифицировать информацию и найти актуальные данные',
      'playbook': 'Автоматическая проверка по правилам снижает риск пропуска важных нарушений',
      'summarize': 'Краткие резюме экономят время при работе с большим объемом текста',
      'extract_entities': 'Автоматическое извлечение ключевых данных ускоряет анализ',
      'document_compare': 'Сравнение версий помогает выявить изменения и расхождения',
      'risk_analysis': 'Систематический анализ рисков защищает от юридических проблем'
    }
    return reasons[tool] || 'Этот инструмент необходим для выполнения задачи'
  }

  const getToolParameters = (_tool: string, documents: string[], options: Record<string, any>) => {
    return {
      documents: documents.length,
      detail_level: options.detailLevel || 'comprehensive',
      language: 'ru'
    }
  }

  const calculateTotalTime = (steps: any[]) => {
    const totalMinutes = steps.reduce((acc, step) => {
      const match = step.estimated_time.match(/(\d+)-(\d+)/)
      if (match) {
        return acc + (parseInt(match[1]) + parseInt(match[2])) / 2
      }
      return acc + 3
    }, 0)
    return `${Math.round(totalMinutes)} мин`
  }

  // Одобрение плана и запуск
  const handleApprovePlan = async () => {
    if (!workflowPlan || !caseId) return

    setShowPlanningPhase(false)
    setShowExecutionPanel(true)

    try {
      // Инициализируем детали выполнения
      setExecutionDetails({
        id: `exec_${Date.now()}`,
        workflow_id: workflowPlan.workflow_id,
        workflow_name: workflowPlan.workflow_name,
        status: 'running',
        progress: 0,
        current_step: 0,
        total_steps: workflowPlan.steps.length,
        steps: workflowPlan.steps.map((s: any, idx: number) => ({
          id: s.id,
          step_number: idx + 1,
          name: s.tool_display_name,
          status: idx === 0 ? 'running' : 'pending',
          tools_used: [{
            id: `tool_${idx}`,
            tool_name: s.tool,
            tool_display_name: s.tool_display_name,
            status: idx === 0 ? 'running' : 'pending'
          }]
        })),
        started_at: new Date().toISOString(),
        documents_processed: 0,
        total_documents: pendingDocuments.length,
        ai_thoughts: [
          'Начинаю выполнение плана...',
          `Анализирую ${pendingDocuments.length} документов...`
        ]
      })

      // Симуляция выполнения
      await simulateExecution()

    } catch (error) {
      console.error('Execution failed:', error)
      toast.error('Ошибка выполнения workflow')
    }
  }

  // Симуляция выполнения workflow
  const simulateExecution = async () => {
    const totalSteps = workflowPlan?.steps.length || 3
    
    for (let i = 0; i < totalSteps; i++) {
      // Обновляем текущий шаг
      setExecutionDetails((prev: any) => ({
        ...prev,
        current_step: i,
        progress: Math.round((i / totalSteps) * 100),
        steps: prev.steps.map((s: any, idx: number) => ({
          ...s,
          status: idx < i ? 'completed' : idx === i ? 'running' : 'pending',
          tools_used: s.tools_used.map((t: any) => ({
            ...t,
            status: idx < i ? 'completed' : idx === i ? 'running' : 'pending',
            progress: idx === i ? 0 : undefined
          }))
        })),
        ai_thoughts: [
          ...prev.ai_thoughts,
          `Выполняю шаг ${i + 1}: ${workflowPlan?.steps[i]?.tool_display_name}...`
        ]
      }))

      // Симуляция прогресса инструмента
      for (let p = 0; p <= 100; p += 20) {
        await new Promise(resolve => setTimeout(resolve, 300))
        setExecutionDetails((prev: any) => ({
          ...prev,
          steps: prev.steps.map((s: any, idx: number) => ({
            ...s,
            tools_used: s.tools_used.map((t: any) => ({
              ...t,
              progress: idx === i ? p : t.progress
            }))
          }))
        }))
      }

      // Завершаем шаг
      await new Promise(resolve => setTimeout(resolve, 500))
      setExecutionDetails((prev: any) => ({
        ...prev,
        steps: prev.steps.map((s: any, idx: number) => ({
          ...s,
          status: idx <= i ? 'completed' : s.status,
          completed_at: idx === i ? new Date().toISOString() : s.completed_at,
          tools_used: s.tools_used.map((t: any) => ({
            ...t,
            status: idx <= i ? 'completed' : t.status,
            duration: idx === i ? '2.3s' : t.duration,
            output_summary: idx === i ? 'Успешно обработано' : t.output_summary
          })),
          result_preview: idx === i ? 'Результаты шага доступны' : s.result_preview
        })),
        documents_processed: Math.min(i + 1, pendingDocuments.length)
      }))
    }

    // Завершение
    const completedAt = new Date().toISOString()
    const elapsedTime = '1:45'
    
    setExecutionDetails((prev: any) => ({
      ...prev,
      status: 'completed',
      progress: 100,
      completed_at: completedAt,
      elapsed_time: elapsedTime,
      result_url: '/api/results/example',
      ai_thoughts: [
        ...prev.ai_thoughts,
        'Workflow успешно завершён!',
        `Обработано ${pendingDocuments.length} документов`
      ]
    }))

    // Сохраняем результат для отображения в чате
    const workflowResult: WorkflowResultData = {
      execution_id: `exec_${Date.now()}`,
      workflow_id: pendingWorkflow?.id || '',
      workflow_name: pendingWorkflow?.display_name || 'Workflow',
      case_id: caseId || '',
      status: 'completed',
      summary: `Workflow "${pendingWorkflow?.display_name}" успешно выполнен. Проанализированы документы и созданы необходимые материалы для дальнейшей работы.`,
      documents_processed: pendingDocuments.length,
      elapsed_time: elapsedTime,
      started_at: new Date(Date.now() - 105000).toISOString(), // ~1:45 назад
      completed_at: completedAt,
      artifacts: {
        reports: [
          { id: 'report_1', name: 'Итоговый отчёт', type: 'pdf' }
        ],
        tables: [
          { id: 'table_1', name: 'Результаты анализа', review_id: 'review_' + Date.now() }
        ],
        documents: pendingDocuments.map((docId, idx) => ({
          id: docId,
          name: `Документ ${idx + 1}`
        })),
        checks: []
      },
      results: {
        analysis_complete: true,
        documents_analyzed: pendingDocuments.length
      },
      steps_completed: workflowPlan?.steps?.length || 3,
      total_steps: workflowPlan?.steps?.length || 3
    }
    
    savePendingWorkflowResult(workflowResult)

    toast.success('Workflow успешно завершён! Переход в чат...')
    
    // Задержка перед переходом для плавного UX
    setTimeout(() => {
      setShowExecutionPanel(false)
      setExecutionDetails(null)
      navigate(`/cases/${caseId}/chat`)
    }, 1500)
  }

  // Перегенерация плана
  const handleRegeneratePlan = async () => {
    if (!pendingWorkflow) return
    setPlanningLoading(true)
    try {
      const plan = await generateWorkflowPlan(pendingWorkflow, pendingDocuments, pendingOptions)
      setWorkflowPlan(plan)
    } catch (error) {
      toast.error('Ошибка генерации плана')
    } finally {
      setPlanningLoading(false)
    }
  }

  // Фильтрация
  const filteredWorkflows = workflows.filter(w =>
    w.display_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    w.description?.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const runningExecutions = executions.filter(e => e.status === 'running')
  const completedExecutions = executions.filter(e => e.status !== 'running')

  if (loading) {
    return (
      <div className="flex h-screen" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
        <UnifiedSidebar navItems={navItems} title="Legal AI" />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-8 h-8 animate-spin" style={{ color: 'var(--color-accent)' }} />
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-screen" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      <UnifiedSidebar navItems={navItems} title="Legal AI" />

      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header
          className="flex items-center justify-between px-6 py-4 border-b"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div>
            <h1 className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>
              Workflows
            </h1>
            <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              Автоматизированные процессы обработки документов
            </p>
          </div>

          <button
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium"
            style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
            onClick={() => setShowCreateDialog(true)}
          >
            <Plus className="w-4 h-4" />
            Создать Workflow
          </button>
        </header>

        {/* Running Workflows Banner */}
        {runningExecutions.length > 0 && (
          <div
            className="mx-6 mt-4 p-4 rounded-lg flex items-center justify-between"
            style={{ backgroundColor: 'rgba(99, 102, 241, 0.1)' }}
          >
            <div className="flex items-center gap-3">
              <Loader2 className="w-5 h-5 animate-spin" style={{ color: 'var(--color-accent)' }} />
              <div>
                <p className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                  {runningExecutions.length} workflow{runningExecutions.length > 1 ? 's' : ''} выполняется
                </p>
                <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {runningExecutions[0].workflow_name}
                </p>
              </div>
            </div>
            <button
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-medium"
              style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
              onClick={() => {
                setRunningExecution(runningExecutions[0])
                setActiveTab('running')
              }}
            >
              <Eye className="w-4 h-4" />
              Просмотр
            </button>
          </div>
        )}

        {/* Tabs */}
        <div
          className="flex items-center gap-6 px-6 py-3 border-b"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <button
            onClick={() => setActiveTab('templates')}
            className={`text-sm font-medium pb-2 border-b-2 transition-colors`}
            style={{
              color: activeTab === 'templates' ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
              borderColor: activeTab === 'templates' ? 'var(--color-accent)' : 'transparent'
            }}
          >
            Шаблоны
          </button>
          <button
            onClick={() => setActiveTab('running')}
            className={`text-sm font-medium pb-2 border-b-2 transition-colors flex items-center gap-2`}
            style={{
              color: activeTab === 'running' ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
              borderColor: activeTab === 'running' ? 'var(--color-accent)' : 'transparent'
            }}
          >
            Выполняются
            {runningExecutions.length > 0 && (
              <span
                className="px-1.5 py-0.5 rounded-full text-xs"
                style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
              >
                {runningExecutions.length}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab('history')}
            className={`text-sm font-medium pb-2 border-b-2 transition-colors`}
            style={{
              color: activeTab === 'history' ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
              borderColor: activeTab === 'history' ? 'var(--color-accent)' : 'transparent'
            }}
          >
            История ({completedExecutions.length})
          </button>
        </div>

        {/* Search */}
        <div className="px-6 py-4">
          <div className="relative max-w-md">
            <Search
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4"
              style={{ color: 'var(--color-text-tertiary)' }}
            />
            <input
              type="text"
              placeholder="Поиск workflows..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 rounded-lg border text-sm"
              style={{
                backgroundColor: 'var(--color-bg-secondary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)'
              }}
            />
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 pb-6">
          {activeTab === 'templates' && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredWorkflows.map(workflow => (
                <WorkflowCard
                  key={workflow.id}
                  workflow={workflow}
                  onRun={() => setSelectedWorkflow(workflow)}
                />
              ))}

              {filteredWorkflows.length === 0 && (
                <div className="col-span-full text-center py-12">
                  <Workflow
                    className="w-12 h-12 mx-auto mb-4"
                    style={{ color: 'var(--color-text-tertiary)' }}
                  />
                  <p style={{ color: 'var(--color-text-secondary)' }}>
                    {searchQuery ? 'Ничего не найдено' : 'Нет доступных workflows'}
                  </p>
                </div>
              )}
            </div>
          )}

          {activeTab === 'running' && (
            <div className="space-y-3">
              {runningExecutions.map(exec => (
                <div
                  key={exec.id}
                  className="flex items-center justify-between p-4 rounded-lg border cursor-pointer hover:border-accent/50"
                  style={{
                    backgroundColor: 'var(--color-bg-secondary)',
                    borderColor: 'var(--color-border)'
                  }}
                  onClick={() => setRunningExecution(exec)}
                >
                  <div className="flex items-center gap-4">
                    <Loader2 className="w-6 h-6 animate-spin" style={{ color: 'var(--color-accent)' }} />
                    <div>
                      <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                        {exec.workflow_name}
                      </div>
                      <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                        Начало: {new Date(exec.started_at).toLocaleString('ru-RU')}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="text-right">
                      <div className="text-lg font-bold" style={{ color: 'var(--color-accent)' }}>
                        {exec.progress || 0}%
                      </div>
                      <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                        прогресс
                      </div>
                    </div>
                    <ChevronRight className="w-5 h-5" style={{ color: 'var(--color-text-tertiary)' }} />
                  </div>
                </div>
              ))}

              {runningExecutions.length === 0 && (
                <div className="text-center py-12">
                  <Clock
                    className="w-12 h-12 mx-auto mb-4"
                    style={{ color: 'var(--color-text-tertiary)' }}
                  />
                  <p style={{ color: 'var(--color-text-secondary)' }}>
                    Нет запущенных workflows
                  </p>
                </div>
              )}
            </div>
          )}

          {activeTab === 'history' && (
            <div className="space-y-3">
              {completedExecutions.map(exec => (
                <div
                  key={exec.id}
                  className="flex items-center justify-between p-4 rounded-lg border"
                  style={{
                    backgroundColor: 'var(--color-bg-secondary)',
                    borderColor: 'var(--color-border)'
                  }}
                >
                  <div className="flex items-center gap-4">
                    {exec.status === 'completed' && <CheckCircle className="w-5 h-5" style={{ color: '#22c55e' }} />}
                    {exec.status === 'failed' && <XCircle className="w-5 h-5" style={{ color: '#ef4444' }} />}
                    <div>
                      <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                        {exec.workflow_name}
                      </div>
                      <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                        {new Date(exec.started_at).toLocaleString('ru-RU')}
                        {exec.completed_at && ` • ${exec.elapsed_time || 'N/A'}`}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {exec.status === 'completed' && (
                      <button
                        onClick={() => {
                          // Сохраняем результат и переходим в чат
                          const result: WorkflowResultData = {
                            execution_id: exec.id,
                            workflow_id: exec.workflow_id,
                            workflow_name: exec.workflow_name || 'Workflow',
                            case_id: caseId || '',
                            status: 'completed',
                            summary: exec.summary || `Результаты выполнения workflow "${exec.workflow_name}"`,
                            documents_processed: exec.documents_processed || 0,
                            elapsed_time: exec.elapsed_time || 'н/д',
                            started_at: exec.started_at,
                            completed_at: exec.completed_at || new Date().toISOString(),
                            artifacts: exec.artifacts || { reports: [], tables: [], documents: [], checks: [] },
                            results: exec.results || {},
                            steps_completed: exec.total_steps_completed || 0,
                            total_steps: exec.total_steps_completed || 0
                          }
                          savePendingWorkflowResult(result)
                          navigate(`/cases/${caseId}/chat`)
                          toast.success('Открываем результаты в чате...')
                        }}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm"
                        style={{
                          backgroundColor: 'var(--color-accent)',
                          color: 'white'
                        }}
                      >
                        <MessageSquare className="w-4 h-4" />
                        Результаты
                      </button>
                    )}
                    {exec.result_url && (
                      <a
                        href={exec.result_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm"
                        style={{
                          backgroundColor: 'var(--color-bg-hover)',
                          color: 'var(--color-text-primary)'
                        }}
                      >
                        <Download className="w-4 h-4" />
                        Отчёт
                      </a>
                    )}
                  </div>
                </div>
              ))}

              {completedExecutions.length === 0 && (
                <div className="text-center py-12">
                  <BarChart3
                    className="w-12 h-12 mx-auto mb-4"
                    style={{ color: 'var(--color-text-tertiary)' }}
                  />
                  <p style={{ color: 'var(--color-text-secondary)' }}>
                    История пуста
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Run Workflow Dialog */}
      {selectedWorkflow && (
        <RunWorkflowDialog
          workflow={selectedWorkflow}
          onClose={() => setSelectedWorkflow(null)}
          onRun={handleRunWorkflow}
        />
      )}

      {/* Planning Phase */}
      {showPlanningPhase && (
        <WorkflowPlanningPhase
          plan={workflowPlan}
          isLoading={planningLoading}
          onApprove={handleApprovePlan}
          onRegenerate={handleRegeneratePlan}
          onClose={() => {
            setShowPlanningPhase(false)
            setWorkflowPlan(null)
            setPendingWorkflow(null)
            setPendingDocuments([])
            setPendingOptions({})
          }}
        />
      )}

      {/* Enhanced Execution Panel */}
      {showExecutionPanel && executionDetails && (
        <WorkflowExecutionPanel
          execution={executionDetails}
          onClose={() => {
            setShowExecutionPanel(false)
            setExecutionDetails(null)
          }}
          onPause={() => {
            setExecutionDetails((prev: any) => ({ ...prev, status: 'paused' }))
          }}
          onResume={() => {
            setExecutionDetails((prev: any) => ({ ...prev, status: 'running' }))
          }}
          onCancel={() => {
            setExecutionDetails((prev: any) => ({ ...prev, status: 'cancelled' }))
            toast.info('Workflow отменён')
          }}
          onDownloadResult={() => {
            // Если есть executionDetails, сохраняем результат и переходим в чат
            if (executionDetails && caseId) {
              const result: WorkflowResultData = {
                execution_id: executionDetails.id || `exec_${Date.now()}`,
                workflow_id: executionDetails.workflow_id || '',
                workflow_name: executionDetails.workflow_name || 'Workflow',
                case_id: caseId,
                status: executionDetails.status === 'completed' ? 'completed' : 'failed',
                summary: `Результаты выполнения workflow "${executionDetails.workflow_name}"`,
                documents_processed: executionDetails.documents_processed || 0,
                elapsed_time: executionDetails.elapsed_time || 'н/д',
                started_at: executionDetails.started_at || new Date().toISOString(),
                completed_at: executionDetails.completed_at || new Date().toISOString(),
                artifacts: {
                  reports: [],
                  tables: [],
                  documents: [],
                  checks: []
                },
                results: {},
                steps_completed: executionDetails.total_steps || 0,
                total_steps: executionDetails.total_steps || 0,
                error: executionDetails.error
              }
              savePendingWorkflowResult(result)
              setShowExecutionPanel(false)
              setExecutionDetails(null)
              navigate(`/cases/${caseId}/chat`)
              toast.success('Открываем результаты в чате...')
            }
          }}
        />
      )}

      {/* Legacy Execution Monitor (для старых выполнений) */}
      {runningExecution && !showExecutionPanel && (
        <ExecutionMonitor
          execution={runningExecution}
          events={executionEvents}
          onClose={() => {
            setRunningExecution(null)
            setExecutionEvents([])
          }}
        />
      )}

      {/* Create Workflow Dialog */}
      {showCreateDialog && (
        <CreateWorkflowDialog
          onClose={() => setShowCreateDialog(false)}
          onCreated={(workflow) => {
            setWorkflows(prev => [workflow, ...prev])
          }}
        />
      )}
    </div>
  )
}
