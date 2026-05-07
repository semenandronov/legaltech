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
  FileSearch,
  MoreVertical,
  Edit3,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import * as workflowsApi from '../services/workflowsApi'
import { getCaseFiles, addFilesToCase, getCasesList, getRecentCases, type CaseListItem } from '../services/api'
import type { WorkflowDefinition, WorkflowExecution, WorkflowEvent } from '../services/workflowsApi'
import { WorkflowPlanningPhase } from '../components/Workflows/WorkflowPlanningPhase'
import { WorkflowExecutionPanel } from '../components/Workflows/WorkflowExecutionPanel'
import { WorkflowFormDialog } from '../components/Workflows/WorkflowFormDialog'
import { WorkflowResultsView } from '../components/Workflows/WorkflowResultsView'
import { savePendingWorkflowResult, WorkflowResultData } from '../services/workflowResultsService'

// Иконки для инструментов workflow
const toolIcons: Record<string, React.ReactNode> = {
  'tabular_review': <Table className="w-5 h-5" />,
  'rag': <FileSearch className="w-5 h-5" />,
  'legal_db': <Globe className="w-5 h-5" />,
  'playbook_check': <BookOpen className="w-5 h-5" />,
  'summarize': <FileText className="w-5 h-5" />,
  'extract_entities': <Target className="w-5 h-5" />,
  'document_draft': <Database className="w-5 h-5" />,
}

// Карточка Workflow Definition
const WorkflowCard = ({
  workflow,
  onRun,
  onEdit,
  onDelete,
  stats
}: {
  workflow: WorkflowDefinition
  onRun: () => void
  onEdit?: () => void
  onDelete?: () => void
  stats?: { runs: number; avgTime: string; lastRun?: string }
}) => {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div
      className="rounded-xl border p-5 transition-all hover:border-accent/50 hover:shadow-lg relative"
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

        {/* Context Menu */}
        {!workflow.is_system && (
          <div className="relative">
            <button
              onClick={() => setMenuOpen(!menuOpen)}
              className="p-1.5 rounded-lg hover:bg-black/5 transition-colors"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              <MoreVertical className="w-4 h-4" />
            </button>
            {menuOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                <div
                  className="absolute right-0 top-8 z-20 w-44 rounded-lg border shadow-lg py-1 overflow-hidden"
                  style={{
                    backgroundColor: 'var(--color-bg-primary)',
                    borderColor: 'var(--color-border)',
                  }}
                >
                  <button
                    onClick={() => { setMenuOpen(false); onRun() }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-black/5 text-left"
                    style={{ color: 'var(--color-text-primary)' }}
                  >
                    <Play className="w-4 h-4" />
                    Запустить
                  </button>
                  {onEdit && (
                    <button
                      onClick={() => { setMenuOpen(false); onEdit() }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-black/5 text-left"
                      style={{ color: 'var(--color-text-primary)' }}
                    >
                      <Edit3 className="w-4 h-4" />
                      Редактировать
                    </button>
                  )}
                  {onDelete && (
                    <button
                      onClick={() => { setMenuOpen(false); onDelete() }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-red-50 text-left text-red-600"
                    >
                      <Trash2 className="w-4 h-4" />
                      Удалить
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        )}
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
  initialCaseId,
  onClose,
  onRun
}: {
  workflow: WorkflowDefinition
  initialCaseId?: string
  onClose: () => void
  onRun: (caseId: string, documents: string[], options: Record<string, any>) => void
}) => {
  const [selectedCaseId, setSelectedCaseId] = useState(initialCaseId || '')
  const [availableCases, setAvailableCases] = useState<CaseListItem[]>([])
  const [loadingCases, setLoadingCases] = useState(false)
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([])
  const [existingFiles, setExistingFiles] = useState<Array<{ id: string; filename: string; file_type: string; selected: boolean }>>([])
  const [loadingFiles, setLoadingFiles] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Загружаем список дел (для глобального /workflows)
  useEffect(() => {
    if (initialCaseId) return
    const loadCases = async () => {
      try {
        setLoadingCases(true)
        // Для модалки workflow берём "recent" как в глобальном ассистенте:
        // это заметно легче и быстрее, чем полный список дел.
        const recent = await getRecentCases(20)
        setAvailableCases(recent || [])
      } catch (error) {
        console.error('Failed to load cases:', error)
        try {
          const response = await getCasesList(0, 100)
          setAvailableCases(response.cases || [])
        } catch {
          toast.error('Не удалось загрузить список дел')
        }
      } finally {
        setLoadingCases(false)
      }
    }
    loadCases()
  }, [initialCaseId])

  // Загружаем существующие файлы из выбранного дела
  useEffect(() => {
    const loadExistingFiles = async () => {
      if (!selectedCaseId) {
        setExistingFiles([])
        setLoadingFiles(false)
        return
      }
      try {
        setLoadingFiles(true)
        const response = await getCaseFiles(selectedCaseId)
        setExistingFiles(response.files.map(f => ({ ...f, selected: true }))) // По умолчанию все выбраны
      } catch (error) {
        console.error('Failed to load case files:', error)
      } finally {
        setLoadingFiles(false)
      }
    }
    loadExistingFiles()
  }, [selectedCaseId])

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

  const toggleExistingFile = (fileId: string) => {
    setExistingFiles(prev => prev.map(f => 
      f.id === fileId ? { ...f, selected: !f.selected } : f
    ))
  }

  const handleRun = async () => {
    try {
      setUploading(true)
      let newFileIds: string[] = []

      // Загружаем новые файлы на сервер если есть
      if (uploadedFiles.length > 0) {
        const response = await addFilesToCase(selectedCaseId, uploadedFiles, setUploadProgress)
        newFileIds = response.files.map(f => f.id)
      }

      // Собираем ID выбранных существующих файлов
      const selectedExistingIds = existingFiles
        .filter(f => f.selected)
        .map(f => f.id)

      // Объединяем все ID файлов
      const allFileIds = [...selectedExistingIds, ...newFileIds]

      if (!selectedCaseId) {
        toast.error('Выберите дело')
        return
      }

      if (allFileIds.length === 0) {
        toast.error('Выберите хотя бы один документ')
        return
      }

      onRun(selectedCaseId, allFileIds, {})
    } catch (error) {
      console.error('Failed to upload files:', error)
      toast.error('Ошибка загрузки файлов')
    } finally {
      setUploading(false)
      setUploadProgress(0)
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
          {/* Case selector (global workflows page) */}
          {!initialCaseId && (
            <div>
              <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-primary)' }}>
                Выберите дело
              </h3>
              {loadingCases ? (
                <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Загрузка дел…
                </div>
              ) : (
                <>
                  <select
                    value={selectedCaseId}
                    onChange={(e) => setSelectedCaseId(e.target.value)}
                    className="w-full rounded-lg border px-3 py-2.5 text-sm"
                    style={{
                      backgroundColor: 'var(--color-bg-secondary)',
                      borderColor: 'var(--color-border)',
                      color: 'var(--color-text-primary)',
                    }}
                  >
                    <option value="">— Выберите дело —</option>
                    {availableCases.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.title || `Дело ${c.id.slice(0, 8)}`}
                      </option>
                    ))}
                  </select>
                  {availableCases.length === 0 && (
                    <p className="text-xs mt-2" style={{ color: 'var(--color-text-tertiary)' }}>
                      Список дел пуст. Проверьте, что дела созданы, и обновите страницу.
                    </p>
                  )}
                </>
              )}
            </div>
          )}

          {/* Existing Files from Case */}
          <div>
            <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-primary)' }}>
              Документы из дела
            </h3>
            
            {loadingFiles ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-6 h-6 animate-spin" style={{ color: 'var(--color-accent)' }} />
                <span className="ml-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  Загрузка файлов…
                </span>
              </div>
            ) : existingFiles.length > 0 ? (
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {existingFiles.map((file) => (
                  <label 
                    key={file.id}
                    className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors hover:bg-bg-hover"
                    style={{ backgroundColor: file.selected ? 'rgba(99, 102, 241, 0.1)' : 'var(--color-bg-secondary)' }}
                  >
                    <input
                      type="checkbox"
                      checked={file.selected}
                      onChange={() => toggleExistingFile(file.id)}
                      className="w-4 h-4 rounded border-gray-300 text-accent focus:ring-accent"
                    />
                    <File className="w-4 h-4" style={{ color: file.selected ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }} />
                    <span className="text-sm flex-1 truncate" style={{ color: 'var(--color-text-primary)' }}>
                      {file.filename}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded" style={{ backgroundColor: 'var(--color-bg-tertiary)', color: 'var(--color-text-tertiary)' }}>
                      {file.file_type.toUpperCase()}
                    </span>
                  </label>
                ))}
              </div>
            ) : (
              <div className="text-center py-4" style={{ color: 'var(--color-text-tertiary)' }}>
                <p className="text-sm">В деле нет загруженных документов</p>
              </div>
            )}
            
            {existingFiles.length > 0 && (
              <div className="flex items-center justify-between mt-2 pt-2 border-t" style={{ borderColor: 'var(--color-border)' }}>
                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  Выбрано: {existingFiles.filter(f => f.selected).length} из {existingFiles.length}
                </span>
                <button
                  onClick={() => setExistingFiles(prev => prev.map(f => ({ ...f, selected: !prev.every(p => p.selected) })))}
                  className="text-xs hover:underline"
                  style={{ color: 'var(--color-accent)' }}
                >
                  {existingFiles.every(f => f.selected) ? 'Снять все' : 'Выбрать все'}
                </button>
              </div>
            )}
          </div>

          {/* Upload New Files */}
          <div>
            <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-primary)' }}>
              Добавить новые документы
            </h3>
            
            <div
              className="border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors hover:border-accent/50"
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
                accept=".pdf,.doc,.docx,.txt,.rtf,.xlsx"
              />
              <FolderUp className="w-10 h-10 mx-auto mb-2" style={{ color: 'var(--color-text-tertiary)' }} />
              <p className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                Перетащите файлы или нажмите для выбора
              </p>
              <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                PDF, DOC, DOCX, TXT, XLSX
              </p>
            </div>

            {/* New files to upload */}
            {uploadedFiles.length > 0 && (
              <div className="mt-3 space-y-2">
                <p className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                  Новые файлы ({uploadedFiles.length}):
                </p>
                {uploadedFiles.map((file, idx) => (
                  <div 
                    key={idx}
                    className="flex items-center justify-between px-3 py-2 rounded-lg"
                    style={{ backgroundColor: 'rgba(34, 197, 94, 0.1)' }}
                  >
                    <div className="flex items-center gap-2">
                      <Plus className="w-4 h-4" style={{ color: '#22c55e' }} />
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

            {/* Upload progress */}
            {uploading && uploadProgress > 0 && (
              <div className="mt-3">
                <div className="flex items-center justify-between text-xs mb-1">
                  <span style={{ color: 'var(--color-text-secondary)' }}>Загрузка файлов…</span>
                  <span style={{ color: 'var(--color-accent)' }}>{uploadProgress}%</span>
                </div>
                <div className="h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: 'var(--color-bg-tertiary)' }}>
                  <div 
                    className="h-full rounded-full transition-all duration-300"
                    style={{ width: `${uploadProgress}%`, backgroundColor: 'var(--color-accent)' }}
                  />
                </div>
              </div>
            )}
          </div>

        </div>

        {/* Footer */}
        <div 
          className="flex items-center justify-between p-5 border-t shrink-0"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            {existingFiles.filter(f => f.selected).length + uploadedFiles.length} документов выбрано
            {uploadedFiles.length > 0 && (
              <span style={{ color: '#22c55e' }}> (+{uploadedFiles.length} новых)</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              disabled={uploading}
              className="px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
              style={{ 
                backgroundColor: 'var(--color-bg-secondary)',
                color: 'var(--color-text-primary)' 
              }}
            >
              Отмена
            </button>
            <button
              onClick={handleRun}
              disabled={uploading || (existingFiles.filter(f => f.selected).length === 0 && uploadedFiles.length === 0)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
              style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
            >
              {uploading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Загрузка…
                </>
              ) : (
                <>
              <Play className="w-4 h-4" />
              Запустить Workflow
                </>
              )}
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
  { name: 'rag', display_name: 'RAG Search', description: 'Поиск по документам с AI', icon: FileSearch },
  { name: 'legal_db', display_name: 'Legal DB', description: 'Поиск в правовой базе', icon: Globe },
  { name: 'playbook_check', display_name: 'Playbook Check', description: 'Проверка документов по правилам', icon: BookOpen },
  { name: 'summarize', display_name: 'Summarize', description: 'Создание резюме документов', icon: FileText },
  { name: 'extract_entities', display_name: 'Extract Entities', description: 'Извлечение сущностей (даты, суммы, лица)', icon: Target },
  { name: 'document_draft', display_name: 'Document Draft', description: 'Подготовка проекта документа', icon: Database },
]

// Главная страница
export default function WorkflowsPage({ embedded = false }: { embedded?: boolean } = {}) {
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
  const [editingWorkflow, setEditingWorkflow] = useState<WorkflowDefinition | null>(null)
  const [viewingExecutionId, setViewingExecutionId] = useState<string | null>(null)

  // Planning Phase
  const [showPlanningPhase, setShowPlanningPhase] = useState(false)
  const [planningLoading, setPlanningLoading] = useState(false)
  const [workflowPlan, setWorkflowPlan] = useState<any>(null)
  const [pendingDocuments, setPendingDocuments] = useState<string[]>([])
  const [pendingOptions, setPendingOptions] = useState<Record<string, any>>({})
  const [pendingWorkflow, setPendingWorkflow] = useState<WorkflowDefinition | null>(null)
  const [pendingCaseId, setPendingCaseId] = useState<string>('')
  
  // Enhanced Execution Panel
  const [showExecutionPanel, setShowExecutionPanel] = useState(false)
  const [executionDetails, setExecutionDetails] = useState<any>(null)

  // Навигация
  const navItems = caseId
    ? [
        { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
        { id: 'editor', label: 'Редактор', icon: FileEdit, path: `/cases/${caseId}/editor` },
        { id: 'playbooks', label: 'Playbooks', icon: BookOpen, path: `/cases/${caseId}/playbooks` },
        { id: 'workflows', label: 'Workflows', icon: Workflow, path: `/cases/${caseId}/workflows` },
      ]
    : [
        { id: 'cases', label: 'Дела', icon: FolderUp, path: '/cases' },
        { id: 'assistant', label: 'Ассистент', icon: MessageSquare, path: '/assistant' },
        { id: 'workflows', label: 'Workflows', icon: Workflow, path: '/workflows' },
      ]

  // Загрузка данных
  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true)

        const [workflowsData, executionsData] = await Promise.all([
          workflowsApi.getWorkflowDefinitions(),
          workflowsApi.getWorkflowExecutions({ case_id: caseId || undefined, limit: 50 })
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

    loadData()
  }, [caseId])

  // Запуск workflow - сначала показываем Planning Phase
  const handleRunWorkflow = async (runCaseId: string, documents: string[], options: Record<string, any>) => {
    if (!selectedWorkflow || !runCaseId) return

    // Сохраняем параметры для последующего запуска
    const workflowToRun = selectedWorkflow
    setPendingWorkflow(workflowToRun)
    setPendingCaseId(runCaseId)
    setPendingDocuments(documents)
    setPendingOptions(options)
    
    // Закрываем диалог выбора документов и показываем Planning Phase
    setSelectedWorkflow(null)
    setShowPlanningPhase(true)
    setPlanningLoading(true)

    try {
      // Генерируем план выполнения (mock для демонстрации)
      const plan = await generateWorkflowPlan(workflowToRun, documents, options, runCaseId)
      setWorkflowPlan(plan)
    } catch (error) {
      console.error('Failed to generate plan:', error)
      toast.error('Ошибка генерации плана')
      setShowPlanningPhase(false)
    } finally {
      setPlanningLoading(false)
    }
  }

  // Генерация плана через реальный API
  const generateWorkflowPlan = async (
    workflow: WorkflowDefinition,
    documents: string[],
    _options: Record<string, any>,
    runCaseId: string
  ) => {
    // Если у workflow есть настроенные шаги — используем их напрямую
    const configuredSteps = workflow.config?.steps
    if (configuredSteps && configuredSteps.length > 0) {
      const steps = configuredSteps.map((step, idx) => ({
        id: step.id || `step_${idx + 1}`,
        tool: step.tool,
        tool_display_name: AVAILABLE_TOOLS.find(t => t.name === step.tool)?.display_name || step.tool,
        description: step.description || getToolDescription(step.tool, documents),
        estimated_time: getEstimatedTime(step.tool),
        dependencies: step.depends_on || (idx > 0 ? [`step_${idx}`] : []),
        reasoning: getToolReasoning(step.tool),
        parameters: step.params || {}
      }))

      return {
        id: `plan_${Date.now()}`,
        workflow_id: workflow.id,
        workflow_name: workflow.display_name,
        goal: workflow.description || `Обработка ${documents.length} документов с помощью ${workflow.display_name}`,
        strategy: `Выполнение ${steps.length} настроенных шагов для анализа документов`,
        steps,
        total_estimated_time: calculateTotalTime(steps),
        confidence_score: 90,
        created_at: new Date().toISOString()
      }
    }

    // Нет настроенных шагов — вызываем API для автоматического планирования
    try {
      const planResponse = await workflowsApi.createPlan({
        definition_id: workflow.id,
        user_task: `Выполнить workflow "${workflow.display_name}" для анализа ${documents.length} документов`,
        case_id: runCaseId || undefined,
        file_ids: documents
      })

      const planData = planResponse.plan
      const steps = (planData.steps || []).map((step: any, idx: number) => ({
        id: step.id || `step_${idx + 1}`,
        tool: step.tool_name || step.tool,
        tool_display_name: AVAILABLE_TOOLS.find(t => t.name === (step.tool_name || step.tool))?.display_name || step.name,
        description: step.description || getToolDescription(step.tool_name || step.tool, documents),
        estimated_time: step.estimated_duration_seconds
          ? `${Math.ceil(step.estimated_duration_seconds / 60)} мин`
          : getEstimatedTime(step.tool_name || step.tool),
        dependencies: step.depends_on || [],
        reasoning: step.reasoning || getToolReasoning(step.tool_name || step.tool),
        parameters: step.tool_params || {}
      }))

      const goalText = planData.goals && planData.goals.length > 0
        ? planData.goals.map((g: any) => g.description).join('; ')
        : `Обработка ${documents.length} документов с помощью ${workflow.display_name}`

      return {
        id: `plan_${Date.now()}`,
        workflow_id: workflow.id,
        workflow_name: workflow.display_name,
        goal: goalText,
        strategy: planData.summary || `Последовательное выполнение ${steps.length} шагов для комплексного анализа документов`,
        steps,
        total_estimated_time: planResponse.estimated_duration_seconds
          ? `${Math.ceil(planResponse.estimated_duration_seconds / 60)} мин`
          : calculateTotalTime(steps),
        confidence_score: planResponse.is_valid ? 90 : 70,
        created_at: new Date().toISOString()
      }
    } catch (error) {
      console.error('API plan generation failed, using fallback:', error)
      // Fallback: генерируем шаги из available_tools
      const tools = workflow.available_tools || ['rag', 'summarize']
      const steps = tools.map((tool, idx) => ({
        id: `step_${idx + 1}`,
        tool: tool,
        tool_display_name: AVAILABLE_TOOLS.find(t => t.name === tool)?.display_name || tool,
        description: getToolDescription(tool, documents),
        estimated_time: getEstimatedTime(tool),
        dependencies: idx > 0 ? [`step_${idx}`] : [],
        reasoning: getToolReasoning(tool),
        parameters: {}
      }))

      return {
        id: `plan_${Date.now()}`,
        workflow_id: workflow.id,
        workflow_name: workflow.display_name,
        goal: `Обработка ${documents.length} документов с помощью ${workflow.display_name}`,
        strategy: `Последовательное выполнение ${steps.length} шагов для комплексного анализа документов`,
        steps,
        total_estimated_time: calculateTotalTime(steps),
        confidence_score: 85,
        created_at: new Date().toISOString()
      }
    }
  }

  // Вспомогательные функции для генерации плана
  const getToolDescription = (tool: string, documents: string[]) => {
    const descriptions: Record<string, string> = {
      'tabular_review': `Создание сводной таблицы для анализа ${documents.length} документов`,
      'rag': 'Семантический поиск по загруженным документам',
      'legal_db': 'Поиск в правовой базе и судебной практике',
      'playbook_check': 'Проверка документов по правилам playbook',
      'summarize': `Создание резюме для ${documents.length} документов`,
      'extract_entities': 'Извлечение ключевых сущностей: даты, суммы, стороны',
      'document_draft': 'Подготовка проекта юридического документа'
    }
    return descriptions[tool] || 'Обработка документов'
  }

  const getEstimatedTime = (tool: string) => {
    const times: Record<string, string> = {
      'tabular_review': '3-5 мин',
      'rag': '1-2 мин',
      'legal_db': '2-3 мин',
      'playbook_check': '5-10 мин',
      'summarize': '2-4 мин',
      'extract_entities': '1-2 мин',
      'document_draft': '4-8 мин'
    }
    return times[tool] || '2-5 мин'
  }

  const getToolReasoning = (tool: string) => {
    const reasons: Record<string, string> = {
      'tabular_review': 'Структурированное представление данных упрощает анализ большого количества документов',
      'rag': 'Семантический поиск позволяет найти релевантную информацию даже при неточных запросах',
      'legal_db': 'Правовая база нужна для валидации выводов и подбора релевантной практики',
      'playbook_check': 'Автоматическая проверка по правилам снижает риск пропуска важных нарушений',
      'summarize': 'Краткие резюме экономят время при работе с большим объемом текста',
      'extract_entities': 'Автоматическое извлечение ключевых данных ускоряет анализ',
      'document_draft': 'Автоматическая подготовка черновика ускоряет следующий этап работы юриста'
    }
    return reasons[tool] || 'Этот инструмент необходим для выполнения задачи'
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

  // Одобрение плана и запуск через реальный API
  const handleApprovePlan = async () => {
    if (!workflowPlan || !pendingCaseId || !pendingWorkflow) return

    setShowPlanningPhase(false)

    try {
      // Запускаем реальное выполнение через API
      const execution = await workflowsApi.executeWorkflowWithDocs(
        pendingWorkflow.id,
        {
          case_id: pendingCaseId,
          document_ids: pendingDocuments,
          options: pendingOptions
        }
      )

      const executionId = execution.id
      try {
        const workflowLaunchContext = {
          execution_id: executionId,
          workflow_id: pendingWorkflow.id,
          workflow_name: pendingWorkflow.display_name || workflowPlan.workflow_name,
          case_id: pendingCaseId,
          return_chat_path: `/cases/${pendingCaseId}/chat`,
          document_ids: pendingDocuments,
          steps: Array.isArray(workflowPlan.steps) ? workflowPlan.steps.map((s: any, idx: number) => ({
            id: s.id || `step_${idx + 1}`,
            name: s.tool_display_name || s.name || s.tool || `Шаг ${idx + 1}`,
            tool: s.tool || s.name || `tool_${idx + 1}`,
            order: idx + 1,
          })) : [],
          started_at: new Date().toISOString(),
        }
        localStorage.setItem('pending_workflow_live_run', JSON.stringify(workflowLaunchContext))
      } catch (storageError) {
        console.error('Failed to save workflow launch context:', storageError)
      }

      toast.success('Workflow запущен. Открываю чат дела…')
      navigate(`/cases/${pendingCaseId}/chat?workflow_execution_id=${encodeURIComponent(executionId)}`)

    } catch (error) {
      console.error('Execution failed:', error)
      toast.error('Ошибка выполнения workflow')
    }
  }

  // Перегенерация плана
  const handleRegeneratePlan = async () => {
    if (!pendingWorkflow) return
    setPlanningLoading(true)
    try {
      const plan = await generateWorkflowPlan(pendingWorkflow, pendingDocuments, pendingOptions, pendingCaseId)
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

  const runningStatuses = new Set(['running', 'planning', 'executing', 'waiting_for_lawyer'])
  const runningExecutions = executions.filter(e => runningStatuses.has(e.status))
  const completedExecutions = executions.filter(e => !runningStatuses.has(e.status))

  if (loading) {
    return (
      <div className={`flex ${embedded ? 'h-full' : 'h-screen'}`} style={{ backgroundColor: 'var(--color-bg-primary)' }}>
        {!embedded && <UnifiedSidebar navItems={navItems} title="Legal AI" />}
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-8 h-8 animate-spin" style={{ color: 'var(--color-accent)' }} />
        </div>
      </div>
    )
  }

  return (
    <div className={`flex ${embedded ? 'h-full' : 'h-screen'}`} style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      {!embedded && <UnifiedSidebar navItems={navItems} title="Legal AI" />}

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
                  onRun={() => {
                    setSelectedWorkflow(workflow)
                  }}
                  onEdit={() => setEditingWorkflow(workflow)}
                  onDelete={async () => {
                    if (!confirm(`Удалить "${workflow.display_name}"?`)) return
                    try {
                      await workflowsApi.deleteDefinition(workflow.id)
                      setWorkflows(prev => prev.filter(w => w.id !== workflow.id))
                      toast.success('Workflow удалён')
                    } catch (error: any) {
                      toast.error(error.response?.data?.detail || 'Ошибка удаления')
                    }
                  }}
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
                    {/* Details button */}
                    <button
                      onClick={() => setViewingExecutionId(exec.id)}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm"
                      style={{
                        backgroundColor: 'var(--color-bg-hover)',
                        color: 'var(--color-text-primary)'
                      }}
                    >
                      <Eye className="w-4 h-4" />
                      Подробнее
                    </button>
                    {exec.status === 'completed' && (
                      <button
                        onClick={() => {
                          // Сохраняем результат и переходим в чат
                          const result: WorkflowResultData = {
                            execution_id: exec.id,
                            workflow_id: exec.definition_id || '',
                            workflow_name: exec.workflow_name || 'Workflow',
                            case_id: exec.case_id || pendingCaseId || '',
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
                          const targetCaseId = exec.case_id || pendingCaseId || caseId
                          if (targetCaseId) {
                            navigate(`/cases/${targetCaseId}/chat`)
                          } else {
                            toast.info('Не удалось открыть чат: у выполнения не найдено дело')
                          }
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
          initialCaseId={caseId}
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
            if (executionDetails && pendingCaseId) {
              const result: WorkflowResultData = {
                execution_id: executionDetails.id || `exec_${Date.now()}`,
                workflow_id: executionDetails.workflow_id || '',
                workflow_name: executionDetails.workflow_name || 'Workflow',
                case_id: pendingCaseId,
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
              navigate(`/cases/${pendingCaseId}/chat`)
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

      {/* Create / Edit Workflow Dialog */}
      {(showCreateDialog || editingWorkflow) && (
        <WorkflowFormDialog
          mode={editingWorkflow ? 'edit' : 'create'}
          workflow={editingWorkflow}
          onClose={() => {
            setShowCreateDialog(false)
            setEditingWorkflow(null)
          }}
          onSaved={(workflow) => {
            if (editingWorkflow) {
              setWorkflows(prev => prev.map(w => w.id === workflow.id ? workflow : w))
            } else {
              setWorkflows(prev => [workflow, ...prev])
            }
            setEditingWorkflow(null)
            setShowCreateDialog(false)
          }}
        />
      )}

      {/* Workflow Results View */}
      {viewingExecutionId && (
        <WorkflowResultsView
          executionId={viewingExecutionId}
          onClose={() => setViewingExecutionId(null)}
          onOpenInChat={(execId) => {
            const exec = executions.find(e => e.id === execId)
            const targetCaseId = exec?.case_id || pendingCaseId || caseId
            if (exec && targetCaseId) {
              const result: WorkflowResultData = {
                execution_id: exec.id,
                workflow_id: exec.definition_id || '',
                workflow_name: exec.workflow_name || 'Workflow',
                case_id: targetCaseId,
                status: exec.status === 'completed' ? 'completed' : 'failed',
                summary: exec.summary || `Результаты выполнения workflow "${exec.workflow_name}"`,
                documents_processed: exec.documents_processed || 0,
                elapsed_time: exec.elapsed_time || 'н/д',
                started_at: exec.started_at,
                completed_at: exec.completed_at || new Date().toISOString(),
                artifacts: exec.artifacts || { reports: [], tables: [], documents: [], checks: [] },
                results: exec.results || {},
                steps_completed: exec.total_steps_completed || 0,
                total_steps: exec.total_steps_completed || 0,
              }
              savePendingWorkflowResult(result)
              setViewingExecutionId(null)
              navigate(`/cases/${targetCaseId}/chat`)
              toast.success('Открываем результаты в чате...')
            }
          }}
          onRerun={(defId) => {
            setViewingExecutionId(null)
            const wf = workflows.find(w => w.id === defId)
            if (wf) setSelectedWorkflow(wf)
          }}
        />
      )}
    </div>
  )
}
