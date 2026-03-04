import { useState, useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { useLocation } from 'react-router-dom'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import {
  FolderOpen, MessageSquare, FileText, X, Plus,
  AlignJustify, SlidersHorizontal, Sparkles, Search, ChevronDown, Loader2, Download, Clock,
  ChevronRight, Check,
} from 'lucide-react'
import { getApiUrl, getGlobalAssistantSession, saveSessionDraft, getCasesList, getCaseFiles, CaseListItem, UploadedFile } from '../services/api'
import { DocumentEditor, DocumentEditorRef } from '../components/Editor/DocumentEditor'
import MessageContent from '../components/Chat/MessageContent'

function inlineFmt(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
}

function markdownToHtml(md: string): string {
  const lines = md.split('\n')
  let html = ''
  let inUl = false
  let inOl = false
  for (const line of lines) {
    if (!/^[-*]\s/.test(line) && inUl) { html += '</ul>'; inUl = false }
    if (!/^\d+\.\s/.test(line) && inOl) { html += '</ol>'; inOl = false }
    const h4 = line.match(/^####\s+(.+)$/); const h3 = line.match(/^###\s+(.+)$/)
    const h2 = line.match(/^##\s+(.+)$/); const h1 = line.match(/^#\s+(.+)$/)
    if (h1) { html += `<h1>${inlineFmt(h1[1])}</h1>`; continue }
    if (h2) { html += `<h2>${inlineFmt(h2[1])}</h2>`; continue }
    if (h3) { html += `<h3>${inlineFmt(h3[1])}</h3>`; continue }
    if (h4) { html += `<h4>${inlineFmt(h4[1])}</h4>`; continue }
    // Skip decorator/separator lines (---, ***, •••, ===, etc.) — not needed in legal docs
    const trimmed = line.trim()
    if (trimmed.length >= 3 && /^(.)\1+$/.test(trimmed) && !/\w/.test(trimmed)) { continue }
    const ul = line.match(/^[-*]\s+(.+)$/)
    if (ul) { if (!inUl) { html += '<ul>'; inUl = true } html += `<li>${inlineFmt(ul[1])}</li>`; continue }
    const ol = line.match(/^\d+\.\s+(.+)$/)
    if (ol) { if (!inOl) { html += '<ol>'; inOl = true } html += `<li>${inlineFmt(ol[1])}</li>`; continue }
    if (line.trim() === '') continue
    html += `<p>${inlineFmt(line)}</p>`
  }
  if (inUl) html += '</ul>'
  if (inOl) html += '</ol>'
  return html
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  attachedFiles?: Array<{ id: string; filename: string }>
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

const navItems = [
  { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
  { id: 'assistant', label: 'Ассистент', icon: MessageSquare, path: '/assistant' },
  { id: 'history', label: 'История', icon: Clock, path: '/history' },
]

const WORKFLOWS = [
  {
    id: 1,
    title: 'Сравнение с правовым стандартом',
    description: 'Загрузите документ и проверьте его на соответствие правовому стандарту или регламенту.',
    outputType: 'Output',
    outputLabel: 'Результат',
    steps: 2,
    prompt: 'Сравни этот документ с соответствующим правовым стандартом и выяви несоответствия:',
  },
  {
    id: 2,
    title: 'Анализ договора',
    description: 'Загрузите договор и извлеките ключевые условия, обязательства, риски и рекомендации.',
    outputType: 'Output',
    outputLabel: 'Результат',
    steps: 3,
    prompt: 'Проанализируй этот договор и выдели ключевые условия, обязательства, риски и рекомендации:',
  },
  {
    id: 3,
    title: 'Составление юридического документа',
    description: 'Опишите нужный документ и предоставьте контекст для составления с помощью AI.',
    outputType: 'Draft',
    outputLabel: 'Черновик',
    steps: 2,
    prompt: 'Составь юридический документ на основе следующего описания и контекста:',
  },
  {
    id: 4,
    title: 'Чек-лист Due Diligence',
    description: 'Создайте комплексный чек-лист due diligence для вашего типа сделки и юрисдикции.',
    outputType: 'Output',
    outputLabel: 'Результат',
    steps: 4,
    prompt: 'Составь комплексный чек-лист due diligence для следующей сделки:',
  },
  {
    id: 5,
    title: 'Правовое заключение',
    description: 'Исследуйте правовой вопрос и получите структурированное заключение со ссылками и анализом.',
    outputType: 'Output',
    outputLabel: 'Результат',
    steps: 5,
    prompt: 'Исследуй следующий правовой вопрос и подготовь структурированное заключение со ссылками:',
  },
  {
    id: 6,
    title: 'Краткое изложение документов',
    description: 'Загрузите несколько документов и получите краткие резюме с ключевыми выводами.',
    outputType: 'Output',
    outputLabel: 'Результат',
    steps: 2,
    prompt: 'Сделай краткое изложение следующего документа и выдели ключевые моменты:',
  },
]

const SOURCES = [
  { label: 'Веб-поиск', color: '#22C55E' },
  { label: 'Документы дела', color: '#3B82F6' },
  { label: 'Загруженные файлы', color: '#F97316' },
  { label: 'Шаблоны договоров', color: '#8B5CF6' },
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
      'Сделай краткое резюме документа с ключевыми выводами',
      'Определи ключевые стороны и их позиции',
      'Выдели основные риски и рекомендации',
    ],
  },
]

// ─────────────────────────────────────────────────────────
// Case Document Picker Modal
// ─────────────────────────────────────────────────────────
interface CaseDocumentPickerProps {
  onClose: () => void
  onConfirm: (files: UploadedFile[], caseName: string) => void
  alreadySelectedIds: Set<string>
}

function CaseDocumentPickerModal({ onClose, onConfirm, alreadySelectedIds }: CaseDocumentPickerProps) {
  const [step, setStep] = useState<'cases' | 'files'>('cases')
  const [cases, setCases] = useState<CaseListItem[]>([])
  const [loadingCases, setLoadingCases] = useState(true)
  const [selectedCase, setSelectedCase] = useState<CaseListItem | null>(null)
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [loadingFiles, setLoadingFiles] = useState(false)
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set(alreadySelectedIds))
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    getCasesList(0, 100)
      .then((res) => setCases(res.cases ?? []))
      .catch(() => {})
      .finally(() => setLoadingCases(false))
  }, [])

  const handleSelectCase = async (c: CaseListItem) => {
    setSelectedCase(c)
    setStep('files')
    setLoadingFiles(true)
    try {
      const res = await getCaseFiles(c.id)
      setFiles(res.files ?? [])
    } catch {
      setFiles([])
    } finally {
      setLoadingFiles(false)
    }
  }

  const toggleFile = (id: string) => {
    setCheckedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleConfirm = () => {
    const selected = files.filter((f) => checkedIds.has(f.id))
    onConfirm(selected, selectedCase?.title ?? '')
    onClose()
  }

  const filteredCases = cases.filter((c) =>
    (c.title ?? '').toLowerCase().includes(searchQuery.toLowerCase())
  )
  const filteredFiles = files.filter((f) =>
    f.filename.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const newlySelected = files.filter((f) => checkedIds.has(f.id) && !alreadySelectedIds.has(f.id))

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0,0,0,0.4)' }}
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl overflow-hidden flex flex-col"
        style={{ width: '520px', maxHeight: '600px', boxShadow: '0 20px 60px rgba(0,0,0,0.18)' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2 text-sm" style={{ color: '#6B7280' }}>
            <button
              onClick={step === 'files' ? () => { setStep('cases'); setSearchQuery('') } : onClose}
              className="hover:text-gray-900 transition-colors font-medium"
            >
              {step === 'files' ? '← Назад' : 'Дела'}
            </button>
            {step === 'files' && selectedCase && (
              <>
                <ChevronRight className="w-3.5 h-3.5" />
                <span className="font-medium" style={{ color: '#111827' }}>{selectedCase.title ?? 'Без названия'}</span>
              </>
            )}
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 transition-colors">
            <X className="w-4 h-4" style={{ color: '#9CA3AF' }} />
          </button>
        </div>

        {/* Search */}
        <div className="px-4 py-2.5 border-b border-gray-100">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg" style={{ backgroundColor: '#F9FAFB', border: '1px solid #E5E7EB' }}>
            <Search className="w-3.5 h-3.5 flex-shrink-0" style={{ color: '#9CA3AF' }} />
            <input
              autoFocus
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={step === 'cases' ? 'Поиск по делам...' : 'Поиск по файлам...'}
              className="flex-1 bg-transparent outline-none text-sm"
              style={{ color: '#111827' }}
            />
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {step === 'cases' ? (
            loadingCases ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-5 h-5 animate-spin" style={{ color: '#9CA3AF' }} />
              </div>
            ) : filteredCases.length === 0 ? (
              <div className="flex items-center justify-center py-12 text-sm" style={{ color: '#9CA3AF' }}>
                {searchQuery ? 'Ничего не найдено' : 'Нет дел'}
              </div>
            ) : (
              filteredCases.map((c) => (
                <button
                  key={c.id}
                  onClick={() => { setSearchQuery(''); handleSelectCase(c) }}
                  className="w-full flex items-center justify-between px-5 py-3 border-b border-gray-50 hover:bg-gray-50 transition-colors text-left"
                >
                  <div className="flex items-center gap-3">
                    <FolderOpen className="w-4 h-4 flex-shrink-0" style={{ color: '#6B7280' }} />
                    <span className="text-sm font-medium" style={{ color: '#111827' }}>
                      {c.title ?? 'Без названия'}
                    </span>
                  </div>
                  <ChevronRight className="w-4 h-4 flex-shrink-0" style={{ color: '#D1D5DB' }} />
                </button>
              ))
            )
          ) : (
            loadingFiles ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-5 h-5 animate-spin" style={{ color: '#9CA3AF' }} />
              </div>
            ) : filteredFiles.length === 0 ? (
              <div className="flex items-center justify-center py-12 text-sm" style={{ color: '#9CA3AF' }}>
                {searchQuery ? 'Ничего не найдено' : 'В деле нет файлов'}
              </div>
            ) : (
              filteredFiles.map((f) => (
                <button
                  key={f.id}
                  onClick={() => toggleFile(f.id)}
                  className="w-full flex items-center gap-3 px-5 py-3 border-b border-gray-50 hover:bg-gray-50 transition-colors text-left"
                >
                  <div
                    className="w-4 h-4 rounded flex items-center justify-center flex-shrink-0"
                    style={{
                      border: checkedIds.has(f.id) ? '1px solid #4F46E5' : '1px solid #D1D5DB',
                      backgroundColor: checkedIds.has(f.id) ? '#4F46E5' : 'transparent',
                    }}
                  >
                    {checkedIds.has(f.id) && <Check className="w-2.5 h-2.5" style={{ color: 'white' }} />}
                  </div>
                  <FileText className="w-4 h-4 flex-shrink-0" style={{ color: '#6B7280' }} />
                  <span className="flex-1 text-sm truncate" style={{ color: '#111827' }}>{f.filename}</span>
                  {f.size && (
                    <span className="text-xs flex-shrink-0" style={{ color: '#9CA3AF' }}>
                      {Math.round(f.size / 1024)}kb
                    </span>
                  )}
                </button>
              ))
            )
          )}
        </div>

        {/* Footer (files step only) */}
        {step === 'files' && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-gray-100" style={{ backgroundColor: '#FAFAFA' }}>
            <span className="text-xs" style={{ color: '#9CA3AF' }}>
              {newlySelected.length > 0 ? `Выбрано: ${newlySelected.length}` : 'Выберите файлы'}
            </span>
            <button
              onClick={handleConfirm}
              disabled={newlySelected.length === 0}
              className="px-4 py-1.5 rounded-lg text-sm font-medium text-white transition-all disabled:opacity-40"
              style={{ backgroundColor: '#111827' }}
            >
              Добавить
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────
// Harvey-style input card
// ─────────────────────────────────────────────────────────
interface HarveyInputProps {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  fileContexts: FileContext[]
  uploadingFiles: string[]
  onAddFiles: (files: File[]) => void
  onRemoveContext: (idx: number) => void
  isStreaming: boolean
  isDraftMode: boolean
  onSetDraftMode: (draft: boolean) => void
  selectedCaseFiles: UploadedFile[]
  onRemoveCaseFile: (id: string) => void
  onOpenCasePicker: () => void
  placeholder?: string
}

function HarveyInput({
  value, onChange, onSubmit,
  fileContexts, uploadingFiles, onAddFiles, onRemoveContext,
  isStreaming, isDraftMode, onSetDraftMode,
  selectedCaseFiles, onRemoveCaseFile, onOpenCasePicker,
  placeholder = 'Спросите что угодно...',
}: HarveyInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const settingsRef = useRef<HTMLDivElement>(null)
  const promptsRef = useRef<HTMLDivElement>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [promptsOpen, setPromptsOpen] = useState(false)

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

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (promptsRef.current && !promptsRef.current.contains(e.target as Node)) {
        setPromptsOpen(false)
      }
    }
    if (promptsOpen) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [promptsOpen])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (value.trim() && !isStreaming) onSubmit()
    }
  }

  const hasFiles = fileContexts.length > 0 || uploadingFiles.length > 0 || selectedCaseFiles.length > 0

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
            color: '#111827',
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
              className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs border border-blue-200 bg-blue-50"
              style={{ color: '#2563EB' }}
            >
              <Loader2 className="w-3 h-3 animate-spin" />
              <span className="max-w-[140px] truncate">{name}</span>
            </div>
          ))}
          {fileContexts.map((fc, i) => (
            <div
              key={`ctx-${i}`}
              className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs border border-gray-200 bg-gray-50"
              style={{ color: '#374151' }}
            >
              <FileText className="w-3 h-3" style={{ color: '#22C55E' }} />
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
              className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs border border-indigo-200 bg-indigo-50"
              style={{ color: '#4338CA' }}
            >
              <FileText className="w-3 h-3" style={{ color: '#6366F1' }} />
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
        {/* Left tools (overflow-hidden to prevent pushing send button) */}
        <div className="flex items-center min-w-0 overflow-hidden" style={{ gap: '2px' }}>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors hover:bg-gray-50 flex-shrink-0 whitespace-nowrap"
            style={{ color: '#6B7280' }}
          >
            <Plus className="w-3.5 h-3.5" />
            Файлы
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.csv,.xlsx"
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
            onClick={onOpenCasePicker}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors hover:bg-gray-50 flex-shrink-0 whitespace-nowrap"
            style={{ color: selectedCaseFiles.length > 0 ? '#4338CA' : '#6B7280' }}
          >
            <FolderOpen className="w-3.5 h-3.5" />
            Из дел
            {selectedCaseFiles.length > 0 && (
              <span
                className="inline-flex items-center justify-center w-4 h-4 rounded-full text-xs font-medium"
                style={{ backgroundColor: '#4F46E5', color: 'white', fontSize: '10px' }}
              >
                {selectedCaseFiles.length}
              </span>
            )}
          </button>

          <button
            type="button"
            disabled
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm opacity-40 cursor-not-allowed flex-shrink-0 whitespace-nowrap"
            style={{ color: '#6B7280' }}
          >
            <Sparkles className="w-3.5 h-3.5" />
            Улучшить
          </button>
        </div>

        {/* Prompts dropdown — outside overflow-hidden so the popup is not clipped */}
        <div ref={promptsRef} className="relative flex-shrink-0">
          <button
            type="button"
            onClick={() => setPromptsOpen((o) => !o)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors whitespace-nowrap"
            style={{
              color: '#6B7280',
              backgroundColor: promptsOpen ? '#F3F4F6' : undefined,
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
                    style={{ color: '#9CA3AF', backgroundColor: '#FAFAFA' }}
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
                      style={{ color: '#374151' }}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Settings dropdown — outside overflow-hidden so the popup is not clipped */}
        <div ref={settingsRef} className="relative flex-shrink-0">
          <button
            type="button"
            onClick={() => setSettingsOpen((o) => !o)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors whitespace-nowrap"
            style={{
              color: isDraftMode ? '#4F46E5' : '#6B7280',
              backgroundColor: settingsOpen ? '#F3F4F6' : undefined,
            }}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            Настройки
            {isDraftMode && (
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 ml-0.5 flex-shrink-0" />
            )}
          </button>

          {settingsOpen && (
            <div
              className="absolute bottom-full mb-1.5 left-0 bg-white rounded-lg border border-gray-200 overflow-hidden z-50"
              style={{ minWidth: '130px', boxShadow: '0 4px 16px rgba(0,0,0,0.10)' }}
            >
              <div className="px-2.5 py-1.5 text-xs font-medium border-b border-gray-100" style={{ color: '#9CA3AF' }}>
                Режим
              </div>
              <button
                type="button"
                onClick={() => { onSetDraftMode(false); setSettingsOpen(false) }}
                className="w-full flex items-center gap-2 px-2.5 py-2 text-sm transition-colors"
                style={{
                  color: !isDraftMode ? '#111827' : '#6B7280',
                  backgroundColor: !isDraftMode ? '#F9FAFB' : 'transparent',
                  fontWeight: !isDraftMode ? 500 : 400,
                }}
              >
                <span
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ backgroundColor: !isDraftMode ? '#111827' : '#D1D5DB' }}
                />
                Ask
              </button>
              <button
                type="button"
                onClick={() => { onSetDraftMode(true); setSettingsOpen(false) }}
                className="w-full flex items-center gap-2 px-2.5 py-2 text-sm transition-colors"
                style={{
                  color: isDraftMode ? '#4F46E5' : '#6B7280',
                  backgroundColor: isDraftMode ? '#EEF2FF' : 'transparent',
                  fontWeight: isDraftMode ? 500 : 400,
                }}
              >
                <span
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ backgroundColor: isDraftMode ? '#4F46E5' : '#D1D5DB' }}
                />
                Draft
              </button>
            </div>
          )}
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Send button — always visible */}
        <div className="flex-shrink-0">
          <button
            type="button"
            onClick={onSubmit}
            disabled={!value.trim() || isStreaming}
            className="flex items-center justify-center px-4 py-1.5 text-sm font-medium text-white rounded-lg transition-all disabled:opacity-40"
            style={{ backgroundColor: '#111827', minWidth: '80px' }}
          >
            {isStreaming ? (
              <div
                className="w-4 h-4 border-2 rounded-full animate-spin"
                style={{ borderColor: 'rgba(255,255,255,0.3)', borderTopColor: '#fff' }}
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
const GlobalAssistantPage = () => {
  const location = useLocation()
  const [question, setQuestion] = useState('')
  const [fileContexts, setFileContexts] = useState<FileContext[]>([])
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [isDraftMode, setIsDraftMode] = useState(false)
  const [draftDocument, setDraftDocument] = useState<DraftDocument | null>(null)
  const [showDraftPanel, setShowDraftPanel] = useState(false)
  const [editorContent, setEditorContent] = useState<string | null>(null)
  const draftEditorRef = useRef<DocumentEditorRef>(null)
  const editorHtmlRef = useRef<string>('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const [selectedCaseFiles, setSelectedCaseFiles] = useState<UploadedFile[]>([])
  const [showCasePicker, setShowCasePicker] = useState(false)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Load session from ?session= URL param
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const sessionParam = params.get('session')
    if (!sessionParam) return
    getGlobalAssistantSession(sessionParam)
      .then((data) => {
        const loadedMessages = data.messages.map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))
        setMessages(loadedMessages)
        setSessionId(sessionParam)

        // Restore draft document: prefer saved draft, else detect from last assistant message
        if (data.draft_content && data.draft_title) {
          setDraftDocument({ title: data.draft_title, content: data.draft_content })
          setEditorContent(data.draft_content) // already HTML
        } else {
          const lastMsg = loadedMessages[loadedMessages.length - 1]
          if (lastMsg?.role === 'assistant' && lastMsg.content.length > 400) {
            const lines = lastMsg.content.trim().split('\n')
            const firstLine = lines[0].trim()
            const boldMatch = firstLine.match(/^\*\*(.+?)\*\*$/)
            const headingMatch = firstLine.match(/^#+\s+(.+)$/)
            let title = ''
            let bodyContent = lastMsg.content.trim()
            if (boldMatch) { title = boldMatch[1]; bodyContent = lines.slice(1).join('\n').trimStart() }
            else if (headingMatch) { title = headingMatch[1]; bodyContent = lines.slice(1).join('\n').trimStart() }
            if (title && bodyContent.length > 200) {
              setDraftDocument({ title, content: bodyContent })
              setEditorContent(markdownToHtml(bodyContent))
            }
          }
        }
      })
      .catch(() => {})
  }, [location.search])

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
      } finally {
        setUploadingFiles((prev) => prev.filter((n) => n !== file.name))
      }
    }
  }

  const handleRemoveContext = (idx: number) => {
    setFileContexts((prev) => prev.filter((_, i) => i !== idx))
  }

  const handleRemoveCaseFile = (id: string) => {
    setSelectedCaseFiles((prev) => prev.filter((f) => f.id !== id))
  }

  const handleCasePickerConfirm = (files: UploadedFile[]) => {
    setSelectedCaseFiles((prev) => {
      const existingIds = new Set(prev.map((f) => f.id))
      const newFiles = files.filter((f) => !existingIds.has(f.id))
      return [...prev, ...newFiles]
    })
  }

  const handleSubmit = async () => {
    const text = question.trim()
    if (!text || isStreaming) return

    const contextsToSend = [...fileContexts]
    const caseFileIdsToSend = selectedCaseFiles.map((f) => f.id)
    const currentDraft = draftDocument
    setQuestion('')
    setFileContexts([])
    setSelectedCaseFiles([])

    const userMsg: ChatMessage = {
      role: 'user',
      content: text,
      attachedFiles: selectedCaseFiles.length > 0
        ? selectedCaseFiles.map((f) => ({ id: f.id, filename: f.filename }))
        : undefined,
    }
    const allMessages = [...messages, userMsg]
    setMessages([...allMessages, { role: 'assistant', content: '' }])
    setIsStreaming(true)

    abortRef.current?.abort()
    abortRef.current = new AbortController()

    if (isDraftMode) {
      setDraftDocument((prev) => prev ?? { title: 'Черновик', content: '' })
      setEditorContent(null)
      editorHtmlRef.current = ''
    }

    let finalDraftContent = ''
    let finalDraftTitle = 'Документ'
    let capturedSessionId = sessionId

    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(getApiUrl('/api/v2/assistant/global-chat'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          messages: allMessages.map((m) => ({ role: m.role, content: m.content })),
          session_id: sessionId,
          file_contexts: contextsToSend.map((fc) => ({ filename: fc.filename, text: fc.text })),
          attached_file_ids: caseFileIdsToSend.length > 0 ? caseFileIdsToSend : undefined,
          draft_mode: isDraftMode,
          document_context: isDraftMode && currentDraft ? currentDraft.content : undefined,
        }),
        signal: abortRef.current.signal,
      })

      if (!response.ok) throw new Error(`Server error: ${response.status}`)

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let assistantContent = ''
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue
          try {
            const data = JSON.parse(raw)
            if (data.session_id && !sessionId) {
              setSessionId(data.session_id)
              capturedSessionId = data.session_id
            } else if (data.error) {
              assistantContent = `Ошибка: ${data.error}`
              setMessages((prev) => [
                ...prev.slice(0, -1),
                { role: 'assistant', content: assistantContent },
              ])
            } else if (data.textDelta) {
              assistantContent += data.textDelta
              if (!isDraftMode) {
                setMessages((prev) => [
                  ...prev.slice(0, -1),
                  { role: 'assistant', content: assistantContent },
                ])
              } else {
                // Draft mode: keep chat empty, parse content for right panel
                const draftLines = assistantContent.trim().split('\n')
                const firstLine = draftLines[0].trim()
                const boldMatch = firstLine.match(/^\*\*(.+?)\*\*$/)
                const headingMatch = firstLine.match(/^#+\s+(.+)$/)
                if (boldMatch) {
                  finalDraftTitle = boldMatch[1]
                  finalDraftContent = draftLines.slice(1).join('\n').trimStart()
                  setDraftDocument({ title: boldMatch[1], content: finalDraftContent })
                } else if (headingMatch) {
                  finalDraftTitle = headingMatch[1]
                  finalDraftContent = draftLines.slice(1).join('\n').trimStart()
                  setDraftDocument({ title: headingMatch[1], content: finalDraftContent })
                } else {
                  finalDraftContent = assistantContent.trim()
                  setDraftDocument((prev) => ({ title: prev?.title ?? 'Документ', content: finalDraftContent }))
                }
              }
            }
          } catch {}
        }
      }
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        setMessages((prev) => [
          ...prev.slice(0, -1),
          { role: 'assistant', content: 'An error occurred. Please try again.' },
        ])
      }
    } finally {
      setIsStreaming(false)
      if (isDraftMode && finalDraftContent) {
        const htmlContent = markdownToHtml(finalDraftContent)
        setEditorContent(htmlContent)
        editorHtmlRef.current = ''
        if (capturedSessionId) {
          saveSessionDraft(capturedSessionId, finalDraftTitle, htmlContent).catch(() => {})
        }
      }
    }
  }

  const handleDownloadDocx = async () => {
    if (!draftDocument) return
    try {
      const token = localStorage.getItem('access_token')
      const contentToSend = editorHtmlRef.current || editorContent || draftDocument.content
      const contentTypeToSend = (editorHtmlRef.current || editorContent) ? 'html' : 'markdown'
      console.log('[download] content_type:', contentTypeToSend, 'content_len:', contentToSend?.length)
      const res = await fetch(getApiUrl('/api/v2/assistant/download-docx'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          title: draftDocument.title,
          content: contentToSend,
          content_type: contentTypeToSend,
        }),
      })
      if (!res.ok) {
        const errText = await res.text().catch(() => '')
        console.error('[download] server error:', res.status, errText)
        throw new Error(`Server ${res.status}: ${errText}`)
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${draftDocument.title}.docx`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Download error:', err)
      toast.error('Ошибка при скачивании документа')
    }
  }

  const handleNewChat = () => {
    abortRef.current?.abort()
    setMessages([])
    setQuestion('')
    setFileContexts([])
    setSelectedCaseFiles([])
    setSessionId(null)
    setIsDraftMode(false)
    setDraftDocument(null)
    setShowDraftPanel(false)
    setEditorContent(null)
    editorHtmlRef.current = ''
  }

  const chatActive = messages.length > 0

  return (
    <div className="h-screen flex overflow-hidden bg-white">
      <UnifiedSidebar navItems={navItems} title="Legal AI" />

      {showCasePicker && (
        <CaseDocumentPickerModal
          onClose={() => setShowCasePicker(false)}
          onConfirm={handleCasePickerConfirm}
          alreadySelectedIds={new Set(selectedCaseFiles.map((f) => f.id))}
        />
      )}

      <div className="flex-1 flex flex-col overflow-hidden">
        {chatActive ? (
          // ── Chat view (with optional split-view document panel) ──
          <>
            {/* Header */}
            <div
              className="flex items-center justify-between px-6 py-3 border-b shrink-0"
              style={{ borderBottomColor: '#E5E7EB' }}
            >
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium" style={{ color: '#6B7280' }}>
                  Ассистент
                </span>
                {isDraftMode && (
                  <span
                    className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                    style={{ backgroundColor: '#EEF2FF', color: '#4F46E5', border: '1px solid #C7D2FE' }}
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 inline-block" />
                    Режим черновика
                  </span>
                )}
              </div>
              <button
                onClick={handleNewChat}
                className="flex items-center gap-1.5 text-sm font-medium transition-opacity hover:opacity-70"
                style={{ color: '#6B7280' }}
              >
                <Plus className="w-4 h-4" />
                Новый чат
              </button>
            </div>

            {/* Body: chat + optional document panel */}
            <div className="flex-1 flex overflow-hidden">
              {/* Chat column */}
              <div className="flex flex-col overflow-hidden" style={{ width: showDraftPanel ? '45%' : '100%', transition: 'width 0.2s ease' }}>
                <div className="flex-1 overflow-y-auto">
                  <div style={{ maxWidth: '960px', margin: '0 auto' }} className="px-6 py-8 space-y-6">
                    {messages.map((msg, idx) => (
                      <div key={idx} className={msg.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                        {msg.role === 'user' ? (
                          <div className="max-w-[75%] flex flex-col items-end gap-1.5">
                            {msg.attachedFiles && msg.attachedFiles.length > 0 && (
                              <div className="flex flex-wrap gap-1 justify-end">
                                {msg.attachedFiles.map((f) => (
                                  <span
                                    key={f.id}
                                    className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border border-indigo-200 bg-indigo-50"
                                    style={{ color: '#4338CA' }}
                                  >
                                    <FileText className="w-3 h-3" />
                                    <span className="max-w-[160px] truncate">{f.filename}</span>
                                  </span>
                                ))}
                              </div>
                            )}
                            <div
                              className="px-4 py-3 rounded-2xl text-sm leading-relaxed"
                              style={{ backgroundColor: '#111827', color: '#fff' }}
                            >
                              {msg.content}
                            </div>
                          </div>
                        ) : (
                          <div
                            className="max-w-[90%] text-sm leading-relaxed"
                            style={{ color: '#111827' }}
                          >
                            {msg.content && !(draftDocument && idx === messages.length - 1) ? (
                              <MessageContent
                                content={msg.content}
                                sources={[]}
                                isStreaming={isStreaming && idx === messages.length - 1 && !isDraftMode}
                              />
                            ) : (
                              isStreaming && idx === messages.length - 1 && !isDraftMode && (
                                <div className="flex gap-1">
                                  {[0, 1, 2].map((i) => (
                                    <div
                                      key={i}
                                      className="w-1.5 h-1.5 rounded-full animate-bounce"
                                      style={{ backgroundColor: '#9CA3AF', animationDelay: `${i * 150}ms` }}
                                    />
                                  ))}
                                </div>
                              )
                            )}
                            {/* Draft indicator */}
                            {(isDraftMode || draftDocument) && idx === messages.length - 1 && (
                              isStreaming ? (
                                <div className="flex flex-col gap-2">
                                  <p className="text-sm" style={{ color: '#374151' }}>
                                    Да, конечно — создаю документ...
                                  </p>
                                  <button
                                    onClick={() => setShowDraftPanel(true)}
                                    className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors self-start"
                                    style={{ border: '1px solid #C7D2FE', backgroundColor: '#EEF2FF', color: '#4338CA' }}
                                  >
                                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                    Генерация черновика...
                                  </button>
                                </div>
                              ) : draftDocument ? (
                                <div className="flex flex-col gap-2">
                                  <p className="text-sm" style={{ color: '#374151' }}>
                                    Готово! Документ{draftDocument.title ? ` «${draftDocument.title}»` : ''} создан. Вы можете открыть его в редакторе.
                                  </p>
                                  <button
                                    onClick={() => setShowDraftPanel(true)}
                                    className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors self-start"
                                    style={{ border: '1px solid #C7D2FE', backgroundColor: '#EEF2FF', color: '#4338CA' }}
                                  >
                                    <FileText className="w-3.5 h-3.5" />
                                    Открыть документ
                                  </button>
                                </div>
                              ) : null
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                    <div ref={messagesEndRef} />
                  </div>
                </div>

                <div className="shrink-0 px-6 py-4 border-t" style={{ borderTopColor: '#E5E7EB' }}>
                  <div style={{ maxWidth: '960px', margin: '0 auto' }}>
                    <HarveyInput
                      value={question}
                      onChange={setQuestion}
                      onSubmit={handleSubmit}
                      fileContexts={fileContexts}
                      uploadingFiles={uploadingFiles}
                      onAddFiles={handleAddFiles}
                      onRemoveContext={handleRemoveContext}
                      isStreaming={isStreaming}
                      isDraftMode={isDraftMode}
                      onSetDraftMode={setIsDraftMode}
                      selectedCaseFiles={selectedCaseFiles}
                      onRemoveCaseFile={handleRemoveCaseFile}
                      onOpenCasePicker={() => setShowCasePicker(true)}
                    />
                  </div>
                </div>
              </div>

              {/* Document panel */}
              {showDraftPanel && draftDocument && (
                <div
                  className="flex flex-col border-l overflow-hidden"
                  style={{ width: '55%', borderLeftColor: '#E5E7EB', backgroundColor: '#FAFAFA' }}
                >
                  <div
                    className="flex items-center gap-3 px-5 py-3 border-b bg-white shrink-0"
                    style={{ borderBottomColor: '#E5E7EB' }}
                  >
                    <input
                      value={draftDocument.title}
                      onChange={(e) => {
                        const newTitle = e.target.value
                        setDraftDocument((prev) => prev ? { ...prev, title: newTitle } : null)
                        if (sessionId) {
                          clearTimeout((window as any)._draftSaveTimer)
                          ;(window as any)._draftSaveTimer = setTimeout(() => {
                            saveSessionDraft(sessionId, newTitle, editorHtmlRef.current || editorContent || '').catch(() => {})
                          }, 1500)
                        }
                      }}
                      className="flex-1 text-sm font-semibold outline-none bg-transparent"
                      style={{ color: '#111827' }}
                    />
                    <button
                      onClick={handleDownloadDocx}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors hover:bg-gray-50"
                      style={{ borderColor: '#E5E7EB', color: '#374151' }}
                    >
                      <Download className="w-3.5 h-3.5" />
                      Скачать .docx
                    </button>
                    <button
                      onClick={() => setShowDraftPanel(false)}
                      className="p-1 rounded-md transition-colors hover:bg-gray-100"
                      style={{ color: '#9CA3AF' }}
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                  <div className="flex-1 flex flex-col overflow-hidden">
                    {isStreaming ? (
                      <div
                        className="flex-1 overflow-y-auto p-8 bg-white"
                        style={{ fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.75', color: '#111827', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
                      >
                        {draftDocument.content}
                      </div>
                    ) : editorContent !== null ? (
                      <DocumentEditor
                        ref={draftEditorRef}
                        content={editorContent}
                        onChange={(html) => {
                          editorHtmlRef.current = html
                          // Auto-save to session with debounce
                          if (sessionId && draftDocument) {
                            clearTimeout((window as any)._draftSaveTimer)
                            ;(window as any)._draftSaveTimer = setTimeout(() => {
                              saveSessionDraft(sessionId, draftDocument.title, html).catch(() => {})
                            }, 1500)
                          }
                        }}
                        onSelectionChange={() => {}}
                      />
                    ) : null}
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          // ── Harvey-style landing ─────────────────────────
          <div className="flex-1 overflow-y-auto" style={{ backgroundColor: '#FAFAFA' }}>
            <div className="max-w-[960px] mx-auto px-6 pt-12 pb-12">

              {/* Client matter selector */}
              <div className="mb-8 flex items-center gap-2 flex-wrap">
                <button
                  onClick={() => setShowCasePicker(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-sm transition-colors hover:bg-white"
                  style={{
                    borderColor: selectedCaseFiles.length > 0 ? '#C7D2FE' : '#E5E7EB',
                    color: selectedCaseFiles.length > 0 ? '#4338CA' : '#6B7280',
                    backgroundColor: selectedCaseFiles.length > 0 ? '#EEF2FF' : 'transparent',
                  }}
                >
                  <FolderOpen className="w-3.5 h-3.5" />
                  Выбрать документы из дел
                  {selectedCaseFiles.length > 0 ? (
                    <span
                      className="inline-flex items-center justify-center w-4 h-4 rounded-full text-xs font-medium"
                      style={{ backgroundColor: '#4F46E5', color: 'white', fontSize: '10px' }}
                    >
                      {selectedCaseFiles.length}
                    </span>
                  ) : (
                    <ChevronDown className="w-3 h-3 ml-0.5" style={{ color: '#9CA3AF' }} />
                  )}
                </button>
                {selectedCaseFiles.map((f) => (
                  <div
                    key={f.id}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border border-indigo-200 bg-indigo-50"
                    style={{ color: '#4338CA' }}
                  >
                    <FileText className="w-3 h-3" style={{ color: '#6366F1' }} />
                    <span className="max-w-[120px] truncate">{f.filename}</span>
                    <button
                      onClick={() => handleRemoveCaseFile(f.id)}
                      className="ml-0.5 hover:text-red-500 transition-colors"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ))}
              </div>

              {/* Title */}
              <h1
                className="text-center mb-8"
                style={{
                  fontSize: '52px',
                  fontFamily: 'Georgia, "Times New Roman", serif',
                  fontWeight: 400,
                  color: '#111827',
                  letterSpacing: '-0.5px',
                  lineHeight: 1.15,
                }}
              >
                Legal AI
              </h1>

              {/* Input card */}
              <div className="mb-4">
                {isDraftMode && (
                  <div className="flex items-center gap-2 mb-2">
                    <span
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
                      style={{ backgroundColor: '#EEF2FF', color: '#4F46E5', border: '1px solid #C7D2FE' }}
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 inline-block" />
                      Режим черновика
                    </span>
                    <button
                      type="button"
                      onClick={() => setIsDraftMode(false)}
                      className="text-xs transition-colors hover:text-gray-700"
                      style={{ color: '#9CA3AF' }}
                    >
                      ✕ Отключить
                    </button>
                  </div>
                )}
                <HarveyInput
                  value={question}
                  onChange={setQuestion}
                  onSubmit={handleSubmit}
                  fileContexts={fileContexts}
                  uploadingFiles={uploadingFiles}
                  onAddFiles={handleAddFiles}
                  onRemoveContext={handleRemoveContext}
                  isStreaming={isStreaming}
                  isDraftMode={isDraftMode}
                  onSetDraftMode={setIsDraftMode}
                  selectedCaseFiles={selectedCaseFiles}
                  onRemoveCaseFile={handleRemoveCaseFile}
                  onOpenCasePicker={() => setShowCasePicker(true)}
                />
              </div>

              {/* Source pills */}
              <div className="flex flex-wrap justify-center gap-2 mb-10">
                {SOURCES.map((source) => (
                  <button
                    key={source.label}
                    type="button"
                    className="flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs transition-colors hover:bg-white"
                    style={{ borderColor: '#E5E7EB', color: '#6B7280', backgroundColor: 'transparent' }}
                  >
                    <span
                      className="w-2 h-2 rounded-full flex-shrink-0"
                      style={{ backgroundColor: source.color }}
                    />
                    {source.label}
                    <Plus className="w-3 h-3" style={{ color: '#9CA3AF' }} />
                  </button>
                ))}
              </div>

              {/* Recommended workflows */}
              <div>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-medium" style={{ color: '#111827' }}>
                    Рекомендуемые сценарии
                  </h3>
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      className="flex items-center gap-1.5 text-sm transition-colors hover:text-gray-900"
                      style={{ color: '#6B7280' }}
                    >
                      <Search className="w-3.5 h-3.5" />
                      Поиск
                    </button>
                    <button
                      type="button"
                      className="text-sm transition-colors hover:text-gray-900"
                      style={{ color: '#6B7280' }}
                    >
                      Все сценарии
                    </button>
                  </div>
                </div>

                <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
                  {WORKFLOWS.map((w) => (
                    <button
                      key={w.id}
                      type="button"
                      onClick={() => {
                        setQuestion(w.prompt)
                        setIsDraftMode(w.outputType === 'Draft')
                      }}
                      className="text-left p-4 rounded-xl border bg-white transition-all duration-150 hover:shadow-md hover:border-gray-300"
                      style={{ borderColor: '#E5E7EB' }}
                    >
                      <h4 className="text-sm font-medium mb-2 leading-snug" style={{ color: '#111827' }}>
                        {w.title}
                      </h4>
                      <p
                        className="text-xs leading-relaxed mb-4"
                        style={{
                          color: '#6B7280',
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical' as const,
                          overflow: 'hidden',
                        }}
                      >
                        {w.description}
                      </p>
                      <div className="flex items-center justify-between">
                        <span className="text-xs" style={{ color: '#9CA3AF' }}>
                          {w.outputLabel} · {w.steps} шагов
                        </span>
                        <div
                          className="w-6 h-6 rounded flex items-center justify-center flex-shrink-0"
                          style={{ backgroundColor: '#111827' }}
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
      </div>
    </div>
  )
}

export default GlobalAssistantPage
