"use client"

import React, { useState, useCallback, useRef, KeyboardEvent, useEffect } from "react"
import {
  streamDocumentChat,
  warmupEditorChat,
  createEditorChatSession,
} from "@/services/documentEditorApi"
import type { StructuredEdit } from "@/services/documentEditorApi"
import { EditSuggestionsList } from "./EditSuggestionCard"
import { buildEditorContextForChat } from "@/utils/editorContextWindow"
import {
  instructionIsDialogueContinuation,
  instructionTargetsBroaderDocument,
  instructionTargetsMultipleLocations,
  shouldScopeRequestToSelection,
  truncateSelectionPreview,
} from "@/utils/editorSelectionScope"
import { applyHybridEditWithFeedback } from "@/utils/applyHybridEdit"
import { getCaseFiles, UploadedFile } from "@/services/api"
import { toast } from "sonner"
import { Loader } from "@/components/ai-elements/loader"
import {
  Check, Edit3, HelpCircle, FileText,
  Sparkles, ListPlus, ArrowRight, ChevronDown, ChevronUp, X, Paperclip,
  BookOpen, ChevronRight, Mic, MicOff, MessageSquarePlus,
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
  ui_status?: 'acceptable' | 'needs_review' | 'not_acceptable' | string
  guidance?: string
  suggested_options?: { label: string; type: 'standard' | 'fallback' | string; text: string }[]
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
  onReplaceAllText?: (original: string, newText: string) => number
  onReplaceRange?: (from: number, to: number, text: string) => void
  onReplaceNodeById?: (nodeId: string, newText: string) => boolean
  onRunPlaybook?: () => void
  caseId?: string
  pendingPlaybookResult?: PlaybookResult | null
  onPlaybookResultConsumed?: () => void
  selectedText?: string
  selectionRange?: { from: number; to: number } | null
  onClearSelection?: () => void
  onScrollToText?: (text: string, nthOccurrence?: number) => boolean
  onReplaceTextFuzzy?: (original: string, newText: string) => boolean
  getDocumentContextForChat?: () => string
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

type EditStatus = 'accepted' | 'rejected'

function editStatusSets(messageId: string, editStatuses: Record<string, Record<string, EditStatus>>) {
  const row = editStatuses[messageId] || {}
  const appliedIds = new Set<string>()
  const skippedIds = new Set<string>()
  for (const [editId, status] of Object.entries(row)) {
    if (status === 'accepted') appliedIds.add(editId)
    if (status === 'rejected') skippedIds.add(editId)
  }
  return { appliedIds, skippedIds }
}

const SelectionFocusBanner: React.FC<{
  mode: EditorMode
  selectionPreview: string
  draftInput?: string
  hasDialogueHistory?: boolean
  onClear: () => void
}> = ({ mode, selectionPreview, draftInput, hasDialogueHistory = false, onClear }) => {
  const draft = draftInput || ''
  const usesWholeDocument =
    instructionTargetsBroaderDocument(draft) ||
    instructionTargetsMultipleLocations(draft) ||
    (hasDialogueHistory && instructionIsDialogueContinuation(draft))
  const isEdit = mode === 'edit'

  if (usesWholeDocument) {
    return (
      <div
        className="mx-3 mb-2 flex items-start gap-2 px-3 py-2.5 rounded-xl border"
        style={{ background: '#fffbeb', borderColor: '#fcd34d' }}
      >
        <HelpCircle className="w-4 h-4 shrink-0 mt-0.5" style={{ color: '#d97706' }} />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold" style={{ color: '#92400e' }}>
            Запрос затрагивает документ шире выделения — поиск по всему тексту
          </p>
          <p className="text-[11px] mt-0.5 leading-snug" style={{ color: '#b45309' }}>
            Выделение используется как подсказка; ИИ может предложить несколько правок.
          </p>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="shrink-0 text-[11px] font-medium px-2 py-1 rounded-lg border transition-colors hover:bg-amber-100"
          style={{ borderColor: '#fcd34d', color: '#92400e' }}
        >
          Снять
        </button>
      </div>
    )
  }

  return (
    <div
      className="mx-3 mb-2 flex items-start gap-2 px-3 py-2.5 rounded-xl border"
      style={{ background: isEdit ? '#eef2ff' : '#f0f9ff', borderColor: isEdit ? '#c7d2fe' : '#bae6fd' }}
    >
      <Edit3 className="w-4 h-4 shrink-0 mt-0.5" style={{ color: isEdit ? '#4f46e5' : '#0284c7' }} />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold" style={{ color: isEdit ? '#3730a3' : '#0369a1' }}>
          {isEdit
            ? 'Выделение — подсказка фокуса; при необходимости ИИ предложит правки в других местах'
            : 'Вопрос с учётом выделенного фрагмента'}
        </p>
        <p className="text-[11px] mt-1 leading-snug text-gray-600 line-clamp-2">
          «{truncateSelectionPreview(selectionPreview)}»
        </p>
        <p className="text-[10px] mt-1" style={{ color: '#6b7280' }}>
          Нужен другой раздел? Снимите выделение или укажите его в запросе (пункт, раздел).
        </p>
      </div>
      <button
        type="button"
        onClick={onClear}
        className="shrink-0 p-1 rounded-md text-gray-400 hover:text-gray-600 hover:bg-white/80"
        title="Снять выделение"
        aria-label="Снять выделение"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}

const DraftCard: React.FC<{
  text: string
  status: EditStatus | undefined
  onAccept: () => void
  onReject: () => void
}> = ({ text, status, onAccept, onReject }) => {
  const [expanded, setExpanded] = useState(false)
  const isLong = text.length > 300
  return (
    <div className="rounded-xl border overflow-hidden" style={{
      borderColor: status === 'accepted' ? '#bbf7d0' : status === 'rejected' ? '#fecaca' : '#e5e7eb',
      background: status === 'accepted' ? '#f0fdf4' : status === 'rejected' ? '#fef2f2' : '#f9fafb',
    }}>
      <div className="flex items-center gap-1.5 px-3 py-1.5 border-b" style={{
        borderColor: status === 'accepted' ? '#bbf7d0' : status === 'rejected' ? '#fecaca' : '#e5e7eb',
      }}>
        {status === 'accepted'
          ? <><Check className="w-3 h-3" style={{ color: '#16a34a' }} /><span className="text-xs font-semibold" style={{ color: '#16a34a' }}>Вставлено в документ</span></>
          : status === 'rejected'
          ? <><X className="w-3 h-3" style={{ color: '#ef4444' }} /><span className="text-xs font-semibold" style={{ color: '#ef4444' }}>Отклонено</span></>
          : <><FileText className="w-3 h-3" style={{ color: '#6b7280' }} /><span className="text-xs font-semibold" style={{ color: '#6b7280' }}>Черновик</span></>
        }
      </div>
      <div className={`px-3 py-2 text-xs leading-relaxed text-gray-700 whitespace-pre-wrap${isLong && !expanded ? ' line-clamp-4' : ''}`}>
        {text}
      </div>
      {isLong && (
        <button
          onClick={() => setExpanded(e => !e)}
          className="flex items-center gap-1 px-3 pb-1.5 text-xs transition-opacity hover:opacity-70"
          style={{ color: '#6b7280' }}
        >
          {expanded
            ? <><ChevronUp className="w-3 h-3" />Свернуть</>
            : <><ChevronDown className="w-3 h-3" />Читать полностью</>
          }
        </button>
      )}
      {!status && (
        <div className="flex items-center gap-2 px-3 pb-2.5 pt-1 border-t" style={{ borderColor: '#e5e7eb' }}>
          <button
            onClick={onReject}
            className="text-xs font-medium px-3 py-1.5 rounded-lg border transition-colors"
            style={{ borderColor: '#e5e7eb', color: '#9ca3af', background: 'transparent' }}
            onMouseEnter={e => { const el = e.currentTarget; el.style.borderColor = '#fca5a5'; el.style.color = '#ef4444'; el.style.background = 'rgba(239,68,68,0.05)' }}
            onMouseLeave={e => { const el = e.currentTarget; el.style.borderColor = '#e5e7eb'; el.style.color = '#9ca3af'; el.style.background = 'transparent' }}
          >
            Отклонить
          </button>
          <button
            onClick={onAccept}
            className="flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-lg border transition-colors"
            style={{ borderColor: '#d1d5db', color: '#374151', background: 'transparent' }}
            onMouseEnter={e => { const el = e.currentTarget; el.style.borderColor = '#10b981'; el.style.color = '#10b981'; el.style.background = 'rgba(16,185,129,0.07)' }}
            onMouseLeave={e => { const el = e.currentTarget; el.style.borderColor = '#d1d5db'; el.style.color = '#374151'; el.style.background = 'transparent' }}
          >
            <Check className="w-3 h-3" />
            Вставить
          </button>
        </div>
      )}
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
  onReplaceAllText,
  onReplaceRange,
  onReplaceNodeById,
  onRunPlaybook,
  caseId,
  pendingPlaybookResult,
  onPlaybookResultConsumed,
  selectedText,
  selectionRange,
  onClearSelection,
  onScrollToText,
  onReplaceTextFuzzy,
  getDocumentContextForChat,
}) => {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [mode, setMode] = useState<EditorMode>('edit')
  const [showModeDropdown, setShowModeDropdown] = useState(false)
  const [inputValue, setInputValue] = useState('')
  const [showTemplates, setShowTemplates] = useState(false)
  const [showFilesPicker, setShowFilesPicker] = useState(false)
  const [caseFiles, setCaseFiles] = useState<UploadedFile[]>([])
  const [attachedFileIds, setAttachedFileIds] = useState<string[]>([])
  const [loadingFiles, setLoadingFiles] = useState(false)
  const [editorSessionId, setEditorSessionId] = useState<string | undefined>(undefined)
  const [startingNewDialog, setStartingNewDialog] = useState(false)
  // Locked selection: captured from editor when user starts typing in chat
  const [activeSelection, setActiveSelection] = useState<string>('')
  const [activeSelectionRange, setActiveSelectionRange] = useState<{ from: number; to: number } | null>(null)
  const selectionClearedRef = useRef(false)
  // Per-message edit statuses: { messageId: { editId: 'accepted' | 'rejected' } }
  const [editStatuses, setEditStatuses] = useState<Record<string, Record<string, EditStatus>>>({})
  const [modeDropdownPos, setModeDropdownPos] = useState<{ top: number; left: number } | null>(null)
  const [isRecording, setIsRecording] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const modeDropdownRef = useRef<HTMLDivElement>(null)
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
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onresult = (e: any) => {
      const text = e.results[0][0].transcript
      if (text) setInputValue(prev => prev ? `${prev} ${text}` : text)
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onerror = (e: any) => {
      setIsRecording(false)
      if (e.error !== 'aborted') toast.error(`Ошибка распознавания: ${e.error}`)
    }
    recognition.start()
  }
  const modeDropdownMenuRef = useRef<HTMLDivElement>(null)
  const modeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Чат редактора только на время открытой страницы — не пишем в историю ассистента.
  useEffect(() => {
    return () => {
      setMessages([])
      setAttachedFileIds([])
      setInputValue('')
      setEditorSessionId(undefined)
    }
  }, [])

  // Прогрев LangGraph при открытии редактора (снижает задержку первого сообщения).
  useEffect(() => {
    if (!caseId || !documentId) return
    let cancelled = false
    warmupEditorChat(documentId, caseId, editorSessionId)
      .then((res) => {
        if (!cancelled && res.session_id) {
          setEditorSessionId(res.session_id)
        }
      })
      .catch(() => {
        /* warmup best-effort */
      })
    return () => {
      cancelled = true
    }
  }, [caseId, documentId])

  const handleNewDialog = useCallback(async () => {
    if (!caseId || startingNewDialog) return
    setStartingNewDialog(true)
    try {
      const res = await createEditorChatSession(documentId, caseId)
      setEditorSessionId(res.session_id)
      setMessages([])
      setEditStatuses({})
      setAttachedFileIds([])
      setInputValue('')
      await warmupEditorChat(documentId, caseId, res.session_id)
    } catch {
      toast.error('Не удалось начать новый диалог')
    } finally {
      setStartingNewDialog(false)
    }
  }, [caseId, documentId, startingNewDialog])

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
      // New text selected in editor — capture it
      selectionClearedRef.current = false
      setActiveSelection(selectedText.trim())
      setActiveSelectionRange(selectionRange || null)
    } else if (!selectedText || !selectedText.trim()) {
      // Selection removed in editor (user clicked away) — clear unless we just sent
      // and the parent prop hasn't updated yet (selectionClearedRef guards that case)
      if (!selectionClearedRef.current) {
        setActiveSelection('')
        if (mode !== 'draft') setActiveSelectionRange(null)
      }
      if (mode === 'draft' && selectionRange) {
        setActiveSelectionRange(selectionRange)
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedText, selectionRange, mode])

  const clearActiveSelection = () => {
    selectionClearedRef.current = true
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

  const MAX_ATTACHED_FILES = 3

  const handleAttachFile = (file: UploadedFile) => {
    if (attachedFileIds.length >= MAX_ATTACHED_FILES) {
      toast.error(`Можно прикрепить не более ${MAX_ATTACHED_FILES} файлов`)
      return
    }
    const tag = `[Файл: ${file.filename}]`
    setInputValue((prev) => prev ? `${prev}\n${tag}` : tag)
    setAttachedFileIds((prev) =>
      prev.includes(file.id) ? prev : [...prev, file.id],
    )
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

    const assistantId = `assistant-${Date.now()}`
    setMessages((prev) => [...prev, {
      id: assistantId,
      role: 'assistant',
      content: '',
      mode,
      selectionRange: selectionRangeSnapshot || undefined,
    }])

    const scopeToSelection = shouldScopeRequestToSelection(
      text.trim(),
      mode,
      selectionSnapshot,
      messages.length > 0,
    )

    const contextHtml = scopeToSelection
      ? buildEditorContextForChat(documentContent || '', {
          selectedText: selectionSnapshot,
        }).html
      : (getDocumentContextForChat?.() ??
        buildEditorContextForChat(documentContent || '').html)

    try {
      const response = await streamDocumentChat(
        documentId,
        text.trim(),
        {
          currentContent: contextHtml,
          mode,
          selectedText: scopeToSelection ? selectionSnapshot : undefined,
          selectionRange: scopeToSelection ? (selectionRangeSnapshot ?? undefined) : undefined,
          attachedFileIds: attachedFileIds.length ? attachedFileIds : undefined,
          sessionId: editorSessionId,
        },
        {
          onTurnStarted: () => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, content: '', structuredEdits: undefined }
                  : m,
              ),
            )
          },
          onContentSync: (content) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, content } : m,
              ),
            )
          },
          onTextDelta: (delta) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, content: m.content + delta } : m,
              ),
            )
          },
          onStructuredEdits: (edits) => {
            if (mode !== 'edit') return
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, structuredEdits: edits } : m,
              ),
            )
          },
          onCitations: (citations) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, citations } : m,
              ),
            )
          },
          onEditedContent: (content) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, editedContent: content } : m,
              ),
            )
          },
        },
      )

      const cleanAnswer = response.answer.trim() || 'Изменения готовы.'

      if (mode === 'draft' && cleanAnswer) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  content: '',
                  draftInsertedText: cleanAnswer,
                  selectionRange: selectionRangeSnapshot || undefined,
                }
              : m,
          ),
        )
        return
      }

      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
                ...m,
                content: cleanAnswer,
                citations: response.citations,
                editedContent: response.edited_content,
                structuredEdits:
                  mode === 'edit' && response.structured_edits?.length
                    ? response.structured_edits
                    : undefined,
              }
            : m,
        ),
      )
    } catch (err: any) {
      toast.error("Ошибка: " + (err.message || "Не удалось получить ответ"))
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: "Извините, произошла ошибка при обработке запроса." }
            : m,
        ),
      )
    } finally {
      setIsLoading(false)
    }
  }, [documentId, isLoading, mode, documentContent, activeSelection, activeSelectionRange, attachedFileIds, getDocumentContextForChat, onReplaceRange])

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

  const hybridHandlers = {
    onReplaceNodeById,
    onReplaceRange,
    onReplaceText,
    onReplaceTextFuzzy,
    onReplaceAllText,
  }

  const handleAcceptEdit = async (messageId: string, edit: StructuredEdit) => {
    const msg = messages.find(m => m.id === messageId)
    const result = applyHybridEditWithFeedback(edit, msg, hybridHandlers)
    if (result.success) {
      setStatus(messageId, edit.id, 'accepted')
      toast.success('Правка принята')
      return
    }
    if (result.copyText && navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(result.copyText)
        toast.error(result.failureMessage || 'Не удалось применить правку', {
          description: 'Новый текст скопирован в буфер обмена.',
        })
      } catch {
        toast.error(result.failureMessage || 'Не удалось применить правку')
      }
    } else {
      toast.error(result.failureMessage || 'Не удалось применить правку')
    }
  }

  const handleAcceptAllEdits = async (messageId: string, edits: StructuredEdit[]) => {
    const msg = messages.find(m => m.id === messageId)
    const pendingEdits = edits.filter(e => e.found_in_document !== false && !editStatuses[messageId]?.[e.id])

    let applied = 0
    for (const edit of pendingEdits) {
      const result = applyHybridEditWithFeedback(edit, msg, hybridHandlers)
      if (result.success) {
        setStatus(messageId, edit.id, 'accepted')
        applied++
      }
    }
    if (applied > 0) toast.success(`Принято правок: ${applied}`)
    if (applied < pendingEdits.length) {
      toast.error(`Не применено: ${pendingEdits.length - applied}. Скопируйте текст вручную.`)
    }
  }

  const handleDismissEdit = (messageId: string, editId: string) => {
    setStatus(messageId, editId, 'rejected')
  }

  const handleSkipAllEdits = (messageId: string, edits: StructuredEdit[]) => {
    const { appliedIds, skippedIds } = editStatusSets(messageId, editStatuses)
    edits.forEach((edit) => {
      if (!appliedIds.has(edit.id) && !skippedIds.has(edit.id)) {
        setStatus(messageId, edit.id, 'rejected')
      }
    })
  }

  const currentMode = MODE_CONFIG[mode]
  const hasMessages = messages.length > 0

  return (
    <div className="flex flex-col h-full bg-white">

      {/* ── Header ── */}
      <div className="px-4 pt-4 pb-3 border-b shrink-0" style={{ borderColor: '#e5e7eb', height: '54px' }}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider shrink-0">AI Ассистент</span>
          <div className="flex items-center gap-1 min-w-0">
            <button
              type="button"
              onClick={() => void handleNewDialog()}
              disabled={!caseId || startingNewDialog || isLoading}
              title="Новый диалог"
              className="shrink-0 p-1 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 disabled:opacity-40"
            >
              <MessageSquarePlus className="w-3.5 h-3.5" />
            </button>
            <span className="text-xs text-gray-400 truncate max-w-[120px]">{documentTitle}</span>
          </div>
        </div>
      </div>

      {/* ── Messages ── */}
      {hasMessages && (
        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3 min-h-0">
          {messages.map((message) => {
            if (message.role === "user") {
              return (
                <div key={message.id} className="flex flex-col items-end gap-1.5">
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
                {/* Draft text card with accept/reject */}
                {message.draftInsertedText && (
                  <DraftCard
                    text={message.draftInsertedText}
                    status={editStatuses[message.id]?.['draft']}
                    onReject={() => setStatus(message.id, 'draft', 'rejected')}
                    onAccept={() => {
                      if (onReplaceRange && message.selectionRange) {
                        onReplaceRange(message.selectionRange.from, message.selectionRange.to, message.draftInsertedText!)
                      } else if (onApplyEdit) {
                        onApplyEdit(message.draftInsertedText!)
                      }
                      setStatus(message.id, 'draft', 'accepted')
                      toast.success('Текст вставлен')
                    }}
                  />
                )}
                {message.content && (
                  <div className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
                    {renderMarkdown(message.content)}
                  </div>
                )}

                {/* Structured edits — тот же UI, что в основном чате сервиса */}
                {allEdits.length > 0 && (
                  <EditSuggestionsList
                    edits={allEdits}
                    onApply={(edit) => void handleAcceptEdit(message.id, edit)}
                    onSkip={(edit) => handleDismissEdit(message.id, edit.id)}
                    onNavigate={(text) => {
                      if (onScrollToText) onScrollToText(text, 0)
                    }}
                    onApplyAll={() => void handleAcceptAllEdits(message.id, allEdits)}
                    onSkipAll={() => handleSkipAllEdits(message.id, allEdits)}
                    appliedIds={editStatusSets(message.id, editStatuses).appliedIds}
                    skippedIds={editStatusSets(message.id, editStatuses).skippedIds}
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
                      <span key={c.file_id} className="text-xs px-2 py-0.5 rounded-full bg-secondary text-accent-muted border border-border-subtle">
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
              <span className="text-xs font-semibold text-gray-500">
                Файлы дела (до {MAX_ATTACHED_FILES})
              </span>
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

        {/* Плашка: выделенный фрагмент влияет на запрос */}
        {activeSelection && (mode === 'edit' || mode === 'ask') && (
          <SelectionFocusBanner
            mode={mode}
            selectionPreview={activeSelection}
            draftInput={inputValue}
            hasDialogueHistory={messages.length > 0}
            onClear={clearActiveSelection}
          />
        )}

        {/* Без выделения в Edit — поиск по всему документу */}
        {!activeSelection && mode === 'edit' && (
          <div
            className="mx-3 mb-2 flex items-center gap-2 px-3 py-2 rounded-xl border border-dashed"
            style={{ borderColor: '#e5e7eb', background: '#fafafa' }}
          >
            <Sparkles className="w-3.5 h-3.5 text-gray-400 shrink-0" />
            <span className="text-[11px] text-gray-500 leading-snug">
              Выделения нет — ИИ найдёт нужный фрагмент по всему документу
            </span>
          </div>
        )}

        {attachedFileIds.length > 0 && (
          <div className="mx-3 mb-2 flex flex-wrap gap-1.5">
            {attachedFileIds.map((fileId) => {
              const file = caseFiles.find((f) => f.id === fileId)
              const label = file?.filename || fileId.slice(0, 8)
              return (
                <span
                  key={fileId}
                  className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-100"
                >
                  <Paperclip className="w-3 h-3" />
                  {label}
                  <button
                    type="button"
                    onClick={() => setAttachedFileIds((prev) => prev.filter((id) => id !== fileId))}
                    className="hover:text-indigo-900"
                    aria-label="Убрать файл"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              )
            })}
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
                          onClick={() => { setMode(key); setShowModeDropdown(false); setModeDropdownPos(null) }}
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
              {/* Mic */}
              <button
                type="button"
                onClick={toggleRecording}
                disabled={isLoading}
                className="w-8 h-8 flex items-center justify-center rounded-xl transition-all disabled:opacity-30"
                style={{
                  backgroundColor: isRecording ? '#FEE2E2' : 'transparent',
                  color: isRecording ? '#DC2626' : '#9ca3af',
                }}
              >
                {isRecording ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
              </button>
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

        {/* Playbook */}
        {onRunPlaybook && !isLoading && (
          <div className="px-3 pb-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Playbook</span>
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
