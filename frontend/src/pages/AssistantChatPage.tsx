import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useLocation, useNavigate } from 'react-router-dom'
import {
  FileText, X, Plus, AlignJustify, SlidersHorizontal, Sparkles,
  Search, Loader2, FolderOpen, Upload, Check, ExternalLink, Mic, MicOff,
} from 'lucide-react'
import { getCase, getApiUrl, SourceInfo, getCaseFiles, improveAssistantPrompt, extractErrorMessage } from '../services/api'
import { ChatHistoryPanel } from '../components/Chat/ChatHistoryPanel'
import { loadChatHistory, mapAssistantHistoryMessage, citationRecordToSourceInfo } from '../services/chatHistoryService'
import MessageContent from '../components/Chat/MessageContent'
import { AnswerBlocks, sourceInfosToAnswerBlockCitations } from '../components/Chat/AnswerBlocks'
import {
  ThinkingBlock,
  type ThinkingStep,
  type ToolCallInfo,
  type WorkflowPlanOutlineRow,
  type WorkflowAgentTodoItem,
} from '../components/Chat/ThinkingBlock'
import { TabularDocumentViewer } from '../components/TabularReview/TabularDocumentViewer'
import {
  consumePendingWorkflowResult,
  createWorkflowResultChatMessage,
  saveWorkflowMessageToHistory,
} from '../services/workflowResultsService'
import { toast } from 'sonner'
import { useWorkflowLiveExecution } from '../workflow/useWorkflowLiveExecution'
import { countWorkflowArtifacts, type WorkflowArtifactsPayload } from '../workflow/workflowLiveHelpers'
import { WorkflowArtifactCards } from '../components/Workflow/WorkflowArtifactCards'

// ─────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────
interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: SourceInfo[]
  reasoningSteps?: ThinkingStep[]
  toolCalls?: ToolCallInfo[]
  workflowArtifacts?: WorkflowArtifactsPayload
  workflowProgressPercent?: number
  workflowStatus?: 'running' | 'completed' | 'failed'
  workflowPlanOutline?: WorkflowPlanOutlineRow[]
  workflowAgentTodos?: WorkflowAgentTodoItem[]
  workflowPlanSource?: 'deepagents' | 'definition'
  draftPlan?: {
    title?: string
    type?: string
    template_name?: string
    user_intent_summary?: string
    template_alignment?: string
    /** Человекочитаемо: что за документ и в какой ситуации */
    document_overview?: string
    /** Что планируется изложить в сгенерированном тексте */
    planned_content?: string
    placeholder_fill_plan?: Array<{
      placeholder?: string
      marker?: string
      plan_to_fill?: string
      fill_with?: string
      what_to_fill?: string
      description?: string
      data_status?: string
      status?: string
    }>
    estimated_length?: string
    sections?: Array<{ name?: string; description?: string }>
    required_fields?: string[]
    clarifying_questions?: string[]
  }
  /** Структурированные блоки ответа (SSE answer_blocks / история). */
  answerBlocks?: Array<{ block_id: string; markdown_text: string; citation_ids: string[] }>
}

interface FileContext {
  filename: string
  text: string
  charCount: number
}

interface DraftDocument {
  title: string
  content: string
}

interface CaseFileItem {
  id: string
  filename: string
  file_type: string
}

function DraftPlanCard({
  plan,
  onApprove,
  onReject,
  onModify,
}: {
  plan: NonNullable<ChatMessage['draftPlan']>
  onApprove: () => void
  onReject: () => void
  onModify: (text: string) => void
}) {
  const [modifyOpen, setModifyOpen] = useState(false)
  const [modifyText, setModifyText] = useState('')
  return (
    <div
      className="mb-3 rounded-xl border p-4"
      style={{ borderColor: 'color-mix(in srgb, var(--color-info) 28%, var(--color-border))', backgroundColor: 'var(--color-info-bg)' }}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold" style={{ color: 'var(--color-info)' }}>План документа</h3>
        {plan.estimated_length && (
          <span className="text-xs px-2 py-0.5 rounded-md" style={{ backgroundColor: 'var(--color-info-bg)', color: 'var(--color-info)' }}>
            {plan.estimated_length}
          </span>
        )}
      </div>
      {(plan.title || plan.type) && (
        <p className="mt-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          {plan.title ? <><strong>{plan.title}</strong>{plan.type ? ` · ${plan.type}` : ''}</> : plan.type}
        </p>
      )}
      {plan.template_name?.trim() && (
        <p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>
          Шаблон: <span style={{ color: 'var(--color-text-secondary)' }}>{plan.template_name.trim()}</span>
        </p>
      )}
      {plan.user_intent_summary?.trim() && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
            Суть запроса
          </p>
          <p className="mt-1 text-sm whitespace-pre-wrap" style={{ color: 'var(--color-text-secondary)' }}>
            {plan.user_intent_summary.trim()}
          </p>
        </div>
      )}
      {plan.template_alignment?.trim() && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
            Шаблон и задача
          </p>
          <p className="mt-1 text-sm whitespace-pre-wrap" style={{ color: 'var(--color-text-secondary)' }}>
            {plan.template_alignment.trim()}
          </p>
        </div>
      )}
      {Array.isArray(plan.placeholder_fill_plan) && plan.placeholder_fill_plan.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
            Поля шаблона
          </p>
          <ul className="mt-1 max-h-48 overflow-y-auto space-y-1.5">
            {plan.placeholder_fill_plan.slice(0, 24).map((row, i) => {
              const marker = (row.placeholder || row.marker || '').trim()
              const hint =
                row.plan_to_fill || row.fill_with || row.what_to_fill || row.description || ''
              const st = (row.data_status || row.status || '').trim()
              if (!marker && !hint) return null
              return (
                <li key={i} className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  <code className="text-[11px] px-1 rounded" style={{ backgroundColor: 'var(--color-surface)' }}>{marker || '—'}</code>
                  {hint ? ` — ${hint}` : ''}
                  {st ? <span style={{ color: 'var(--color-text-muted)' }}> ({st})</span> : null}
                </li>
              )
            })}
          </ul>
        </div>
      )}
      {plan.document_overview?.trim() && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
            Что за документ
          </p>
          <p className="mt-1 text-sm whitespace-pre-wrap" style={{ color: 'var(--color-text-secondary)' }}>
            {plan.document_overview.trim()}
          </p>
        </div>
      )}
      {plan.planned_content?.trim() && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
            Что будет в тексте
          </p>
          <p className="mt-1 text-sm whitespace-pre-wrap" style={{ color: 'var(--color-text-secondary)' }}>
            {plan.planned_content.trim()}
          </p>
        </div>
      )}
      {Array.isArray(plan.sections) && plan.sections.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>Разделы</p>
          <ul className="mt-1 space-y-1">
            {plan.sections.slice(0, 6).map((s, i) => (
              <li key={i} className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                • {s.name || `Раздел ${i + 1}`}{s.description ? ` — ${s.description}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
      {Array.isArray(plan.clarifying_questions) && plan.clarifying_questions.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>Нужно уточнить</p>
          <ul className="mt-1 space-y-1">
            {plan.clarifying_questions.slice(0, 5).map((q, i) => (
              <li key={i} className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {i + 1}. {q}
              </li>
            ))}
          </ul>
        </div>
      )}
      {modifyOpen ? (
        <div className="mt-3">
          <textarea
            value={modifyText}
            onChange={(e) => setModifyText(e.target.value)}
            placeholder="Опишите, что изменить в плане…"
            className="w-full rounded-lg border px-3 py-2 text-sm"
            style={{ borderColor: 'var(--color-border-strong)' }}
            rows={3}
          />
          <div className="mt-2 flex gap-2">
            <button
              onClick={() => {
                const v = modifyText.trim()
                if (!v) return
                onModify(v)
                setModifyText('')
                setModifyOpen(false)
              }}
              className="px-3 py-1.5 rounded-lg text-xs font-medium"
              style={{ backgroundColor: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
            >
              Отправить правки
            </button>
            <button
              onClick={() => { setModifyOpen(false); setModifyText('') }}
              className="px-3 py-1.5 rounded-lg text-xs font-medium border"
              style={{ borderColor: 'var(--color-border-strong)', color: 'var(--color-accent-muted)' }}
            >
              Отмена
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex gap-2">
          <button
            onClick={onApprove}
            className="px-3 py-1.5 rounded-lg text-xs font-medium"
            style={{ backgroundColor: 'var(--color-success)', color: 'var(--color-on-accent)' }}
          >
            Одобрить и создать
          </button>
          <button
            onClick={() => setModifyOpen(true)}
            className="px-3 py-1.5 rounded-lg text-xs font-medium"
            style={{ backgroundColor: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
          >
            Изменить план
          </button>
          <button
            onClick={onReject}
            className="px-3 py-1.5 rounded-lg text-xs font-medium"
            style={{ backgroundColor: 'var(--color-error)', color: 'var(--color-on-accent)' }}
          >
            Отклонить
          </button>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────
// Case file picker modal
// ─────────────────────────────────────────────────────────
function CaseFilePickerModal({
  isOpen,
  files,
  loading,
  initialSelectedIds,
  onApply,
  onClose,
}: {
  isOpen: boolean
  files: CaseFileItem[]
  loading: boolean
  initialSelectedIds: string[]
  onApply: (ids: string[]) => void
  onClose: () => void
}) {
  const [search, setSearch] = useState('')
  const [tempSelected, setTempSelected] = useState<string[]>(initialSelectedIds)

  useEffect(() => {
    if (isOpen) {
      setTempSelected(initialSelectedIds)
      setSearch('')
    }
  }, [isOpen])

  if (!isOpen) return null

  const filtered = files.filter((f) =>
    f.filename.toLowerCase().includes(search.toLowerCase())
  )

  const toggle = (id: string) => {
    setTempSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    )
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0,0,0,0.4)' }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="bg-white rounded-xl overflow-hidden flex flex-col"
        style={{ width: '480px', maxHeight: '580px', boxShadow: '0 20px 40px rgba(0,0,0,0.15)' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>Документы дела</h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-disabled)' }}>
              Выберите документы для анализа в этом чате
            </p>
          </div>
          <button onClick={onClose} className="p-1 rounded-md hover:bg-gray-100 transition-colors">
            <X className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        {/* Search */}
        <div className="px-5 py-3 border-b border-gray-100">
          <div
            className="flex items-center gap-2 px-3 py-2 rounded-lg"
            style={{ backgroundColor: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            <Search className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-disabled)' }} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Поиск по названию..."
              className="flex-1 text-sm outline-none bg-transparent"
              style={{ color: 'var(--color-text-primary)' }}
            />
          </div>
        </div>

        {/* File list */}
        <div className="flex-1 overflow-y-auto px-2 py-2">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-5 h-5 animate-spin" style={{ color: 'var(--color-text-disabled)' }} />
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-sm" style={{ color: 'var(--color-text-disabled)' }}>
                {files.length === 0 ? 'Нет документов в деле' : 'Ничего не найдено'}
              </p>
            </div>
          ) : (
            filtered.map((f) => {
              const isSelected = tempSelected.includes(f.id)
              return (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => toggle(f.id)}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors"
                  style={{ backgroundColor: isSelected ? 'var(--color-bg-hover)' : 'transparent' }}
                >
                  <span
                    className="w-4 h-4 rounded border flex items-center justify-center flex-shrink-0"
                    style={{
                      borderColor: isSelected ? 'var(--color-accent)' : 'var(--color-border-strong)',
                      backgroundColor: isSelected ? 'var(--color-accent)' : 'transparent',
                    }}
                  >
                    {isSelected && <Check className="w-2.5 h-2.5 text-white" />}
                  </span>
                  <FileText
                    className="w-4 h-4 flex-shrink-0"
                    style={{ color: isSelected ? 'var(--color-accent)' : 'var(--color-text-disabled)' }}
                  />
                  <span
                    className="flex-1 text-sm truncate"
                    style={{ color: isSelected ? 'var(--color-accent-muted)' : 'var(--color-text-secondary)' }}
                  >
                    {f.filename}
                  </span>
                  <span className="text-xs flex-shrink-0 uppercase" style={{ color: 'var(--color-text-disabled)' }}>
                    {f.file_type}
                  </span>
                </button>
              )
            })
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-4 border-t border-gray-100">
          <span className="text-xs" style={{ color: 'var(--color-text-disabled)' }}>
            {tempSelected.length > 0 ? `Выбрано: ${tempSelected.length}` : 'Не выбрано'}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg border transition-colors hover:bg-gray-50"
              style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
            >
              Отмена
            </button>
            <button
              type="button"
              onClick={() => onApply(tempSelected)}
              className="px-4 py-2 text-sm rounded-lg font-medium text-white transition-all"
              style={{ backgroundColor: 'var(--color-text-primary)' }}
            >
              {tempSelected.length > 0 ? `Применить (${tempSelected.length})` : 'Применить'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────
// Case-specific workflows
// ─────────────────────────────────────────────────────────
const WORKFLOWS = [
  {
    id: 1,
    title: 'Ключевые сроки',
    description: 'Извлеките все важные даты и дедлайны из документов дела.',
    outputLabel: 'Результат',
    steps: 1,
    prompt: 'Какие ключевые сроки важны в этом деле?',
  },
  {
    id: 2,
    title: 'Анализ рисков',
    description: 'Выявите риски и уязвимые места в документах дела.',
    outputLabel: 'Результат',
    steps: 2,
    prompt: 'Какие риски есть в документах этого дела?',
  },
  {
    id: 3,
    title: 'Составление документа',
    description: 'Опишите нужный документ, и AI составит его с учётом контекста дела.',
    outputLabel: 'Черновик',
    steps: 2,
    prompt: 'Составь юридический документ на основе следующего описания:',
    isDraft: true,
  },
  {
    id: 4,
    title: 'Суммы и стороны',
    description: 'Извлеките суммы, стороны договора, организации из документов дела.',
    outputLabel: 'Результат',
    steps: 1,
    prompt: 'Какие суммы и стороны упоминаются в документах этого дела?',
  },
  {
    id: 5,
    title: 'Анализ договора',
    description: 'Загрузите договор и получите анализ условий, обязательств и рисков.',
    outputLabel: 'Результат',
    steps: 2,
    prompt: 'Проанализируй условия, обязательства и риски в этом договоре:',
  },
  {
    id: 6,
    title: 'Резюме дела',
    description: 'Получите краткое резюме дела с ключевыми выводами по документам.',
    outputLabel: 'Результат',
    steps: 1,
    prompt: 'Сделай краткое резюме этого дела с ключевыми выводами по документам.',
  },
]

const LEGAL_PROMPTS = [
  {
    category: 'Анализ документа',
    prompts: [
      'Проанализируй ключевые условия этого документа и выяви потенциальные риски',
      'Извлеки все важные даты, сроки и дедлайны',
      'Перечисли права и обязанности каждой из сторон',
      'Найди неоднозначные или противоречивые формулировки в тексте',
    ],
  },
  {
    category: 'Составление',
    prompts: [
      'Составь проект договора об оказании юридических услуг',
      'Напиши претензионное письмо в связи с нарушением условий договора',
      'Составь соглашение о конфиденциальности (NDA)',
    ],
  },
  {
    category: 'Резюме',
    prompts: [
      'Сделай краткое резюме дела с ключевыми выводами',
      'Определи ключевые стороны и их позиции',
      'Выдели основные риски и рекомендации',
    ],
  },
]

// ─────────────────────────────────────────────────────────
// HarveyInput — input card with case-specific settings
// ─────────────────────────────────────────────────────────
interface HarveyInputProps {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  fileContexts: FileContext[]
  uploadingFiles: string[]
  onAddFiles: (files: File[]) => void
  onRemoveContext: (idx: number) => void
  selectedCaseFiles: CaseFileItem[]
  onOpenCaseFilePicker: () => void
  onRemoveCaseFile: (id: string) => void
  isStreaming: boolean
  isDraftMode: boolean
  onSetDraftMode: (draft: boolean) => void
  isLegalResearch: boolean
  onSetLegalResearch: (v: boolean) => void
  isDeepThink: boolean
  onSetDeepThink: (v: boolean) => void
  isImprovingPrompt?: boolean
  onImprovePrompt?: () => void
  placeholder?: string
}

function HarveyInput({
  value, onChange, onSubmit,
  fileContexts, uploadingFiles, onAddFiles, onRemoveContext,
  selectedCaseFiles, onOpenCaseFilePicker, onRemoveCaseFile,
  isStreaming, isDraftMode, onSetDraftMode,
  isLegalResearch, onSetLegalResearch,
  isDeepThink, onSetDeepThink,
  isImprovingPrompt = false,
  onImprovePrompt,
  placeholder = 'Спросите что угодно о деле...',
}: HarveyInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const settingsRef = useRef<HTMLDivElement>(null)
  const filesDropdownRef = useRef<HTMLDivElement>(null)
  const promptsRef = useRef<HTMLDivElement>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [filesDropdownOpen, setFilesDropdownOpen] = useState(false)
  const [promptsOpen, setPromptsOpen] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null)

  const toggleRecording = () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) { toast.error('Голосовой ввод не поддерживается в этом браузере. Используйте Chrome.'); return }
    if (isRecording) { recognitionRef.current?.stop(); return }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const recognition: any = new SR()
    recognitionRef.current = recognition
    recognition.lang = 'ru-RU'
    recognition.continuous = false
    recognition.interimResults = false
    recognition.onstart = () => setIsRecording(true)
    recognition.onend = () => setIsRecording(false)
    recognition.onerror = () => setIsRecording(false)
    recognition.onresult = (e: any) => {
      const text = e.results[0][0].transcript
      if (text) onChange(value ? `${value} ${text}` : text)
    }
    recognition.start()
  }

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (filesDropdownRef.current && !filesDropdownRef.current.contains(e.target as Node)) {
        setFilesDropdownOpen(false)
      }
    }
    if (filesDropdownOpen) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [filesDropdownOpen])

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (promptsRef.current && !promptsRef.current.contains(e.target as Node)) {
        setPromptsOpen(false)
      }
    }
    if (promptsOpen) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [promptsOpen])

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [value])

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) {
        setSettingsOpen(false)
      }
    }
    if (settingsOpen) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [settingsOpen])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (value.trim() && !isStreaming && !isImprovingPrompt) onSubmit()
    }
  }

  const hasFiles = fileContexts.length > 0 || uploadingFiles.length > 0 || selectedCaseFiles.length > 0
  const hasActiveSettings = isDraftMode || isLegalResearch || isDeepThink

  return (
    <div className="rounded-xl border border-gray-200 bg-white" style={{ boxShadow: '0 1px 6px rgba(0,0,0,0.06)' }}>
      {/* Textarea */}
      <div className="px-4 pt-4 pb-2">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={3}
          className="w-full resize-none outline-none bg-transparent"
          style={{
            minHeight: '80px',
            fontSize: '15px',
            lineHeight: '1.6',
            color: 'var(--color-text-primary)',
            fontFamily: 'inherit',
          }}
        />
      </div>

      {/* Attached files */}
      {hasFiles && (
        <div className="px-4 pb-2 flex flex-wrap gap-2">
          {uploadingFiles.map((name) => (
            <div
              key={`uploading-${name}`}
              className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs border border-border bg-secondary"
              style={{ color: 'var(--color-accent-muted)' }}
            >
              <Loader2 className="w-3 h-3 animate-spin" />
              <span className="max-w-[140px] truncate">{name}</span>
            </div>
          ))}
          {fileContexts.map((fc, i) => (
            <div
              key={`ctx-${i}`}
              className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs border border-gray-200 bg-gray-50"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <FileText className="w-3 h-3" style={{ color: 'var(--color-success)' }} />
              <span className="max-w-[140px] truncate">{fc.filename}</span>
              <span className="text-gray-400 ml-0.5">{Math.round(fc.charCount / 1000)}k</span>
              <button onClick={() => onRemoveContext(i)} className="ml-0.5 hover:text-red-500 transition-colors">
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
          {selectedCaseFiles.map((f) => (
            <div
              key={`case-${f.id}`}
              className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs border"
              style={{ borderColor: 'var(--color-border-strong)', backgroundColor: 'var(--color-bg-hover)', color: 'var(--color-accent-muted)' }}
            >
              <FolderOpen className="w-3 h-3" />
              <span className="max-w-[140px] truncate">{f.filename}</span>
              <button onClick={() => onRemoveCaseFile(f.id)} className="ml-0.5 hover:text-red-500 transition-colors">
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center px-3 py-2 border-t border-gray-100" style={{ gap: '2px' }}>
        {/* Left tools */}
        <div className="flex items-center min-w-0 overflow-hidden" style={{ gap: '2px' }}>
          {/* Files dropdown */}
          <div ref={filesDropdownRef} className="relative flex-shrink-0">
            <button
              type="button"
              onClick={() => setFilesDropdownOpen((o) => !o)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors hover:bg-gray-50 whitespace-nowrap"
              style={{ color: selectedCaseFiles.length > 0 ? 'var(--color-accent-muted)' : 'var(--color-text-muted)' }}
            >
              <Plus className="w-3.5 h-3.5" />
              Файлы
              {selectedCaseFiles.length > 0 && (
                <span
                  className="ml-0.5 px-1.5 py-0.5 rounded-full text-xs font-medium"
                  style={{ backgroundColor: 'var(--color-bg-hover)', color: 'var(--color-accent-muted)' }}
                >
                  {selectedCaseFiles.length}
                </span>
              )}
            </button>
            {filesDropdownOpen && (
              <div
                className="absolute bottom-full mb-1 left-0 bg-white rounded-lg border border-gray-200 overflow-hidden z-50"
                style={{ minWidth: '210px', boxShadow: '0 4px 16px rgba(0,0,0,0.10)' }}
              >
                <button
                  type="button"
                  onClick={() => { fileInputRef.current?.click(); setFilesDropdownOpen(false) }}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm hover:bg-gray-50 transition-colors text-left"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  <Upload className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--color-text-disabled)' }} />
                  Загрузить с компьютера
                </button>
                <button
                  type="button"
                  onClick={() => { onOpenCaseFilePicker(); setFilesDropdownOpen(false) }}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm hover:bg-gray-50 transition-colors text-left"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  <FolderOpen className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--color-text-disabled)' }} />
                  Из документов дела
                </button>
              </div>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
                  accept=".pdf,.docx,.txt,.csv,.xlsx,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.gif"
            className="hidden"
            onChange={(e) => {
              if (e.target.files) {
                onAddFiles(Array.from(e.target.files))
                e.target.value = ''
              }
            }}
          />

          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            disabled={isStreaming || isImprovingPrompt || !value.trim()}
            onClick={() => onImprovePrompt?.()}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors flex-shrink-0 whitespace-nowrap disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-50"
            style={{ color: 'var(--color-text-muted)' }}
            aria-label="Улучшить формулировку запроса"
          >
            {isImprovingPrompt ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />
            ) : (
              <Sparkles className="w-3.5 h-3.5" aria-hidden />
            )}
            Улучшить
          </button>
        </div>

        {/* Prompts dropdown — outside overflow-hidden so popup is not clipped */}
        <div ref={promptsRef} className="relative flex-shrink-0">
          <button
            type="button"
            onClick={() => setPromptsOpen((o) => !o)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors whitespace-nowrap"
            style={{
              color: 'var(--color-text-muted)',
              backgroundColor: promptsOpen ? 'var(--color-bg-tertiary)' : undefined,
            }}
          >
            <AlignJustify className="w-3.5 h-3.5" />
            Промпты
          </button>

          {promptsOpen && (
            <div
              className="absolute bottom-full mb-1.5 left-0 bg-white rounded-lg border border-gray-200 z-50 overflow-y-auto"
              style={{ width: '300px', maxHeight: '220px', boxShadow: '0 4px 16px rgba(0,0,0,0.10)' }}
            >
              {LEGAL_PROMPTS.map((group) => (
                <div key={group.category}>
                  <div
                    className="px-3 py-1 text-xs font-medium border-b border-gray-100"
                    style={{ color: 'var(--color-text-disabled)', backgroundColor: 'var(--color-bg-secondary)' }}
                  >
                    {group.category}
                  </div>
                  {group.prompts.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => {
                        onChange(prompt)
                        setPromptsOpen(false)
                      }}
                      className="w-full text-left px-3 py-1.5 text-sm hover:bg-gray-50 transition-colors border-b border-gray-50"
                      style={{ color: 'var(--color-text-secondary)' }}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Settings dropdown — outside overflow-hidden */}
        <div ref={settingsRef} className="relative flex-shrink-0">
          <button
            type="button"
            onClick={() => setSettingsOpen((o) => !o)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors whitespace-nowrap"
            style={{
              color: hasActiveSettings ? 'var(--color-accent)' : 'var(--color-text-muted)',
              backgroundColor: settingsOpen ? 'var(--color-bg-tertiary)' : undefined,
            }}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            Настройки
            {hasActiveSettings && (
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 ml-0.5 flex-shrink-0" />
            )}
          </button>

          {settingsOpen && (
            <div
              className="absolute bottom-full mb-1.5 left-0 bg-white rounded-lg border border-gray-200 overflow-hidden z-50"
              style={{ minWidth: '160px', boxShadow: '0 4px 16px rgba(0,0,0,0.10)' }}
            >
              {/* Mode section */}
              <div className="px-2.5 py-1.5 text-xs font-medium border-b border-gray-100" style={{ color: 'var(--color-text-disabled)' }}>
                Режим
              </div>
              <button
                type="button"
                onClick={() => { onSetDraftMode(false); setSettingsOpen(false) }}
                className="w-full flex items-center gap-2 px-2.5 py-2 text-sm transition-colors"
                style={{
                  color: !isDraftMode ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
                  backgroundColor: !isDraftMode ? 'var(--color-bg-secondary)' : 'transparent',
                  fontWeight: !isDraftMode ? 500 : 400,
                }}
              >
                <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: !isDraftMode ? 'var(--color-text-primary)' : 'var(--color-border-strong)' }} />
                Ask
              </button>
              <button
                type="button"
                onClick={() => { onSetDraftMode(true); setSettingsOpen(false) }}
                className="w-full flex items-center gap-2 px-2.5 py-2 text-sm transition-colors"
                style={{
                  color: isDraftMode ? 'var(--color-accent)' : 'var(--color-text-muted)',
                  backgroundColor: isDraftMode ? 'var(--color-bg-hover)' : 'transparent',
                  fontWeight: isDraftMode ? 500 : 400,
                }}
              >
                <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: isDraftMode ? 'var(--color-accent)' : 'var(--color-border-strong)' }} />
                Draft
              </button>

              {/* Tools section */}
              <div className="px-2.5 py-1.5 text-xs font-medium border-t border-b border-gray-100" style={{ color: 'var(--color-text-disabled)' }}>
                Инструменты
              </div>
              <button
                type="button"
                onClick={() => onSetLegalResearch(!isLegalResearch)}
                className="w-full flex items-center gap-2 px-2.5 py-2 text-sm transition-colors"
                style={{
                  color: isLegalResearch ? 'var(--color-success)' : 'var(--color-text-muted)',
                  backgroundColor: isLegalResearch ? 'var(--color-success-bg)' : 'transparent',
                }}
              >
                <span
                  className="w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0"
                  style={{
                    borderColor: isLegalResearch ? 'var(--color-success)' : 'var(--color-border-strong)',
                    backgroundColor: isLegalResearch ? 'var(--color-success)' : 'transparent',
                  }}
                >
                  {isLegalResearch && <span className="text-white" style={{ fontSize: '9px' }}>✓</span>}
                </span>
                Pravo.gov.ru
              </button>
              <button
                type="button"
                onClick={() => onSetDeepThink(!isDeepThink)}
                className="w-full flex items-center gap-2 px-2.5 py-2 text-sm transition-colors"
                style={{
                  color: isDeepThink ? 'var(--color-info)' : 'var(--color-text-muted)',
                  backgroundColor: isDeepThink ? 'var(--color-info-bg)' : 'transparent',
                }}
              >
                <span
                  className="w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0"
                  style={{
                    borderColor: isDeepThink ? 'var(--color-info)' : 'var(--color-border-strong)',
                    backgroundColor: isDeepThink ? 'var(--color-info)' : 'transparent',
                  }}
                >
                  {isDeepThink && <span className="text-white" style={{ fontSize: '9px' }}>✓</span>}
                </span>
                Deep Think
              </button>
            </div>
          )}
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Mic button */}
        {!isStreaming && (
          <button
            type="button"
            onClick={toggleRecording}
            className="flex items-center justify-center w-8 h-8 rounded-lg transition-colors flex-shrink-0"
            style={{ backgroundColor: isRecording ? 'var(--color-error-bg)' : 'transparent', color: isRecording ? 'var(--color-error)' : 'var(--color-text-disabled)' }}
          >
            {isRecording ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
          </button>
        )}

        {/* Send button */}
        <div className="flex-shrink-0">
          <button
            type="button"
            onClick={onSubmit}
            disabled={!value.trim() || isStreaming}
            className="flex items-center justify-center px-4 py-1.5 text-sm font-medium text-white rounded-lg transition-all disabled:opacity-40"
            style={{ backgroundColor: 'var(--color-text-primary)', minWidth: '80px' }}
          >
            {isStreaming ? (
              <div
                className="w-4 h-4 border-2 rounded-full animate-spin"
                style={{ borderColor: 'rgba(255,255,255,0.3)', borderTopColor: 'var(--color-on-accent)' }}
              />
            ) : (
              'Отправить'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────
const AssistantChatPage = () => {
  const { caseId } = useParams<{ caseId: string }>()
  const location = useLocation()
  const navigate = useNavigate()

  const [question, setQuestion] = useState('')
  const [fileContexts, setFileContexts] = useState<FileContext[]>([])
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [isDraftMode, setIsDraftMode] = useState(false)
  const [isLegalResearch, setIsLegalResearch] = useState(false)
  const [isDeepThink, setIsDeepThink] = useState(false)
  const [isImprovingPrompt, setIsImprovingPrompt] = useState(false)
  const [draftDocument, setDraftDocument] = useState<DraftDocument | null>(null)
  const [draftDocId, setDraftDocId] = useState<string | null>(null)

  const [historyPanelOpen, setHistoryPanelOpen] = useState(false)
  const [caseTitle, setCaseTitle] = useState<string>('')
  const [loadingSession, setLoadingSession] = useState(false)

  // Case file picker
  const [selectedCaseFileIds, setSelectedCaseFileIds] = useState<string[]>([])
  const [availableCaseFiles, setAvailableCaseFiles] = useState<CaseFileItem[]>([])
  const [caseFilesLoaded, setCaseFilesLoaded] = useState(false)
  const [showCaseFilePicker, setShowCaseFilePicker] = useState(false)
  const [loadingCaseFiles, setLoadingCaseFiles] = useState(false)
  const [viewerSource, setViewerSource] = useState<SourceInfo | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const workflowResultProcessed = useRef(false)

  const caseChatPath = caseId ? `/cases/${caseId}/chat` : '/cases'
  const [artifactReturnPath, setArtifactReturnPath] = useState(caseChatPath)
  const onWorkflowReturnPath = useCallback((path: string) => {
    setArtifactReturnPath(path)
  }, [])

  useWorkflowLiveExecution({
    locationSearch: location.search,
    setMessages,
    setIsStreaming,
    onReturnPath: onWorkflowReturnPath,
    defaultReturnChatPath: caseChatPath,
  })

  // Load case info
  useEffect(() => {
    if (!caseId) return
    getCase(caseId)
      .then((d) => setCaseTitle(d.title || ''))
      .catch(() => {})
  }, [caseId])

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Handle pending workflow result
  useEffect(() => {
    const timer = setTimeout(async () => {
      if (workflowResultProcessed.current) return
      const pendingResult = consumePendingWorkflowResult()
      if (pendingResult && pendingResult.case_id === caseId) {
        workflowResultProcessed.current = true
        const message = createWorkflowResultChatMessage(pendingResult)
        setMessages([{ role: 'assistant', content: message.content }])
        try {
          await saveWorkflowMessageToHistory(pendingResult)
        } catch {}
        if (pendingResult.status === 'completed') {
          toast.success(`✨ Workflow "${pendingResult.workflow_name}" завершён!`, {
            description: `Обработано ${pendingResult.documents_processed} документов за ${pendingResult.elapsed_time}`,
            duration: 5000,
          })
        } else {
          toast.error(`Workflow "${pendingResult.workflow_name}" завершён с ошибкой`, {
            description: pendingResult.error || 'Неизвестная ошибка',
            duration: 5000,
          })
        }
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [caseId])

  // Handle autoQuery from navigation state (e.g. from GlobalAssistantPage)
  useEffect(() => {
    const autoQuery: string = (location.state as any)?.autoQuery || ''
    if (autoQuery) {
      setQuestion(autoQuery)
    }
  }, [])

  // Auto-load session from ?session= URL param (e.g. from recent actions on case overview)
  useEffect(() => {
    if (!caseId) return
    const params = new URLSearchParams(location.search)
    const sessionParam = params.get('session')
    if (sessionParam) {
      setLoadingSession(true)
      loadChatHistory(caseId, sessionParam)
        .then((history) => {
          setMessages(history.map((m) => mapAssistantHistoryMessage(m)))
          setSessionId(sessionParam)
        })
        .catch(() => {})
        .finally(() => setLoadingSession(false))
    }
  }, [caseId, location.search])

  // Прогрев графа/чекпоинта при открытии чата по делу (меньше задержка первого сообщения)
  useEffect(() => {
    if (!caseId) return
    const token = localStorage.getItem('access_token')
    if (!token) return

    const params = new URLSearchParams(location.search)
    const sessionFromUrl = params.get('session')
    const sid = sessionFromUrl || sessionId || undefined

    let cancelled = false
    const t = window.setTimeout(async () => {
      if (cancelled) return
      try {
        const res = await fetch(getApiUrl('/api/v2/assistant/chat/warmup'), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            case_id: caseId,
            ...(sid ? { session_id: sid } : {}),
          }),
        })
        if (cancelled || !res.ok) return
        const data = (await res.json()) as { session_id?: string }
        // Не перетираем session_id после «Новый чат» (уже задан в state)
        if (data.session_id && !sessionFromUrl && !sessionId) {
          setSessionId((prev) => prev ?? data.session_id!)
        }
      } catch {
        /* ignore */
      }
    }, 250)

    return () => {
      cancelled = true
      window.clearTimeout(t)
    }
  }, [caseId, location.search, sessionId])

  // ── File upload ──
  const handleAddFiles = async (newFiles: File[]) => {
    const token = localStorage.getItem('access_token')
    for (const file of newFiles) {
      setUploadingFiles((prev) => [...prev, file.name])
      try {
        const formData = new FormData()
        formData.append('file', file)
        const res = await fetch(getApiUrl('/api/v2/assistant/upload-file'), {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: formData,
        })
        if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
        const data: FileContext = await res.json()
        setFileContexts((prev) => [...prev, data])
      } catch (err) {
        console.error('File upload error:', err)
        toast.error(`Не удалось загрузить файл ${file.name}`)
      } finally {
        setUploadingFiles((prev) => prev.filter((n) => n !== file.name))
      }
    }
  }

  const handleRemoveContext = (idx: number) => {
    setFileContexts((prev) => prev.filter((_, i) => i !== idx))
  }

  // ── Case file picker ──
  const handleOpenCaseFilePicker = async () => {
    setShowCaseFilePicker(true)
    if (!caseFilesLoaded && caseId) {
      setLoadingCaseFiles(true)
      try {
        const result = await getCaseFiles(caseId)
        setAvailableCaseFiles(
          result.files.map((f) => ({
            id: f.id,
            filename: f.filename,
            file_type: f.file_type || '',
          }))
        )
        setCaseFilesLoaded(true)
      } catch {}
      setLoadingCaseFiles(false)
    }
  }

  const selectedCaseFiles: CaseFileItem[] = availableCaseFiles.filter((f) =>
    selectedCaseFileIds.includes(f.id)
  )

  const handleImprovePrompt = useCallback(async () => {
    const draft = question.trim()
    if (!draft || isStreaming || isImprovingPrompt) return
    setIsImprovingPrompt(true)
    try {
      const improved = await improveAssistantPrompt(draft)
      if (improved) setQuestion(improved)
      else toast.error('Не удалось получить улучшенный текст')
    } catch (e) {
      toast.error(extractErrorMessage(e))
    } finally {
      setIsImprovingPrompt(false)
    }
  }, [question, isStreaming, isImprovingPrompt])

  const resolveConversationMode = (): 'research' | 'case_advice' | 'drafting' | 'review' | 'comparison' | 'clarify' => {
    if (isDraftMode) return 'drafting'
    if (isLegalResearch) return 'research'
    if (isDeepThink) return 'case_advice'
    return 'case_advice'
  }

  // ── Send message ──
  const handleSubmit = async (
    overrideText?: unknown,
    options?: { draftAction?: 'approve' | 'reject' },
  ) => {
    // Может вызываться как onSubmit(event) и как handleSubmit("текст").
    if (overrideText && typeof overrideText === 'object' && 'preventDefault' in (overrideText as any)) {
      ;(overrideText as any).preventDefault?.()
    }
    const rawText = typeof overrideText === 'string' ? overrideText : question
    let text = String(rawText ?? '').trim()
    if (options?.draftAction === 'approve' && !text) text = 'Одобрить план'
    if (options?.draftAction === 'reject' && !text) text = 'отмена'
    if (!text || isStreaming) return

    const contextsToSend = [...fileContexts]
    const currentDraft = draftDocument
    setQuestion('')
    // fileContexts are kept for the whole session — files stay available for follow-up messages

    const userMsg: ChatMessage = { role: 'user', content: text }
    const allMessages = [...messages, userMsg]
    setMessages([...allMessages, { role: 'assistant', content: '' }])
    setIsStreaming(true)

    abortRef.current?.abort()
    abortRef.current = new AbortController()

    if (isDraftMode) {
      // Сбрасываем флаг готовности: "Документ создан" показываем только после real document_created
      setDraftDocument(null)
      setDraftDocId(null)
    }

    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(getApiUrl('/api/v2/assistant/chat'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          case_id: caseId,
          mode: resolveConversationMode(),
          messages: allMessages.map((m) => ({ role: m.role, content: m.content })),
          session_id: sessionId,
          file_contexts: contextsToSend.map((fc) => ({ filename: fc.filename, text: fc.text })),
          web_search: false,
          legal_research: isLegalResearch,
          deep_think: isDeepThink,
          draft_mode: isDraftMode,
          ...(options?.draftAction ? { draft_action: options.draftAction } : {}),
          document_context: isDraftMode && currentDraft ? currentDraft.content : undefined,
          attached_file_ids: selectedCaseFileIds.length > 0 ? selectedCaseFileIds : undefined,
        }),
        signal: abortRef.current.signal,
      })

      if (!response.ok) throw new Error(`Server error: ${response.status}`)

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let assistantContent = ''
      let buffer = ''

      const processSSELine = (line: string) => {
        if (!line.startsWith('data: ')) return
        const raw = line.slice(6).trim()
        if (!raw) return
        try {
          const data = JSON.parse(raw)
          if (data.session_id && !sessionId) {
            setSessionId(data.session_id)
          } else if (data.type === 'citations' && Array.isArray(data.citations)) {
            const sources: SourceInfo[] = data.citations.map((c: unknown) =>
              citationRecordToSourceInfo(c as Record<string, unknown>)
            )
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              return [...prev.slice(0, -1), { ...last, sources }]
            })
          } else if (data.type === 'answer_blocks' && Array.isArray(data.blocks)) {
            const answerBlocks = data.blocks.map((b: Record<string, unknown>) => ({
              block_id: String(b.block_id ?? ''),
              markdown_text: String(b.markdown_text ?? ''),
              citation_ids: Array.isArray(b.citation_ids)
                ? (b.citation_ids as unknown[]).map((x) => String(x))
                : [],
            }))
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              return [...prev.slice(0, -1), { ...last, answerBlocks }]
            })
          } else if (data.type === 'reasoning' && data.phase && data.content) {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last.role !== 'assistant') return prev
              const currentSteps = last.reasoningSteps || []
              const newStep: ThinkingStep = {
                phase: data.phase,
                step: data.step ?? data.stepNumber ?? currentSteps.length + 1,
                totalSteps: data.totalSteps ?? data.totalStepsNumber ?? 4,
                content: data.content,
              }
              const stepIndex = currentSteps.findIndex(
                (s) => s.phase === newStep.phase && s.step === newStep.step
              )
              const reasoningSteps =
                stepIndex >= 0
                  ? currentSteps.map((s, i) => (i === stepIndex ? newStep : s))
                  : [...currentSteps, newStep]
              return [...prev.slice(0, -1), { ...last, reasoningSteps }]
            })
          } else if (data.type === 'draft_plan' && data.plan) {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (!last || last.role !== 'assistant') return prev
              return [...prev.slice(0, -1), { ...last, draftPlan: data.plan }]
            })
          } else if (data.type === 'tool_call' && data.name) {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last.role !== 'assistant') return prev
              const toolCalls = last.toolCalls || []
              if (data.status === 'running') {
                return [
                  ...prev.slice(0, -1),
                  {
                    ...last,
                    toolCalls: [
                      ...toolCalls,
                      {
                        name: data.name,
                        status: 'running',
                        input: typeof data.input === 'string' ? data.input : JSON.stringify(data.input ?? ''),
                      },
                    ],
                  },
                ]
              }
              let idx = -1
              for (let i = toolCalls.length - 1; i >= 0; i--) {
                if (toolCalls[i].name === data.name && toolCalls[i].status === 'running') {
                  idx = i
                  break
                }
              }
              const updated = [...toolCalls]
              if (idx >= 0) {
                updated[idx] = {
                  ...updated[idx],
                  status: data.status === 'error' ? 'error' : 'completed',
                  output: data.output,
                }
                return [...prev.slice(0, -1), { ...last, toolCalls: updated }]
              }
              return [
                ...prev.slice(0, -1),
                {
                  ...last,
                  toolCalls: [
                    ...toolCalls,
                    {
                      name: data.name,
                      status: data.status === 'error' ? 'error' : 'completed',
                      output: data.output,
                    },
                  ],
                },
              ]
            })
          } else if (data.error) {
            assistantContent = `Ошибка: ${data.error}`
            setMessages((prev) => [
              ...prev.slice(0, -1),
              { role: 'assistant', content: assistantContent },
            ])
          } else if (
            (data.type === 'document_created' && data.document) ||
            (data.type === 'document-card' && data.data)
          ) {
            const doc = data.document || data.data
            const docId = doc.id
            const docTitle = doc.title || 'Черновик'
            setDraftDocId(docId)
            setDraftDocument({ title: docTitle, content: '' })
          } else if (data.type === 'content_sync' && typeof data.content === 'string') {
            // Финальный текст узла графа после sanitize — подменяем накопленный стрим (убирает утечки/дубли).
            assistantContent = data.content
            if (!isDraftMode) {
              setMessages((prev) => {
                const last = prev[prev.length - 1]
                return [...prev.slice(0, -1), { ...last, role: 'assistant', content: assistantContent }]
              })
            }
          } else if (data.textDelta) {
            assistantContent += data.textDelta
            if (!isDraftMode) {
              // Preserve sources if already set (citations can arrive before last textDelta in some edge cases)
              setMessages((prev) => {
                const last = prev[prev.length - 1]
                return [...prev.slice(0, -1), { ...last, role: 'assistant', content: assistantContent }]
              })
            }
          }
        } catch {}
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          // Flush remaining buffer on stream end
          if (buffer) {
            for (const line of buffer.split('\n')) processSSELine(line)
          }
          break
        }
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) processSSELine(line)
      }
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        setMessages((prev) => [
          ...prev.slice(0, -1),
          { role: 'assistant', content: 'Произошла ошибка. Попробуйте ещё раз.' },
        ])
      }
    } finally {
      setIsStreaming(false)
    }
  }

  // ── Open draft in case document editor ──
  const handleOpenInEditor = async () => {
    if (!caseId) return
    // If backend already created the document, navigate directly
    if (draftDocId) {
      navigate(`/cases/${caseId}/editor/${draftDocId}`)
      return
    }
    // Fallback: shouldn't happen, but handle gracefully
    toast.error('Документ ещё не готов')
  }

  // ── Open citation in document viewer (or quote popup for direct uploads) ──
  const handleCitationClick = (source: SourceInfo) => {
    // External sources (pravo.gov.ru etc.) — open in new tab, never local viewer
    if (source.source_type === 'external' || (source.url && source.url.startsWith('http'))) {
      if (source.url) {
        window.open(source.url, '_blank', 'noopener,noreferrer')
      }
      return
    }
    // Some payloads may miss source_id; try to recover it from case file list by filename.
    // Without source_id, the viewer may open the "default" document, which looks like a wrong first link.
    if (!source.source_id && source.file && availableCaseFiles.length > 0) {
      const match = availableCaseFiles.find((f) => f.filename === source.file)
      if (match?.id) {
        setViewerSource({ ...source, source_id: match.id, case_id: source.case_id ?? caseId ?? undefined })
        return
      }
    }
    setViewerSource(source)
  }

  // ── New chat ──
  const handleNewChat = () => {
    abortRef.current?.abort()
    setMessages([])
    setQuestion('')
    setFileContexts([])
    setSelectedCaseFileIds([])
    // Новый UUID = новый LangGraph thread; иначе бэкенд цепляется к последней сессии дела (<30 мин)
    setSessionId(crypto.randomUUID())
    setIsDraftMode(false)
    setDraftDocument(null)
    setDraftDocId(null)
    if (caseId) {
      navigate(`/cases/${caseId}/chat`, { replace: true })
      setArtifactReturnPath(`/cases/${caseId}/chat`)
    }
  }

  // ── Load history session ──
  const handleLoadHistory = async (histSessionId?: string) => {
    if (!caseId) return
    try {
      const history = await loadChatHistory(caseId, histSessionId)
      setMessages(history.map((m) => mapAssistantHistoryMessage(m)))
      if (histSessionId) setSessionId(histSessionId)
    } catch {
      toast.error('Не удалось загрузить историю')
    }
  }

  if (!caseId) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Дело не найдено</p>
      </div>
    )
  }

  const sessionParam = new URLSearchParams(location.search).get('session')
  const workflowExecParam = new URLSearchParams(location.search).get('workflow_execution_id')
  const chatActive = messages.length > 0 || loadingSession || !!sessionParam || !!workflowExecParam

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Breadcrumb — always visible */}
      <div
        className="flex items-center gap-1.5 text-sm px-6 pt-3 pb-1 shrink-0"
        style={{
          color: 'var(--color-text-muted)',
          backgroundColor: chatActive ? 'var(--color-bg-elevated)' : 'var(--color-bg-secondary)',
        }}
      >
        <button onClick={() => navigate('/cases')} className="hover:underline transition-colors" style={{ color: 'var(--color-text-muted)' }}>Дела</button>
        <span>/</span>
        <button onClick={() => navigate(`/cases/${caseId}`)} className="hover:underline transition-colors" style={{ color: 'var(--color-text-muted)' }}>{caseTitle || '...'}</button>
        <span>/</span>
        <span>Ассистент</span>
      </div>

      {chatActive ? (
        // ── Chat view ──
        <>
          {/* Header */}
          <div
            className="flex items-center justify-between px-6 py-3 border-b shrink-0"
            style={{ borderBottomColor: 'var(--color-border)' }}
          >
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium" style={{ color: 'var(--color-text-muted)' }}>
                Ассистент
              </span>
              {caseTitle && (
                <span className="text-sm" style={{ color: 'var(--color-text-disabled)' }}>
                  · {caseTitle}
                </span>
              )}
              {isDraftMode && (
                <span
                  className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                  style={{ backgroundColor: 'var(--color-bg-hover)', color: 'var(--color-accent)', border: '1px solid var(--color-border-strong)' }}
                >
                  <span className="w-1.5 h-1.5 rounded-full inline-block bg-accent-muted" />
                  Draft
                </span>
              )}
              {isLegalResearch && (
                <span
                  className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                  style={{
                    backgroundColor: 'var(--color-success-bg)',
                    color: 'var(--color-success)',
                    border: '1px solid color-mix(in srgb, var(--color-success) 35%, var(--color-border))',
                  }}
                >
                  Pravo.gov.ru
                </span>
              )}
              {isDeepThink && (
                <span
                  className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                  style={{
                    backgroundColor: 'var(--color-info-bg)',
                    color: 'var(--color-info)',
                    border: '1px solid color-mix(in srgb, var(--color-info) 22%, var(--color-border))',
                  }}
                >
                  Deep Think
                </span>
              )}
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={handleNewChat}
                className="flex items-center gap-1.5 text-sm font-medium transition-opacity hover:opacity-70"
                style={{ color: 'var(--color-text-muted)' }}
              >
                <Plus className="w-4 h-4" />
                Новый чат
              </button>
            </div>
          </div>

          {/* Body: chat + optional document panel */}
          <div className="flex-1 flex overflow-hidden">
            {/* Chat column */}
            <div
              className="flex flex-col overflow-hidden transition-all duration-300"
              style={{ width: viewerSource ? '45%' : '100%' }}
            >
              <div className="flex-1 overflow-y-auto">
                <div style={{ maxWidth: '960px', margin: '0 auto' }} className="px-6 py-8 space-y-6">
                  {loadingSession && messages.length === 0 && (
                    <div className="flex items-center justify-center py-16">
                      <div className="flex gap-1">
                        {[0, 1, 2].map((i) => (
                          <div
                            key={i}
                            className="w-2 h-2 rounded-full animate-bounce"
                            style={{ backgroundColor: 'var(--color-text-muted)', animationDelay: `${i * 150}ms` }}
                          />
                        ))}
                      </div>
                    </div>
                  )}
                  {messages.map((msg, idx) => {
                    const wfArtifactN = msg.role === 'assistant' ? countWorkflowArtifacts(msg.workflowArtifacts) : 0
                    const assistantTextBody =
                      msg.role === 'assistant'
                        ? (msg.content && msg.content.trim()) ||
                          (wfArtifactN > 0 ? 'Готово. Откройте нужный результат ниже.' : '')
                        : ''
                    const showAssistantTextBody = msg.role === 'assistant' && Boolean(assistantTextBody)
                    /** Не подменять стрим markdown блоками Phase 2 — иначе весь текст визуально исчезает и рисуется заново из `AnswerBlocks`. */
                    const hasStreamedAssistantMarkdown = Boolean(
                      msg.role === 'assistant' && msg.content && msg.content.trim().length > 0,
                    )
                    const showAnswerBlocks =
                      msg.role === 'assistant' &&
                      (msg.answerBlocks?.length ?? 0) > 0 &&
                      !hasStreamedAssistantMarkdown
                    return (
                    <div key={idx} className={msg.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                      {msg.role === 'user' ? (
                        <div
                          className="max-w-[75%] px-4 py-3 rounded-2xl text-sm leading-relaxed"
                          style={{
                            backgroundColor: 'var(--color-user-message-bg)',
                            color: 'var(--color-user-message-text)',
                            fontFamily: 'var(--font-body)',
                          }}
                        >
                          {msg.content}
                        </div>
                      ) : (
                        <div className="max-w-[90%] w-full text-sm">
                          {((msg.toolCalls && msg.toolCalls.length > 0) ||
                            (msg.workflowPlanOutline && msg.workflowPlanOutline.length > 0) ||
                            (msg.workflowAgentTodos && msg.workflowAgentTodos.length > 0) ||
                            msg.workflowStatus === 'running' ||
                            (isStreaming && idx === messages.length - 1 && !msg.content)) && (
                            <div className="mb-3">
                              <ThinkingBlock
                                steps={msg.reasoningSteps || []}
                                toolCalls={msg.toolCalls}
                                planOutline={msg.workflowPlanOutline}
                                planOutlineTitle={
                                  msg.workflowPlanSource === 'deepagents'
                                    ? 'План и подзадачи (Deep Agents)'
                                    : undefined
                                }
                                agentTodos={msg.workflowAgentTodos}
                                isStreaming={
                                  isStreaming &&
                                  idx === messages.length - 1 &&
                                  (!msg.content || msg.workflowStatus === 'running')
                                }
                                progressPercent={msg.workflowProgressPercent}
                                workflowStatus={msg.workflowStatus}
                                defaultOpen
                              />
                            </div>
                          )}
                          {msg.draftPlan && (
                            <DraftPlanCard
                              plan={msg.draftPlan}
            onApprove={() => { void handleSubmit('Одобрить план', { draftAction: 'approve' }) }}
            onReject={() => { void handleSubmit('отмена', { draftAction: 'reject' }) }}
            onModify={(text) => { void handleSubmit(text) }}
                            />
                          )}
                          {showAnswerBlocks ? (
                            <AnswerBlocks
                              blocks={msg.answerBlocks!}
                              citations={sourceInfosToAnswerBlockCitations(msg.sources || [])}
                              onCitationClick={handleCitationClick}
                              isStreaming={isStreaming && idx === messages.length - 1}
                            />
                          ) : showAssistantTextBody ? (
                            <MessageContent
                              content={assistantTextBody}
                              sources={msg.sources || []}
                              answerBlocks={msg.answerBlocks}
                              onCitationClick={handleCitationClick}
                              isStreaming={isStreaming && idx === messages.length - 1}
                            />
                          ) : (
                            isStreaming && idx === messages.length - 1 && !isDraftMode && (
                              <div className="flex gap-1">
                                {[0, 1, 2].map((i) => (
                                  <div
                                    key={i}
                                    className="w-1.5 h-1.5 rounded-full animate-bounce"
                                    style={{ backgroundColor: 'var(--color-text-muted)', animationDelay: `${i * 150}ms` }}
                                  />
                                ))}
                              </div>
                            )
                          )}
                          {msg.workflowArtifacts && (
                            <WorkflowArtifactCards
                              artifacts={msg.workflowArtifacts}
                              navigate={navigate}
                              returnChatPath={artifactReturnPath || caseChatPath}
                            />
                          )}
                          {/* Draft indicator */}
                          {isDraftMode && idx === messages.length - 1 && (
                            isStreaming ? (
                              <div className="flex items-center gap-2 mt-1">
                                <Loader2 className="w-3.5 h-3.5 animate-spin" style={{ color: 'var(--color-accent-muted)' }} />
                                <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Создаю документ...</span>
                              </div>
                            ) : draftDocId && draftDocument ? (
                              <div className="flex flex-col gap-2 mt-1">
                                <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                                  Готово! Документ{draftDocument.title ? ` «${draftDocument.title}»` : ''} создан.
                                </p>
                                <button
                                  onClick={handleOpenInEditor}
                                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors self-start"
                                  style={{
                                    border: '1px solid var(--color-border)',
                                    backgroundColor: 'var(--color-bg-hover)',
                                    color: 'var(--color-accent)',
                                  }}
                                >
                                  <ExternalLink className="w-3.5 h-3.5" />
                                  Перейти в редактор
                                </button>
                              </div>
                            ) : null
                          )}
                        </div>
                      )}
                    </div>
                    )
                  })}
                  <div ref={messagesEndRef} />
                </div>
              </div>

              <div className="shrink-0 px-6 py-4 border-t" style={{ borderTopColor: 'var(--color-border)' }}>
                <div style={{ maxWidth: '960px', margin: '0 auto' }}>
                  <HarveyInput
                    value={question}
                    onChange={setQuestion}
                    onSubmit={handleSubmit}
                    fileContexts={fileContexts}
                    uploadingFiles={uploadingFiles}
                    onAddFiles={handleAddFiles}
                    onRemoveContext={handleRemoveContext}
                    selectedCaseFiles={selectedCaseFiles}
                    onOpenCaseFilePicker={handleOpenCaseFilePicker}
                    onRemoveCaseFile={(id) => setSelectedCaseFileIds((prev) => prev.filter((x) => x !== id))}
                    isStreaming={isStreaming}
                    isDraftMode={isDraftMode}
                    onSetDraftMode={setIsDraftMode}
                    isLegalResearch={isLegalResearch}
                    onSetLegalResearch={setIsLegalResearch}
                    isDeepThink={isDeepThink}
                    onSetDeepThink={setIsDeepThink}
                    isImprovingPrompt={isImprovingPrompt}
                    onImprovePrompt={handleImprovePrompt}
                  />
                </div>
              </div>
            </div>

            {/* Document viewer panel — slides in from right when citation clicked */}
            {viewerSource && (
              <div
                className="flex flex-col border-l overflow-hidden transition-all duration-300"
                style={{ width: '55%', borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-elevated)' }}
              >
                <div className="flex items-center justify-between px-4 py-2 border-b shrink-0" style={{ borderColor: 'var(--color-border)' }}>
                  <span className="text-sm font-medium truncate" style={{ color: 'var(--color-text-secondary)' }}>
                    {viewerSource.file || 'Документ'}
                  </span>
                  <button
                    onClick={() => setViewerSource(null)}
                    className="p-1.5 rounded-full hover:bg-gray-100 transition-colors"
                  >
                    <X className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
                  </button>
                </div>

                {viewerSource.source_id && caseId ? (
                  <TabularDocumentViewer
                    key={
                      viewerSource.citation_id ||
                      [
                        viewerSource.source_id,
                        viewerSource.page ?? 'p',
                        viewerSource.chunk_id ?? 'c',
                        viewerSource.char_start ?? 's',
                        viewerSource.char_end ?? 'e',
                      ].join(':')
                    }
                    fileId={viewerSource.source_id}
                    caseId={caseId}
                    fileType={
                      viewerSource.file?.toLowerCase().endsWith('.pdf') ? 'pdf' :
                      viewerSource.file?.toLowerCase().endsWith('.docx') ? 'docx' : 'txt'
                    }
                    fileName={viewerSource.file}
                    cellData={{
                      verbatimExtract:
                        viewerSource.quote_anchor ||
                        viewerSource.quote ||
                        viewerSource.text_preview ||
                        null,
                      highlightMode: 'verbatim',
                      sourcePage: viewerSource.page ?? null,
                      sourcePageBasis: 'one',
                      highlightBBox: viewerSource.bbox,
                      highlightBBoxRegions: viewerSource.bbox_regions,
                      highlightPageBBox: viewerSource.page_bbox,
                    }}
                  />
                ) : (
                  <div className="p-6 overflow-y-auto">
                    <div
                      className="text-sm leading-relaxed p-4 rounded-lg"
                      style={{
                        backgroundColor: 'var(--color-info-bg)',
                        color: 'var(--color-info)',
                        border: '1px solid color-mix(in srgb, var(--color-info) 30%, var(--color-border))',
                        whiteSpace: 'pre-wrap',
                      }}
                    >
                      {viewerSource.quote || viewerSource.text_preview || 'Текст недоступен'}
                    </div>
                    <p className="mt-3 text-xs" style={{ color: 'var(--color-text-disabled)' }}>
                      Для навигации по документу прикрепите его через «Из дел»
                    </p>
                  </div>
                )}
              </div>
            )}

          </div>
        </>
      ) : (
        // ── Landing ──
        <div className="flex-1 overflow-y-auto" style={{ backgroundColor: 'var(--color-bg-secondary)' }}>
          <div className="max-w-[960px] mx-auto px-6 pt-6 pb-12">

            {/* Case badge */}
            <div className="mb-8 flex items-center justify-between">
              <div
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-sm"
                style={{
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-muted)',
                  backgroundColor: 'var(--color-bg-elevated)',
                }}
              >
                <FileText className="w-3.5 h-3.5" />
                {caseTitle || 'Загрузка...'}
              </div>
            </div>

            {/* Title */}
            <h1
              className="text-center mb-8"
              style={{
                fontSize: '52px',
                fontFamily: 'Georgia, "Times New Roman", serif',
                fontWeight: 400,
                color: 'var(--color-text-primary)',
                letterSpacing: '-0.5px',
                lineHeight: 1.15,
              }}
            >
              Legal AI
            </h1>

            {/* Input card */}
            <div className="mb-8">
              <HarveyInput
                value={question}
                onChange={setQuestion}
                onSubmit={handleSubmit}
                fileContexts={fileContexts}
                uploadingFiles={uploadingFiles}
                onAddFiles={handleAddFiles}
                onRemoveContext={handleRemoveContext}
                selectedCaseFiles={selectedCaseFiles}
                onOpenCaseFilePicker={handleOpenCaseFilePicker}
                onRemoveCaseFile={(id) => setSelectedCaseFileIds((prev) => prev.filter((x) => x !== id))}
                isStreaming={isStreaming}
                isDraftMode={isDraftMode}
                onSetDraftMode={setIsDraftMode}
                isLegalResearch={isLegalResearch}
                onSetLegalResearch={setIsLegalResearch}
                isDeepThink={isDeepThink}
                onSetDeepThink={setIsDeepThink}
                isImprovingPrompt={isImprovingPrompt}
                onImprovePrompt={handleImprovePrompt}
              />
            </div>

            {/* Workflows */}
            <div>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                  Рекомендуемые сценарии
                </h3>
                <button
                  type="button"
                  className="flex items-center gap-1.5 text-sm transition-colors hover:text-gray-900"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  <Search className="w-3.5 h-3.5" />
                  Поиск
                </button>
              </div>

              <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
                {WORKFLOWS.map((w) => (
                  <button
                    key={w.id}
                    type="button"
                    onClick={() => {
                      setQuestion(w.prompt)
                      if (w.isDraft) setIsDraftMode(true)
                    }}
                    className="text-left p-4 rounded-xl border bg-white transition-all duration-150 hover:shadow-md hover:border-gray-300"
                    style={{ borderColor: 'var(--color-border)' }}
                  >
                    <h4 className="text-sm font-medium mb-2 leading-snug" style={{ color: 'var(--color-text-primary)' }}>
                      {w.title}
                    </h4>
                    <p
                      className="text-xs leading-relaxed mb-4"
                      style={{
                        color: 'var(--color-text-muted)',
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical' as const,
                        overflow: 'hidden',
                      }}
                    >
                      {w.description}
                    </p>
                    <div className="flex items-center justify-between">
                      <span className="text-xs" style={{ color: 'var(--color-text-disabled)' }}>
                        {w.outputLabel} · {w.steps} шагов
                      </span>
                      <div
                        className="w-6 h-6 rounded flex items-center justify-center flex-shrink-0"
                        style={{ backgroundColor: 'var(--color-text-primary)' }}
                      >
                        <span className="text-white font-bold" style={{ fontSize: '11px' }}>L</span>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>

          </div>
        </div>
      )}

      {/* History drawer */}
      <ChatHistoryPanel
        isOpen={historyPanelOpen}
        onClose={() => setHistoryPanelOpen(false)}
        currentCaseId={caseId}
        onSelectQuery={(query, _sId) => {
          setQuestion(query)
          setHistoryPanelOpen(false)
        }}
        onLoadHistory={handleLoadHistory}
      />

      {/* Case file picker modal */}
      <CaseFilePickerModal
        isOpen={showCaseFilePicker}
        files={availableCaseFiles}
        loading={loadingCaseFiles}
        initialSelectedIds={selectedCaseFileIds}
        onApply={(ids) => {
          setSelectedCaseFileIds(ids)
          setShowCaseFilePicker(false)
        }}
        onClose={() => setShowCaseFilePicker(false)}
      />
    </div>
  )
}

export default AssistantChatPage
