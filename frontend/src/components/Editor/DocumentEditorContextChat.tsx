"use client"

import React, { useState, useCallback, useRef, KeyboardEvent, useEffect } from "react"
import { chatOverDocument } from "@/services/documentEditorApi"
import type { StructuredEdit } from "@/services/documentEditorApi"
import { getCaseFiles, UploadedFile } from "@/services/api"
import { toast } from "sonner"
import { Loader } from "@/components/ai-elements/loader"
import {
  Check, Edit3, HelpCircle, FileText,
  Sparkles, ListPlus, ArrowRight, ChevronDown, ChevronUp, X, Paperclip,
  BookOpen, ChevronRight, Scissors
} from "lucide-react"

// ==================== TYPES ====================
type EditorMode = 'edit' | 'ask' | 'draft'

interface RuleResult {
  rule_id: string
  rule_name: string
  rule_type: 'red_line' | 'no_go' | 'fallback' | 'standard' | string
  status: 'passed' | 'violation' | 'warning' | 'not_applicable' | 'not_found' | 'error' | string
  issue_description?: string
  suggestion?: string
  suggested_fix?: string
  found_text?: string
  reasoning?: string
}

interface PlaybookResult {
  id: string
  playbook_name: string
  compliance_score: number
  total_rules: number
  passed_rules: number
  red_line_violations: number
  no_go_violations: number
  fallback_issues: number
  results: RuleResult[]
  summary?: string
}

interface DocumentEditorContextChatProps {
  documentId: string
  documentTitle: string
  documentContent?: string
  onApplyEdit?: (text: string) => void
  onInsertText?: (text: string) => void
  onReplaceText?: (original: string, newText: string) => boolean
  onReplaceRange?: (from: number, to: number, text: string) => void
  onRunPlaybook?: () => void
  caseId?: string
  pendingPlaybookResult?: PlaybookResult | null
  onPlaybookResultConsumed?: () => void
  selectedText?: string
  selectionRange?: { from: number; to: number } | null
  onClearSelection?: () => void
}

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  citations?: Array<{ file: string; file_id: string }>
  editedContent?: string
  structuredEdits?: StructuredEdit[]
  playbookResult?: PlaybookResult
  mode?: EditorMode
  selectionRange?: { from: number; to: number }
  selectedTextSnapshot?: string
  draftInsertedText?: string
}

// ==================== TEMPLATE PROMPTS ====================
const TEMPLATE_PROMPTS = [
  { category: 'Анализ', items: ['Проверь документ на риски', 'Найди противоречия', 'Оцени сбалансированность условий', 'Сравни с типовым договором'] },
  { category: 'Редактирование', items: ['Улучши стиль и грамотность', 'Добавь стандартные защитные оговорки', 'Приведи к единому формату', 'Упрости язык договора'] },
  { category: 'Создание', items: ['Добавь преамбулу', 'Создай пункт об NDA', 'Добавь форс-мажорную оговорку', 'Напиши раздел о гарантиях'] },
]

// ==================== MAGIC PENCIL ====================
const enhancePrompt = (text: string, mode: EditorMode): string => {
  const trimmed = text.trim()
  if (!trimmed || trimmed.length > 200) return text
  if (mode === 'edit' && trimmed.length < 20) {
    return `${trimmed}. Отредактируй соответствующую часть документа профессионально и юридически грамотно`
  }
  if (mode === 'ask' && !trimmed.includes('?') && trimmed.length < 60) {
    return `${trimmed}? Дай подробный ответ со ссылкой на конкретные пункты документа`
  }
  if (mode === 'draft') {
    return `${trimmed}. Используй стандартные юридические формулировки, соответствующие российскому праву`
  }
  return text
}

const MODE_CONFIG = {
  edit: {
    label: 'Edit',
    icon: Edit3,
    placeholder: 'Задайте вопрос ассистенту...',
    color: '#6366f1',
    hint: 'Редактирование текста',
  },
  ask: {
    label: 'Ask',
    icon: HelpCircle,
    placeholder: 'Задайте вопрос о документе...',
    color: '#0ea5e9',
    hint: 'Вопросы о документе',
  },
  draft: {
    label: 'Draft',
    icon: FileText,
    placeholder: 'Опишите что нужно создать...',
    color: '#10b981',
    hint: 'Создание нового текста',
  },
} as const

// ==================== MARKDOWN RENDERER ====================
const renderMarkdown = (text: string): React.ReactNode => {
  const lines = text.split('\n')
  return lines.map((line, i) => {
    const parts = line.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g)
    const rendered = parts.map((part, j) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={j}>{part.slice(2, -2)}</strong>
      }
      if (part.startsWith('*') && part.endsWith('*')) {
        return <em key={j}>{part.slice(1, -1)}</em>
      }
      return part
    })
    return <React.Fragment key={i}>{rendered}{i < lines.length - 1 ? '\n' : ''}</React.Fragment>
  })
}

// ==================== STRUCTURED EDITS CARD ====================
type EditStatus = 'accepted' | 'rejected'

const StructuredEditsBlock: React.FC<{
  edits: StructuredEdit[]
  statuses: Record<string, EditStatus>
  onAccept: (edit: StructuredEdit) => void
  onAcceptAll: () => void
  onDismiss: (editId: string) => void
}> = ({ edits, statuses, onAccept, onAcceptAll, onDismiss }) => {
  const pendingEdits = edits.filter(e => e.found_in_document !== false && !statuses[e.id])

  return (
    <div className="space-y-2 mt-2 max-w-[92%]">
      {/* Header bar */}
      <div className="flex items-center justify-between px-3 py-2 rounded-lg border" style={{ borderColor: '#e5e7eb', background: '#fafafa' }}>
        <span className="text-xs font-semibold text-gray-500">
          Правки ({edits.length})
        </span>
        {pendingEdits.length > 1 && (
          <button
            onClick={onAcceptAll}
            className="flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-lg border transition-colors"
            style={{ borderColor: '#d1d5db', color: '#374151', background: 'transparent' }}
            onMouseEnter={e => {
              const el = e.currentTarget
              el.style.borderColor = '#10b981'
              el.style.color = '#10b981'
              el.style.background = 'rgba(16,185,129,0.06)'
            }}
            onMouseLeave={e => {
              const el = e.currentTarget
              el.style.borderColor = '#d1d5db'
              el.style.color = '#374151'
              el.style.background = 'transparent'
            }}
          >
            <Check className="w-3 h-3" />
            Принять все
          </button>
        )}
      </div>

      {/* Individual edits */}
      {edits.map((edit) => {
        const isFound = edit.found_in_document !== false
        const status = statuses[edit.id]

        return (
          <div
            key={edit.id}
            className="rounded-xl border overflow-hidden"
            style={{ borderColor: '#e5e7eb', background: '#f5f5f5' }}
          >
            <div className="px-3 pt-2.5 pb-1.5">
              {/* Diff row */}
              <div className="space-y-1">
                <div className="flex items-start gap-1.5 px-2 py-1 rounded-md" style={{ background: 'rgba(239,68,68,0.05)' }}>
                  <span className="text-xs font-bold text-red-400 shrink-0 mt-0.5 select-none">–</span>
                  <span className="text-xs text-red-600 line-through break-words leading-relaxed opacity-80">{edit.original_text}</span>
                </div>
                <div className="flex items-start gap-1.5 px-2 py-1 rounded-md" style={{ background: 'rgba(16,185,129,0.05)' }}>
                  <span className="text-xs font-bold text-emerald-500 shrink-0 mt-0.5 select-none">+</span>
                  <span className="text-xs text-emerald-800 break-words leading-relaxed">{edit.new_text}</span>
                </div>
              </div>
              {!isFound && !status && (
                <div className="text-xs text-amber-600 mt-1.5">⚠ Фрагмент не найден в документе</div>
              )}
            </div>

            {/* Footer: status badge or action buttons */}
            <div className="flex items-center justify-end gap-2 px-3 pb-2.5 pt-1 border-t" style={{ borderColor: '#ebebeb' }}>
              {status === 'accepted' && (
                <div className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg border" style={{ borderColor: '#d1fae5', color: '#10b981', background: 'rgba(16,185,129,0.07)' }}>
                  <Check className="w-3 h-3" />
                  Принято
                </div>
              )}
              {status === 'rejected' && (
                <div className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border" style={{ borderColor: '#fee2e2', color: '#ef4444', background: 'rgba(239,68,68,0.05)' }}>
                  <X className="w-3 h-3" />
                  Отклонено
                </div>
              )}
              {!status && (
                <>
                  <button
                    onClick={() => onDismiss(edit.id)}
                    className="text-xs font-medium px-3 py-1.5 rounded-lg border transition-colors"
                    style={{ borderColor: '#e5e7eb', color: '#9ca3af', background: 'transparent' }}
                    onMouseEnter={e => {
                      const el = e.currentTarget
                      el.style.borderColor = '#fca5a5'
                      el.style.color = '#ef4444'
                      el.style.background = 'rgba(239,68,68,0.05)'
                    }}
                    onMouseLeave={e => {
                      const el = e.currentTarget
                      el.style.borderColor = '#e5e7eb'
                      el.style.color = '#9ca3af'
                      el.style.background = 'transparent'
                    }}
                  >
                    Отклонить
                  </button>
                  {isFound && (
                    <button
                      onClick={() => onAccept(edit)}
                      className="flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-lg border transition-colors"
                      style={{ borderColor: '#d1d5db', color: '#374151', background: 'transparent' }}
                      onMouseEnter={e => {
                        const el = e.currentTarget
                        el.style.borderColor = '#10b981'
                        el.style.color = '#10b981'
                        el.style.background = 'rgba(16,185,129,0.07)'
                      }}
                      onMouseLeave={e => {
                        const el = e.currentTarget
                        el.style.borderColor = '#d1d5db'
                        el.style.color = '#374151'
                        el.style.background = 'transparent'
                      }}
                    >
                      <Check className="w-3 h-3" />
                      Принять
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ==================== PLAYBOOK RESULT BLOCK ====================
const getHarveyClass = (rule: RuleResult) => {
  if (rule.status === 'passed') return { label: 'Приемлемо', color: '#16a34a', bg: 'rgba(22,163,74,0.08)', border: 'rgba(22,163,74,0.2)' }
  if (rule.status === 'warning' || rule.rule_type === 'fallback') return { label: 'Требует проверки', color: '#ca8a04', bg: 'rgba(202,138,4,0.08)', border: 'rgba(202,138,4,0.2)' }
  return { label: 'Неприемлемо', color: '#dc2626', bg: 'rgba(220,38,38,0.08)', border: 'rgba(220,38,38,0.2)' }
}

const PlaybookResultBlock: React.FC<{
  result: PlaybookResult
  onApplyFix?: (original: string, fixed: string) => boolean
}> = ({ result, onApplyFix }) => {
  const [expandedRules, setExpandedRules] = useState<Set<string>>(new Set())
  const [activeFilter, setActiveFilter] = useState<'all' | 'violations' | 'warnings' | 'passed'>('all')
  const [appliedRules, setAppliedRules] = useState<Set<string>>(new Set())

  const toggleRule = (id: string) => {
    setExpandedRules(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const violationsCount = result.results.filter(r => r.status === 'violation' || r.status === 'not_found' || r.status === 'error').length
  const warningsCount = result.results.filter(r => r.status === 'warning').length
  const passedCount = result.results.filter(r => r.status === 'passed').length

  const filteredResults = result.results.filter(r => {
    if (activeFilter === 'violations') return r.status === 'violation' || r.status === 'not_found' || r.status === 'error'
    if (activeFilter === 'warnings') return r.status === 'warning'
    if (activeFilter === 'passed') return r.status === 'passed'
    return true
  })

  const scoreColor = result.compliance_score >= 80 ? '#16a34a' : result.compliance_score >= 50 ? '#ca8a04' : '#dc2626'

  return (
    <div className="rounded-2xl border overflow-hidden" style={{ borderColor: '#e5e7eb' }}>
      {/* Header */}
      <div className="px-4 py-3 border-b" style={{ borderColor: '#e5e7eb', background: '#f9fafb' }}>
        <div className="flex items-center justify-between mb-2">
          <div>
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5">Результаты Playbook</div>
            <div className="text-sm font-semibold text-gray-800">{result.playbook_name}</div>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold" style={{ color: scoreColor }}>{result.compliance_score}%</div>
            <div className="text-xs text-gray-400">соответствие</div>
          </div>
        </div>
        {/* Stats row */}
        <div className="grid grid-cols-3 gap-2 mt-2">
          <div className="rounded-lg px-2 py-1.5 text-center" style={{ background: 'rgba(22,163,74,0.08)' }}>
            <div className="text-base font-bold" style={{ color: '#16a34a' }}>{passedCount}</div>
            <div className="text-xs text-gray-500">Приемлемо</div>
          </div>
          <div className="rounded-lg px-2 py-1.5 text-center" style={{ background: 'rgba(202,138,4,0.08)' }}>
            <div className="text-base font-bold" style={{ color: '#ca8a04' }}>{warningsCount}</div>
            <div className="text-xs text-gray-500">На проверку</div>
          </div>
          <div className="rounded-lg px-2 py-1.5 text-center" style={{ background: 'rgba(220,38,38,0.08)' }}>
            <div className="text-base font-bold" style={{ color: '#dc2626' }}>{violationsCount}</div>
            <div className="text-xs text-gray-500">Неприемлемо</div>
          </div>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex border-b" style={{ borderColor: '#e5e7eb' }}>
        {([
          { key: 'all', label: 'Все' },
          { key: 'violations', label: 'Неприемлемо' },
          { key: 'warnings', label: 'На проверку' },
          { key: 'passed', label: 'Приемлемо' },
        ] as const).map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveFilter(tab.key)}
            className="flex-1 text-xs py-2 font-medium transition-colors"
            style={{
              color: activeFilter === tab.key ? '#111827' : '#9ca3af',
              borderBottom: activeFilter === tab.key ? '2px solid #111827' : '2px solid transparent',
              background: 'transparent',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Rules list */}
      <div className="divide-y max-h-[400px] overflow-y-auto" style={{ borderColor: '#f3f4f6' }}>
        {filteredResults.length === 0 ? (
          <div className="px-4 py-6 text-center text-xs text-gray-400">Нет результатов</div>
        ) : (
          filteredResults.map(rule => {
            const cls = getHarveyClass(rule)
            const isExpanded = expandedRules.has(rule.rule_id)
            const isApplied = appliedRules.has(rule.rule_id)
            return (
              <div key={rule.rule_id} style={{ borderColor: '#f3f4f6' }}>
                <button
                  className="w-full flex items-start gap-3 px-4 py-3 text-left hover:bg-gray-50 transition-colors"
                  onClick={() => toggleRule(rule.rule_id)}
                >
                  <div className="shrink-0 mt-0.5">
                    <span
                      className="text-xs font-semibold px-2 py-0.5 rounded-full"
                      style={{ color: cls.color, background: cls.bg }}
                    >
                      {cls.label}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium text-gray-800 truncate">{rule.rule_name}</div>
                    {rule.issue_description && (
                      <div className="text-xs text-gray-500 mt-0.5 line-clamp-1">{rule.issue_description}</div>
                    )}
                  </div>
                  {isExpanded ? <ChevronUp className="w-3.5 h-3.5 text-gray-400 shrink-0 mt-0.5" /> : <ChevronDown className="w-3.5 h-3.5 text-gray-400 shrink-0 mt-0.5" />}
                </button>
                {isExpanded && (
                  <div className="px-4 pb-3 space-y-2" style={{ background: cls.bg }}>
                    {rule.reasoning && (
                      <div>
                        <div className="text-xs font-semibold text-gray-500 mb-1">Обоснование AI</div>
                        <div className="text-xs text-gray-700 leading-relaxed">{rule.reasoning}</div>
                      </div>
                    )}
                    {rule.found_text && (
                      <div>
                        <div className="text-xs font-semibold text-gray-500 mb-1">Найдено в документе</div>
                        <div className="text-xs text-gray-600 italic bg-white rounded px-2 py-1 border" style={{ borderColor: cls.border }}>
                          "{rule.found_text}"
                        </div>
                      </div>
                    )}
                    {(rule.suggested_fix || rule.suggestion) && (
                      <div>
                        <div className="text-xs font-semibold text-gray-500 mb-1">Предлагаемая правка</div>
                        <div className="rounded-lg border overflow-hidden" style={{ borderColor: cls.border }}>
                          {rule.found_text && (
                            <div className="flex items-start gap-1.5 px-2 py-1 bg-red-50">
                              <span className="text-xs font-bold text-red-500 shrink-0">–</span>
                              <span className="text-xs text-red-700 line-through">{rule.found_text}</span>
                            </div>
                          )}
                          <div className="flex items-start gap-1.5 px-2 py-1 bg-green-50">
                            <span className="text-xs font-bold text-green-600 shrink-0">+</span>
                            <span className="text-xs text-green-800 underline decoration-green-400">{rule.suggested_fix || rule.suggestion}</span>
                          </div>
                        </div>
                        {onApplyFix && rule.found_text && !isApplied && (
                          <button
                            onClick={() => {
                              const fix = rule.suggested_fix || rule.suggestion || ''
                              const ok = onApplyFix(rule.found_text!, fix)
                              if (ok) {
                                setAppliedRules(prev => new Set([...prev, rule.rule_id]))
                                toast.success('Правка применена')
                              } else {
                                toast.error('Не удалось найти фрагмент')
                              }
                            }}
                            className="mt-1.5 flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-lg text-white transition-opacity hover:opacity-90"
                            style={{ backgroundColor: '#10b981' }}
                          >
                            <Check className="w-3 h-3" />
                            Применить правку
                          </button>
                        )}
                        {isApplied && (
                          <div className="mt-1.5 text-xs text-green-600 font-medium flex items-center gap-1">
                            <Check className="w-3 h-3" /> Правка применена
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

// ==================== COMPONENT ====================
export const DocumentEditorContextChat: React.FC<DocumentEditorContextChatProps> = ({
  documentId,
  documentTitle,
  documentContent,
  onApplyEdit,
  onInsertText: _onInsertText,
  onReplaceText,
  onReplaceRange,
  onRunPlaybook,
  caseId,
  pendingPlaybookResult,
  onPlaybookResultConsumed,
  selectedText,
  selectionRange,
  onClearSelection,
}) => {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [mode, setMode] = useState<EditorMode>('edit')
  const [showModeDropdown, setShowModeDropdown] = useState(false)
  const [inputValue, setInputValue] = useState('')
  const [showTemplates, setShowTemplates] = useState(false)
  const [showFilesPicker, setShowFilesPicker] = useState(false)
  const [caseFiles, setCaseFiles] = useState<UploadedFile[]>([])
  const [loadingFiles, setLoadingFiles] = useState(false)
  // Locked selection: captured from editor when user starts typing in chat
  const [activeSelection, setActiveSelection] = useState<string>('')
  const [activeSelectionRange, setActiveSelectionRange] = useState<{ from: number; to: number } | null>(null)
  // Per-message edit statuses: { messageId: { editId: 'accepted' | 'rejected' } }
  const [editStatuses, setEditStatuses] = useState<Record<string, Record<string, EditStatus>>>({})
  const [modeDropdownPos, setModeDropdownPos] = useState<{ top: number; left: number } | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const modeDropdownRef = useRef<HTMLDivElement>(null)
  const modeDropdownMenuRef = useRef<HTMLDivElement>(null)
  const modeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Inject playbook result as a chat message
  useEffect(() => {
    if (!pendingPlaybookResult) return
    setMessages(prev => [...prev, {
      id: `playbook-${Date.now()}`,
      role: 'assistant',
      content: '',
      playbookResult: pendingPlaybookResult,
    }])
    onPlaybookResultConsumed?.()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingPlaybookResult])

  // Capture selection/cursor when editor updates
  useEffect(() => {
    if (selectedText && selectedText.trim()) {
      // Text is selected — capture it and its range
      setActiveSelection(selectedText.trim())
      setActiveSelectionRange(selectionRange || null)
    } else if (mode === 'draft' && selectionRange) {
      // Draft mode: always track cursor position even without a text selection
      setActiveSelectionRange(selectionRange)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedText, selectionRange, mode])

  const clearActiveSelection = () => {
    setActiveSelection('')
    setActiveSelectionRange(null)
    onClearSelection?.()
  }

  // Close mode dropdown on outside click
  useEffect(() => {
    if (!showModeDropdown) return
    const handleClick = (e: MouseEvent) => {
      const target = e.target as Node
      const insideButton = modeDropdownRef.current?.contains(target)
      const insideMenu = modeDropdownMenuRef.current?.contains(target)
      if (!insideButton && !insideMenu) {
        setShowModeDropdown(false)
        setModeDropdownPos(null)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [showModeDropdown])

  const handleToggleFiles = useCallback(async () => {
    if (showFilesPicker) {
      setShowFilesPicker(false)
      return
    }
    if (!caseId) {
      toast.error('Дело не определено')
      return
    }
    setShowFilesPicker(true)
    if (caseFiles.length === 0) {
      setLoadingFiles(true)
      try {
        const resp = await getCaseFiles(caseId)
        setCaseFiles(resp.files)
      } catch {
        toast.error('Не удалось загрузить файлы дела')
        setShowFilesPicker(false)
      } finally {
        setLoadingFiles(false)
      }
    }
  }, [caseId, caseFiles.length, showFilesPicker])

  const handleAttachFile = (file: UploadedFile) => {
    const tag = `[Файл: ${file.filename}]`
    setInputValue((prev) => prev ? `${prev}\n${tag}` : tag)
    setShowFilesPicker(false)
    textareaRef.current?.focus()
  }

  const handleSend = useCallback(async (text: string) => {
    if (!text.trim() || isLoading) return

    const selectionSnapshot = activeSelection
    const selectionRangeSnapshot = activeSelectionRange

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text.trim(),
      mode,
      selectedTextSnapshot: selectionSnapshot || undefined,
    }

    setMessages((prev) => [...prev, userMessage])
    setIsLoading(true)
    setInputValue('')
    if (selectionSnapshot) clearActiveSelection()

    try {
      const response = await chatOverDocument(documentId, text.trim(), {
        currentContent: documentContent,
        mode,
        selectedText: selectionSnapshot || undefined,
      })

      // Strip any residual code blocks from the displayed answer
      const cleanAnswer = response.answer
        .replace(/```(?:html|edit|)\s*\n[\s\S]*?\n?```/gi, '')
        .replace(/```[\s\S]*?```/g, '')
        .trim() || "Изменения готовы."

      // Draft mode: insert generated text at cursor/selection position in editor
      if (mode === 'draft' && selectionRangeSnapshot && onReplaceRange && cleanAnswer) {
        const insertText = cleanAnswer
        onReplaceRange(selectionRangeSnapshot.from, selectionRangeSnapshot.to, insertText)
        setMessages((prev) => [...prev, {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: '',
          mode,
          draftInsertedText: insertText,
        }])
        return
      }

      const assistantMessage: Message = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: cleanAnswer,
        citations: response.citations,
        editedContent: response.edited_content,
        structuredEdits: response.structured_edits && response.structured_edits.length > 0
          ? response.structured_edits
          : undefined,
        mode,
        selectionRange: selectionRangeSnapshot || undefined,
      }

      setMessages((prev) => [...prev, assistantMessage])
    } catch (err: any) {
      toast.error("Ошибка: " + (err.message || "Не удалось получить ответ"))
      setMessages((prev) => [
        ...prev,
        {
          id: `assistant-error-${Date.now()}`,
          role: "assistant",
          content: "Извините, произошла ошибка при обработке запроса.",
        },
      ])
    } finally {
      setIsLoading(false)
    }
  }, [documentId, isLoading, mode, documentContent, activeSelection, activeSelectionRange, onReplaceRange])

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend(inputValue)
    }
  }

  const handleMagicPencil = () => {
    if (!inputValue.trim()) return
    const enhanced = enhancePrompt(inputValue, mode)
    if (enhanced !== inputValue) {
      setInputValue(enhanced)
      toast.success('Запрос улучшен')
    }
  }

  const getContentPreview = (html: string): string => {
    const div = document.createElement('div')
    div.innerHTML = html
    return (div.textContent || '').trim().slice(0, 220)
  }

  const handleApply = (content: string, messageId: string) => {
    if (onApplyEdit) {
      onApplyEdit(content)
      toast.success('Применено')
    }
    setMessages((prev) =>
      prev.map((m) => m.id === messageId ? { ...m, editedContent: undefined } : m)
    )
  }

  const setStatus = (messageId: string, editId: string, status: EditStatus) => {
    setEditStatuses(prev => ({
      ...prev,
      [messageId]: { ...(prev[messageId] || {}), [editId]: status },
    }))
  }

  const handleAcceptEdit = (messageId: string, edit: StructuredEdit) => {
    const msg = messages.find(m => m.id === messageId)
    if (msg?.selectionRange && onReplaceRange) {
      onReplaceRange(msg.selectionRange.from, msg.selectionRange.to, edit.new_text)
      setStatus(messageId, edit.id, 'accepted')
      toast.success('Правка принята')
    } else if (onReplaceText) {
      const success = onReplaceText(edit.original_text, edit.new_text)
      if (success) {
        setStatus(messageId, edit.id, 'accepted')
        toast.success('Правка принята')
      } else {
        toast.error('Не удалось найти фрагмент в документе')
      }
    }
  }

  const handleAcceptAllEdits = (messageId: string, edits: StructuredEdit[]) => {
    const msg = messages.find(m => m.id === messageId)
    const pendingEdits = edits.filter(e => e.found_in_document !== false && !editStatuses[messageId]?.[e.id])

    if (msg?.selectionRange && onReplaceRange && pendingEdits.length === 1) {
      onReplaceRange(msg.selectionRange.from, msg.selectionRange.to, pendingEdits[0].new_text)
      setStatus(messageId, pendingEdits[0].id, 'accepted')
      toast.success('Правка принята')
      return
    }

    if (!onReplaceText) return
    let applied = 0
    for (const edit of pendingEdits) {
      const success = onReplaceText(edit.original_text, edit.new_text)
      if (success) {
        setStatus(messageId, edit.id, 'accepted')
        applied++
      }
    }
    if (applied > 0) toast.success(`Принято правок: ${applied}`)
  }

  const handleDismissEdit = (messageId: string, editId: string) => {
    setStatus(messageId, editId, 'rejected')
  }

  const currentMode = MODE_CONFIG[mode]
  const hasMessages = messages.length > 0

  return (
    <div className="flex flex-col h-full bg-white">

      {/* ── Header ── */}
      <div className="px-4 pt-4 pb-3 border-b shrink-0" style={{ borderColor: '#e5e7eb' }}>
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">AI Ассистент</span>
          <span className="text-xs text-gray-400 truncate max-w-[160px]">{documentTitle}</span>
        </div>
      </div>

      {/* ── Messages ── */}
      {hasMessages && (
        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3 min-h-0">
          {messages.map((message) => {
            if (message.role === "user") {
              return (
                <div key={message.id} className="flex flex-col items-end gap-1.5">
                  {message.selectedTextSnapshot && (
                    <div
                      className="max-w-[85%] rounded-2xl rounded-tr-sm px-3 py-2 border"
                      style={{ background: '#f5f5f5', borderColor: '#e5e7eb' }}
                    >
                      <div className="flex items-center gap-1.5 mb-1">
                        <Scissors className="w-3 h-3 shrink-0" style={{ color: '#9ca3af' }} />
                        <span className="text-xs font-semibold" style={{ color: '#9ca3af' }}>Выделенный текст</span>
                      </div>
                      <div className="text-xs leading-relaxed line-clamp-3" style={{ color: '#6b7280' }}>
                        {message.selectedTextSnapshot.slice(0, 200)}{message.selectedTextSnapshot.length > 200 ? '…' : ''}
                      </div>
                    </div>
                  )}
                  <div className="max-w-[85%] bg-gray-100 rounded-2xl rounded-tr-sm px-3 py-2 text-sm text-gray-800">
                    {message.content}
                  </div>
                </div>
              )
            }

            const allEdits = message.structuredEdits ?? []

            // Playbook result message
            if (message.playbookResult) {
              return (
                <div key={message.id} className="space-y-2">
                  <PlaybookResultBlock
                    result={message.playbookResult}
                    onApplyFix={onReplaceText}
                  />
                </div>
              )
            }

            return (
              <div key={message.id} className="space-y-2">
                {/* Draft inserted text card */}
                {message.draftInsertedText && (
                  <div className="rounded-xl border overflow-hidden" style={{ borderColor: '#bbf7d0', background: '#f0fdf4' }}>
                    <div className="flex items-center gap-1.5 px-3 py-1.5 border-b" style={{ borderColor: '#bbf7d0' }}>
                      <Check className="w-3 h-3" style={{ color: '#16a34a' }} />
                      <span className="text-xs font-semibold" style={{ color: '#16a34a' }}>Текст вставлен в документ</span>
                    </div>
                    <div className="px-3 py-2 text-xs leading-relaxed text-gray-700 whitespace-pre-wrap line-clamp-4">
                      {message.draftInsertedText}
                    </div>
                  </div>
                )}
                {message.content && (
                  <div className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
                    {renderMarkdown(message.content)}
                  </div>
                )}

                {/* Structured edits */}
                {allEdits.length > 0 && (
                  <StructuredEditsBlock
                    edits={allEdits}
                    statuses={editStatuses[message.id] || {}}
                    onAccept={(edit) => handleAcceptEdit(message.id, edit)}
                    onAcceptAll={() => handleAcceptAllEdits(message.id, allEdits)}
                    onDismiss={(editId) => handleDismissEdit(message.id, editId)}
                  />
                )}

                {/* Full document apply (fallback when no structured edits) */}
                {message.editedContent && !message.structuredEdits && onApplyEdit && (
                  <div className="rounded-xl border bg-gray-50 overflow-hidden" style={{ borderColor: '#e5e7eb' }}>
                    <div className="px-3 py-2 text-xs text-gray-500 leading-relaxed line-clamp-3 border-b" style={{ borderColor: '#e5e7eb' }}>
                      {getContentPreview(message.editedContent)}
                    </div>
                    <button
                      onClick={() => handleApply(message.editedContent!, message.id)}
                      className="w-full flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-semibold text-white transition-opacity hover:opacity-90"
                      style={{ backgroundColor: '#10b981' }}
                    >
                      <Check className="w-3 h-3" />
                      Применить к документу
                    </button>
                  </div>
                )}

                {message.citations && message.citations.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {message.citations.map((c) => (
                      <span key={c.file_id} className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 border border-blue-100">
                        {c.file}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-gray-400">
              <Loader />
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      )}

      {/* ── Input + Quick Actions ── */}
      <div className={`shrink-0 ${hasMessages ? 'border-t' : 'flex-1 flex flex-col justify-end'}`} style={{ borderColor: '#e5e7eb' }}>

        {/* Files picker panel */}
        {showFilesPicker && (
          <div className="mx-3 mb-2 rounded-xl border bg-white shadow-sm overflow-hidden" style={{ borderColor: '#e5e7eb' }}>
            <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: '#e5e7eb' }}>
              <span className="text-xs font-semibold text-gray-500">Файлы дела</span>
              <button onClick={() => setShowFilesPicker(false)} className="text-gray-400 hover:text-gray-600">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="max-h-48 overflow-y-auto">
              {loadingFiles ? (
                <div className="px-3 py-3 text-xs text-gray-400 text-center">Загрузка...</div>
              ) : caseFiles.length === 0 ? (
                <div className="px-3 py-3 text-xs text-gray-400 text-center">Файлы не найдены</div>
              ) : (
                caseFiles.map((file) => (
                  <button
                    key={file.id}
                    onClick={() => handleAttachFile(file)}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 transition-colors border-b last:border-0"
                    style={{ borderColor: '#f3f4f6' }}
                  >
                    <Paperclip className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                    <span className="text-xs text-gray-700 truncate">{file.filename}</span>
                  </button>
                ))
              )}
            </div>
          </div>
        )}

        {/* Templates panel */}
        {showTemplates && (
          <div className="mx-3 mb-2 rounded-xl border bg-gray-50 shadow-sm overflow-hidden" style={{ borderColor: '#e5e7eb' }}>
            <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: '#e5e7eb' }}>
              <span className="text-xs font-semibold text-gray-500">Шаблоны</span>
              <button onClick={() => setShowTemplates(false)} className="text-gray-400 hover:text-gray-600">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
            {TEMPLATE_PROMPTS.map((group) => (
              <div key={group.category} className="px-3 py-2 border-b last:border-0" style={{ borderColor: '#f3f4f6' }}>
                <p className="text-xs font-semibold text-gray-400 mb-1.5 uppercase tracking-wider">{group.category}</p>
                {group.items.map((item) => (
                  <button
                    key={item}
                    onClick={() => { setInputValue(item); setShowTemplates(false) }}
                    className="w-full text-left px-2 py-1.5 rounded-lg text-xs text-gray-700 hover:bg-gray-100 transition-colors"
                  >
                    {item}
                  </button>
                ))}
              </div>
            ))}
          </div>
        )}

        {/* Draft mode: cursor position indicator */}
        {mode === 'draft' && !activeSelection && activeSelectionRange && (
          <div className="mx-3 mb-2 flex items-center gap-2 px-3 py-2 rounded-xl border" style={{ background: '#f0fdf4', borderColor: '#bbf7d0' }}>
            <span className="text-xs" style={{ color: '#16a34a' }}>|</span>
            <span className="text-xs font-medium" style={{ color: '#16a34a' }}>Курсор установлен — текст будет вставлен в это место</span>
          </div>
        )}

        {/* Selection chip */}
        {activeSelection && (
          <div className="mx-3 mb-2 flex items-start gap-2 px-3 py-2 rounded-xl border" style={{ background: '#f5f5f5', borderColor: '#e5e7eb' }}>
            <Scissors className="w-3.5 h-3.5 shrink-0 mt-0.5" style={{ color: '#9ca3af' }} />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-semibold mb-0.5" style={{ color: '#6b7280' }}>Выделенный текст</div>
              <div className="text-xs leading-relaxed line-clamp-2" style={{ color: '#374151' }}>
                {activeSelection.slice(0, 120)}{activeSelection.length > 120 ? '…' : ''}
              </div>
            </div>
            <button
              onClick={clearActiveSelection}
              className="shrink-0 p-0.5 rounded hover:bg-gray-200 transition-colors"
              style={{ color: '#9ca3af' }}
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Input box */}
        <div className="px-3 pt-3 pb-2">
          <div className="rounded-2xl border bg-gray-50 overflow-hidden transition-shadow focus-within:shadow-sm focus-within:border-gray-300" style={{ borderColor: '#e5e7eb' }}>
            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={currentMode.placeholder}
              disabled={isLoading}
              rows={hasMessages ? 2 : 4}
              className="w-full px-4 pt-3 pb-2 text-sm resize-none outline-none bg-transparent text-gray-800 placeholder-gray-400"
            />
            {/* Toolbar */}
            <div className="flex items-center justify-between px-3 pb-2.5">
              <div className="flex items-center gap-0.5">

                {/* Mode selector dropdown */}
                <div ref={modeDropdownRef}>
                  <button
                    ref={modeButtonRef}
                    type="button"
                    onClick={() => {
                      if (showModeDropdown) {
                        setShowModeDropdown(false)
                        setModeDropdownPos(null)
                      } else {
                        const rect = modeButtonRef.current?.getBoundingClientRect()
                        if (rect) {
                          setModeDropdownPos({ top: rect.top - 4, left: rect.left })
                        }
                        setShowModeDropdown(true)
                      }
                    }}
                    className="flex items-center gap-1 px-2 py-1.5 rounded-lg hover:bg-gray-200 transition-colors text-xs font-semibold"
                    style={{ color: currentMode.color }}
                  >
                    {React.createElement(currentMode.icon, { className: "w-3.5 h-3.5" })}
                    {currentMode.label}
                    <ChevronDown className="w-3 h-3 text-gray-400" />
                  </button>
                </div>
                {showModeDropdown && modeDropdownPos && (
                  <div
                    ref={modeDropdownMenuRef}
                    className="bg-white border rounded-xl shadow-lg overflow-hidden z-[9999] min-w-[160px]"
                    style={{
                      position: 'fixed',
                      top: modeDropdownPos.top,
                      left: modeDropdownPos.left,
                      transform: 'translateY(-100%)',
                      borderColor: '#e5e7eb',
                    }}
                  >
                    {(Object.entries(MODE_CONFIG) as [EditorMode, typeof MODE_CONFIG[EditorMode]][]).map(([key, cfg]) => {
                      const Icon = cfg.icon
                      const isActive = mode === key
                      return (
                        <button
                          key={key}
                          onClick={() => { setMode(key); setInputValue(''); setShowModeDropdown(false); setModeDropdownPos(null) }}
                          className="w-full flex items-center gap-2.5 px-3 py-2.5 text-left hover:bg-gray-50 transition-colors"
                          style={{ color: isActive ? cfg.color : '#374151' }}
                        >
                          <Icon className="w-3.5 h-3.5 shrink-0" />
                          <div className="min-w-0">
                            <div className="text-xs font-semibold">{cfg.label}</div>
                            <div className="text-xs text-gray-400">{cfg.hint}</div>
                          </div>
                          {isActive && <Check className="w-3.5 h-3.5 ml-auto shrink-0" />}
                        </button>
                      )
                    })}
                  </div>
                )}

                {/* + files */}
                <button
                  type="button"
                  onClick={handleToggleFiles}
                  className="p-1.5 rounded-lg hover:bg-gray-200 transition-colors"
                  style={{ color: showFilesPicker ? currentMode.color : '#9ca3af' }}
                >
                  <Paperclip className="w-4 h-4" />
                </button>
                {/* Templates */}
                <button
                  type="button"
                  onClick={() => setShowTemplates(!showTemplates)}
                  className="p-1.5 rounded-lg transition-colors hover:bg-gray-200"
                  style={{ color: showTemplates ? currentMode.color : '#9ca3af' }}
                >
                  <ListPlus className="w-4 h-4" />
                </button>
                {/* Magic pencil */}
                <button
                  type="button"
                  onClick={handleMagicPencil}
                  disabled={!inputValue.trim()}
                  className="p-1.5 rounded-lg hover:bg-gray-200 transition-colors disabled:opacity-30"
                  style={{ color: '#9ca3af' }}
                >
                  <Sparkles className="w-4 h-4" />
                </button>
              </div>
              {/* Send */}
              <button
                type="button"
                onClick={() => handleSend(inputValue)}
                disabled={isLoading || !inputValue.trim()}
                className="w-8 h-8 flex items-center justify-center rounded-xl transition-all disabled:opacity-30"
                style={{
                  backgroundColor: inputValue.trim() && !isLoading ? '#111827' : '#e5e7eb',
                  color: inputValue.trim() && !isLoading ? 'white' : '#9ca3af',
                }}
              >
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Workflows */}
        {onRunPlaybook && !isLoading && (
          <div className="px-3 pb-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Workflows</span>
            </div>
            <button
              onClick={onRunPlaybook}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left hover:bg-gray-50 transition-colors group border"
              style={{ borderColor: '#e5e7eb' }}
            >
              <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ backgroundColor: '#d1fae5' }}>
                <BookOpen className="w-4 h-4" style={{ color: '#10b981' }} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-gray-800 group-hover:text-gray-900">Запустить Playbook</div>
                <div className="text-xs text-gray-400">Проверить документ по правилам</div>
              </div>
              <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-gray-500 shrink-0" />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
