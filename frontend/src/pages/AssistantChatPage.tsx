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
import {
  caseAssistantLegacyCitationsEnabled,
  resolveCaseCitationSource,
} from '../utils/caseAssistantCitations'
import { AnswerBlocks, sourceInfosToAnswerBlockCitations } from '../components/Chat/AnswerBlocks'
import {
  ThinkingBlock,
  type ThinkingStep,
  type ToolCallInfo,
} from '../components/Chat/ThinkingBlock'
import { TabularDocumentViewer } from '../components/TabularReview/TabularDocumentViewer'
import { toast } from 'sonner'
import {
  canSelectDraftMode,
  canEnableLegalResearch,
  canEnableCourtPractice,
} from '../lib/chatInstrumentPolicy'
import { agentRunsEnabled } from '../lib/agentRunsPolicy'
import { useChatInstrumentSettings } from '../hooks/useChatInstrumentSettings'
import {
  applyAssistantActivityEvent,
  applyReasoningEvent,
} from '../lib/assistantActivity'

// ─────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────
interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: SourceInfo[]
  reasoningSteps?: ThinkingStep[]
  toolCalls?: ToolCallInfo[]
  agentTodos?: Array<{ content: string; status: string }>
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
  isCourtPractice: boolean
  onSetCourtPractice: (v: boolean) => void
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
  isCourtPractice, onSetCourtPractice,
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
  const hasActiveSettings = isDraftMode || isLegalResearch || isCourtPractice

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
                disabled={!canSelectDraftMode(isLegalResearch, isCourtPractice)}
                onClick={() => {
                  if (!canSelectDraftMode(isLegalResearch, isCourtPractice)) return
                  onSetDraftMode(true)
                  setSettingsOpen(false)
                }}
                className="w-full flex items-center gap-2 px-2.5 py-2 text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                title={isLegalResearch || isCourtPractice ? 'Недоступно при включённых инструментах' : undefined}
                style={{
                  color: isDraftMode ? 'var(--color-accent)' : 'var(--color-text-muted)',
                  backgroundColor: isDraftMode ? 'var(--color-bg-hover)' : 'transparent',
                  fontWeight: isDraftMode ? 500 : 400,
                }}
              >
                <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: isDraftMode ? 'var(--color-accent)' : 'var(--color-border-strong)' }} />
                Draft
              </button>

              {/* Инструменты — только в режиме Ask */}
              {!isDraftMode && (
              <>
              <div className="px-2.5 py-1.5 text-xs font-medium border-t border-b border-gray-100" style={{ color: 'var(--color-text-disabled)' }}>
                Инструменты
              </div>
              <button
                type="button"
                disabled={!canEnableLegalResearch(isDraftMode) || isCourtPractice}
                onClick={() => onSetLegalResearch(!isLegalResearch)}
                className="w-full flex items-center gap-2 px-2.5 py-2 text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                title={isDraftMode ? 'Недоступно в режиме Draft' : undefined}
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
                Справочник
              </button>
              <button
                type="button"
                disabled={!canEnableCourtPractice(isDraftMode) || isLegalResearch}
                onClick={() => onSetCourtPractice(!isCourtPractice)}
                className="w-full flex items-center gap-2 px-2.5 py-2 text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                title={isDraftMode ? 'Недоступно в режиме Draft' : undefined}
                style={{
                  color: isCourtPractice ? '#0F766E' : 'var(--color-text-muted)',
                  backgroundColor: isCourtPractice ? 'var(--color-success-bg)' : 'transparent',
                }}
              >
                <span
                  className="w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0"
                  style={{
                    borderColor: isCourtPractice ? '#0F766E' : 'var(--color-border-strong)',
                    backgroundColor: isCourtPractice ? '#0F766E' : 'transparent',
                  }}
                >
                  {isCourtPractice && <span className="text-white" style={{ fontSize: '9px' }}>✓</span>}
                </span>
                Суд. практика
              </button>
              </>
              )}
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
  const sessionIdRef = useRef<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const {
    legalResearch: isLegalResearch,
    courtPractice: isCourtPractice,
    draftMode: isDraftMode,
    setLegalResearch: setIsLegalResearch,
    setCourtPractice: setIsCourtPractice,
    setDraftMode: setIsDraftMode,
    reset: resetChatInstruments,
  } = useChatInstrumentSettings()
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

  // Сброс тумблеров при входе в чат другого дела (или повторном открытии маршрута).
  useEffect(() => {
    resetChatInstruments()
  }, [caseId, resetChatInstruments])

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

  // Handle autoQuery from navigation state (e.g. from GlobalAssistantPage)
  useEffect(() => {
    const autoQuery: string = (location.state as any)?.autoQuery || ''
    if (autoQuery) {
      setQuestion(autoQuery)
    }
  }, [])

  // Client-owned session: mint UUID before first API call so backend never attaches to stale case session.
  useEffect(() => {
    if (!caseId) return
    const params = new URLSearchParams(location.search)
    if (params.get('session')) return
    if (sessionIdRef.current) return
    const newSid = crypto.randomUUID()
    sessionIdRef.current = newSid
    setSessionId(newSid)
  }, [caseId, location.search])

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
          sessionIdRef.current = sessionParam
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
            'X-Access-Token': token,
          },
          body: JSON.stringify({
            case_id: caseId,
            ...(sid ? { session_id: sid } : {}),
          }),
        })
        if (cancelled || !res.ok) return
        const data = (await res.json()) as { session_id?: string }
        // Не перетираем session_id после «Новый чат» (уже задан в state)
        if (data.session_id && !sessionFromUrl && !sessionIdRef.current) {
          sessionIdRef.current = data.session_id
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
          headers: { 'X-Access-Token': token || '' },
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
    return 'case_advice'
  }

  // ── Send message ──
  const handleSubmit = async (
    overrideText?: unknown,
    options?: Record<string, never>,
  ) => {
    // Может вызываться как onSubmit(event) и как handleSubmit("текст").
    if (overrideText && typeof overrideText === 'object' && 'preventDefault' in (overrideText as any)) {
      ;(overrideText as any).preventDefault?.()
    }
    const rawText = typeof overrideText === 'string' ? overrideText : question
    let text = String(rawText ?? '').trim()
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

    let assistantContent = ''
    let draftDocIdThisRequest: string | null = null

    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(getApiUrl('/api/v2/assistant/chat'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Access-Token': token || '',
        },
        body: JSON.stringify({
          case_id: caseId,
          mode: resolveConversationMode(),
          messages: allMessages.map((m) => ({ role: m.role, content: m.content })),
          session_id: sessionIdRef.current ?? sessionId,
          file_contexts: contextsToSend.map((fc) => ({ filename: fc.filename, text: fc.text })),
          web_search: false,
          legal_research: isDraftMode ? false : isLegalResearch,
          use_legal_corpus: isDraftMode ? false : isLegalResearch,
          court_practice: isDraftMode ? false : isCourtPractice,
          draft_mode: isDraftMode,
          document_context: isDraftMode && currentDraft ? currentDraft.content : undefined,
          attached_file_ids: selectedCaseFileIds.length > 0 ? selectedCaseFileIds : undefined,
        }),
        signal: abortRef.current.signal,
      })

      if (!response.ok) throw new Error(`Server error: ${response.status}`)

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const processSSELine = (line: string) => {
        if (!line.startsWith('data: ')) return
        const raw = line.slice(6).trim()
        if (!raw) return
        try {
          const data = JSON.parse(raw)
          if (data.session_id) {
            sessionIdRef.current = data.session_id
            setSessionId((prev) => prev || data.session_id)
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
          } else if (data.type === 'assistant_activity') {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last.role !== 'assistant') return prev
              const reasoningSteps = applyAssistantActivityEvent(
                last.reasoningSteps || [],
                data,
              )
              return [...prev.slice(0, -1), { ...last, reasoningSteps }]
            })
          } else if (data.type === 'reasoning' && data.phase && data.content) {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last.role !== 'assistant') return prev
              const reasoningSteps = applyReasoningEvent(
                last.reasoningSteps || [],
                data,
              )
              return [...prev.slice(0, -1), { ...last, reasoningSteps }]
            })
          } else if (data.type === 'draft_todos' && Array.isArray(data.todos)) {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (!last || last.role !== 'assistant') return prev
              return [
                ...prev.slice(0, -1),
                {
                  ...last,
                  agentTodos: data.todos.map((t: { content?: string; status?: string }) => ({
                    content: String(t.content || ''),
                    status: String(t.status || 'pending'),
                  })),
                },
              ]
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
            draftDocIdThisRequest = docId
            setDraftDocId(docId)
            setDraftDocument({ title: docTitle, content: '' })
          } else if (data.type === 'content_sync' && typeof data.content === 'string') {
            // Финальный текст узла графа после sanitize — подменяем накопленный стрим (убирает утечки/дубли).
            assistantContent = data.content
            const draftShowContent =
              isDraftMode &&
              (assistantContent.includes('❌') ||
                assistantContent.includes('Ошибка') ||
                assistantContent.includes('✅'))
            if (!isDraftMode || draftShowContent) {
              setMessages((prev) => {
                const last = prev[prev.length - 1]
                return [...prev.slice(0, -1), { ...last, role: 'assistant', content: assistantContent }]
              })
            }
          } else if (data.textDelta) {
            assistantContent += data.textDelta
            const draftShowDelta =
              isDraftMode &&
              (data.textDelta.includes('❌') ||
                assistantContent.includes('Ошибка') ||
                assistantContent.includes('✅'))
            if (!isDraftMode || draftShowDelta) {
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
      if (isDraftMode && assistantContent.trim()) {
        const draftFailed =
          !draftDocIdThisRequest &&
          (assistantContent.includes('❌') || assistantContent.includes('Ошибка создания'))
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last?.role !== 'assistant') return prev
          return [...prev.slice(0, -1), { ...last, role: 'assistant', content: assistantContent }]
        })
        if (draftFailed) {
          toast.error('Не удалось сохранить документ в редактор. Нажмите «Одобрить план» ещё раз.')
        }
      }
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
    const resolved = resolveCaseCitationSource(
      source,
      availableCaseFiles,
      caseId ?? undefined,
    )
    setViewerSource(resolved)
  }

  // ── New chat ──
  const handleNewChat = () => {
    abortRef.current?.abort()
    setMessages([])
    setQuestion('')
    setFileContexts([])
    setSelectedCaseFileIds([])
    // Новый UUID = новый LangGraph thread; иначе бэкенд цепляется к последней сессии дела (<30 мин)
    const newSid = crypto.randomUUID()
    sessionIdRef.current = newSid
    setSessionId(newSid)
    resetChatInstruments()
    setDraftDocument(null)
    setDraftDocId(null)
    if (caseId) {
      navigate(`/cases/${caseId}/chat`, { replace: true })
    }
  }

  // ── Load history session ──
  const handleLoadHistory = async (histSessionId?: string) => {
    if (!caseId) return
    resetChatInstruments()
    try {
      const history = await loadChatHistory(caseId, histSessionId)
      setMessages(history.map((m) => mapAssistantHistoryMessage(m)))
      if (histSessionId) {
        sessionIdRef.current = histSessionId
        setSessionId(histSessionId)
      }
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
  const chatActive = messages.length > 0 || loadingSession || !!sessionParam

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
                  Справочник
                </span>
              )}
              {isCourtPractice && (
                <span
                  className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                  style={{
                    backgroundColor: 'var(--color-success-bg)',
                    color: '#0F766E',
                    border: '1px solid color-mix(in srgb, #0F766E 35%, var(--color-border))',
                  }}
                >
                  Суд. практика
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
                    const assistantTextBody =
                      msg.role === 'assistant'
                        ? (msg.content && msg.content.trim()) || ''
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
                            (msg.reasoningSteps && msg.reasoningSteps.length > 0) ||
                            (msg.agentTodos && msg.agentTodos.length > 0) ||
                            (isStreaming && idx === messages.length - 1 && !msg.content)) && (
                            <div className="mb-3">
                              <ThinkingBlock
                                steps={msg.reasoningSteps || []}
                                toolCalls={msg.toolCalls}
                                agentTodos={msg.agentTodos}
                                planOutlineTitle="Draft Agent"
                                isStreaming={isStreaming && idx === messages.length - 1 && !msg.content}
                                defaultOpen
                              />
                            </div>
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
                              preferLegacyCitations={caseAssistantLegacyCitationsEnabled()}
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
                    isCourtPractice={isCourtPractice}
                    onSetCourtPractice={setIsCourtPractice}
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
                isCourtPractice={isCourtPractice}
                onSetCourtPractice={setIsCourtPractice}
                isImprovingPrompt={isImprovingPrompt}
                onImprovePrompt={handleImprovePrompt}
              />
            </div>

            {agentRunsEnabled() && caseId && (
              <div
                className="rounded-xl border p-5 flex items-center justify-between gap-4"
                style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-elevated)' }}
              >
                <div>
                  <h3 className="text-sm font-medium flex items-center gap-2" style={{ color: 'var(--color-text-primary)' }}>
                    <Sparkles className="w-4 h-4" />
                    Многошаговые задачи
                  </h3>
                  <p className="text-xs mt-1 max-w-lg" style={{ color: 'var(--color-text-muted)' }}>
                    Анализ, таблицы, черновики и другие сложные сценарии — на отдельной странице Workflows с историей запусков.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => navigate(`/cases/${caseId}/workflows`)}
                  className="flex-shrink-0 px-4 py-2 rounded-lg text-sm font-medium text-white"
                  style={{ backgroundColor: 'var(--color-text-primary)' }}
                >
                  Открыть Workflows
                </button>
              </div>
            )}

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
