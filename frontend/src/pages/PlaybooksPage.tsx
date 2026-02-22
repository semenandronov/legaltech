/**
 * Playbooks Management Page - Enhanced with Legora-style features
 * 
 * Улучшения:
 * 1. Визуальный редактор правил с drag-and-drop
 * 2. Предпросмотр результатов проверки
 * 3. Интеграция с Document Viewer
 */
import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import {
  BookOpen,
  Plus,
  Search,
  ChevronDown,
  AlertTriangle,
  CheckCircle,
  XCircle,
  MoreVertical,
  Copy,
  Trash2,
  Edit,
  FileText,
  Loader2,
  Shield,
  Target,
  Ban,
  Save,
  ArrowLeft,
  MessageSquare,
  Table,
  FileEdit,
  Workflow,
  GripVertical,
  Eye,
  Sparkles,
  Layers,
  Settings,
  ChevronUp,
  Info,
  X
} from 'lucide-react'
import { toast } from 'sonner'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import * as playbooksApi from '../services/playbooksApi'
import type { Playbook, PlaybookRule, PlaybookCheck } from '../services/playbooksApi'

// ==================== HARVEY FIELDS HELPERS ====================
interface HarveyFields {
  standard_position: string
  fallback_positions: string[]        // multiple fallback positions
  unacceptable_deviations: string[]   // multiple unacceptable deviations
  internal_guidance: string
  mark_missing_as_violation: boolean  // if clause not found → mark as not acceptable
}

const EMPTY_HARVEY: HarveyFields = {
  standard_position: '',
  fallback_positions: [''],
  unacceptable_deviations: [],
  internal_guidance: '',
  mark_missing_as_violation: false,
}

/**
 * Parse Harvey fields from backend data.
 * Priority: structured fallback_options JSON > old serialized description format.
 */
const parseHarveyFromDescription = (
  description?: string,
  suggested_clause_template?: string,
  fallback_options?: any
): HarveyFields => {
  // 1. Try structured fallback_options JSON (new format)
  if (fallback_options && typeof fallback_options === 'object' && !Array.isArray(fallback_options)) {
    const fo = fallback_options as any
    if (fo.fallbacks !== undefined || fo.unacceptable !== undefined) {
      return {
        standard_position: suggested_clause_template || fo.standard_position || '',
        fallback_positions: Array.isArray(fo.fallbacks) && fo.fallbacks.length > 0 ? fo.fallbacks : [''],
        unacceptable_deviations: Array.isArray(fo.unacceptable) ? fo.unacceptable : [],
        internal_guidance: description || fo.guidance || '',
        mark_missing_as_violation: fo.mark_missing ?? false,
      }
    }
  }
  // 2. Backward compat: old serialized description format
  const desc = description || ''
  const hasHarveyFormat = desc.includes('СТАНДАРТ:') || desc.includes('ЗАПАСНОЙ ВАРИАНТ:') ||
                          desc.includes('НЕДОПУСТИМО:') || desc.includes('ИНСТРУКЦИИ:')
  if (!hasHarveyFormat) {
    return {
      standard_position: suggested_clause_template || '',
      fallback_positions: [''],
      unacceptable_deviations: [],
      internal_guidance: desc,
      mark_missing_as_violation: false,
    }
  }
  const sections: Record<string, string> = {}
  const parts = desc.split('\n\n')
  for (const part of parts) {
    const colonIdx = part.indexOf(':')
    if (colonIdx > 0) {
      const key = part.substring(0, colonIdx).trim()
      const value = part.substring(colonIdx + 1).trim()
      sections[key] = value
    }
  }
  return {
    standard_position: sections['СТАНДАРТ'] || suggested_clause_template || '',
    fallback_positions: sections['ЗАПАСНОЙ ВАРИАНТ'] ? [sections['ЗАПАСНОЙ ВАРИАНТ']] : [''],
    unacceptable_deviations: sections['НЕДОПУСТИМО'] ? [sections['НЕДОПУСТИМО']] : [],
    internal_guidance: sections['ИНСТРУКЦИИ'] || '',
    mark_missing_as_violation: false,
  }
}

// ==================== RULE TYPE BADGE ====================
const RuleTypeBadge = ({ type, size = 'sm' }: { type: string; size?: 'sm' | 'lg' }) => {
  const getStyle = () => {
    switch (type) {
      case 'red_line':
        return { bg: 'rgba(239, 68, 68, 0.15)', color: '#ef4444', icon: Target, label: 'Red Line', description: 'Обязательное требование' }
      case 'no_go':
        return { bg: 'rgba(220, 38, 38, 0.15)', color: '#dc2626', icon: Ban, label: 'No-Go', description: 'Запрещённое условие' }
      case 'fallback':
        return { bg: 'rgba(234, 179, 8, 0.15)', color: '#eab308', icon: Shield, label: 'Fallback', description: 'Рекомендуемое условие' }
      default:
        return { bg: 'rgba(156, 163, 175, 0.15)', color: '#9ca3af', icon: Shield, label: type, description: '' }
    }
  }

  const style = getStyle()
  const Icon = style.icon
  const isLarge = size === 'lg'

  return (
    <div
      className={`inline-flex items-center gap-1.5 ${isLarge ? 'px-3 py-1.5' : 'px-2 py-0.5'} rounded-lg ${isLarge ? 'text-sm' : 'text-xs'} font-medium`}
      style={{ backgroundColor: style.bg, color: style.color }}
      title={style.description}
    >
      <Icon className={isLarge ? 'w-4 h-4' : 'w-3 h-3'} />
      {style.label}
    </div>
  )
}

// ==================== CONDITION TYPE DISPLAY ====================
const ConditionTypeDisplay = ({ type }: { type: string }) => {
  const labels: Record<string, string> = {
    'must_exist': 'Должен присутствовать',
    'must_not_exist': 'Не должен присутствовать',
    'value_check': 'Проверка значения',
    'duration_check': 'Проверка срока',
    'text_match': 'Содержит текст',
    'text_not_match': 'Не содержит текст'
  }
  return <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{labels[type] || type}</span>
}

// ==================== DRAGGABLE RULE CARD ====================
const DraggableRuleCard = ({
  rule,
  index,
  isExpanded,
  onToggleExpand,
  onEdit,
  onDelete,
  onDragStart,
  onDragOver,
  onDrop,
  isDragging,
  harveyFields
}: {
  rule: PlaybookRule
  index: number
  isExpanded: boolean
  onToggleExpand: () => void
  onEdit: () => void
  onDelete: () => void
  onDragStart: (e: React.DragEvent, index: number) => void
  onDragOver: (e: React.DragEvent) => void
  onDrop: (e: React.DragEvent, index: number) => void
  isDragging: boolean
  harveyFields?: HarveyFields
}) => {
  const fields = harveyFields || parseHarveyFromDescription(rule.description, rule.suggested_clause_template)
  return (
    <div
      draggable
      onDragStart={(e) => onDragStart(e, index)}
      onDragOver={onDragOver}
      onDrop={(e) => onDrop(e, index)}
      className={`rounded-xl border transition-all ${isDragging ? 'opacity-50 scale-95' : ''}`}
      style={{
        backgroundColor: 'var(--color-bg-secondary)',
        borderColor: isExpanded ? 'var(--color-accent)' : 'var(--color-border)'
      }}
    >
      {/* Header - always visible */}
      <div
        className="flex items-center gap-3 p-4 cursor-pointer"
        onClick={onToggleExpand}
      >
        {/* Drag handle */}
        <div
          className="p-1 rounded cursor-grab active:cursor-grabbing hover:bg-bg-hover"
          style={{ color: 'var(--color-text-tertiary)' }}
          onClick={(e) => e.stopPropagation()}
        >
          <GripVertical className="w-4 h-4" />
        </div>

        {/* Priority indicator */}
        <div 
          className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
          style={{ 
            backgroundColor: 'var(--color-bg-hover)',
            color: 'var(--color-text-secondary)'
          }}
        >
          {index + 1}
        </div>

        {/* Rule info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <RuleTypeBadge type={rule.rule_type} />
            <span className="font-medium truncate" style={{ color: 'var(--color-text-primary)' }}>
              {rule.rule_name || 'Без названия'}
            </span>
          </div>
          <ConditionTypeDisplay type={rule.condition_type} />
        </div>

        {/* Expand indicator */}
        {isExpanded ? (
          <ChevronUp className="w-5 h-5" style={{ color: 'var(--color-text-tertiary)' }} />
        ) : (
          <ChevronDown className="w-5 h-5" style={{ color: 'var(--color-text-tertiary)' }} />
        )}
      </div>

      {/* Expanded content */}
      {isExpanded && (
        <div
          className="px-4 pb-4 pt-0 border-t"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div className="pt-4 space-y-3">
            {/* Harvey sections */}
            {fields.standard_position && (
              <div className="rounded-lg p-3" style={{ backgroundColor: 'rgba(34, 197, 94, 0.08)' }}>
                <p className="text-xs font-semibold mb-1" style={{ color: '#22c55e' }}>✅ Стандартная позиция</p>
                <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>{fields.standard_position}</p>
              </div>
            )}
            {fields.fallback_positions.some(Boolean) && (
              <div className="rounded-lg p-3" style={{ backgroundColor: 'rgba(234, 179, 8, 0.08)' }}>
                <p className="text-xs font-semibold mb-1.5" style={{ color: '#eab308' }}>🟡 Запасные варианты</p>
                <ul className="space-y-1">
                  {fields.fallback_positions.filter(Boolean).map((pos, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="text-xs font-semibold mt-0.5 shrink-0" style={{ color: '#eab308' }}>{i + 1}.</span>
                      <span className="text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>{pos}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {fields.unacceptable_deviations.some(Boolean) && (
              <div className="rounded-lg p-3" style={{ backgroundColor: 'rgba(239, 68, 68, 0.08)' }}>
                <p className="text-xs font-semibold mb-1.5" style={{ color: '#ef4444' }}>❌ Недопустимые отклонения</p>
                <ul className="space-y-1">
                  {fields.unacceptable_deviations.filter(Boolean).map((dev, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="text-xs font-bold mt-0.5 shrink-0" style={{ color: '#ef4444' }}>✕</span>
                      <span className="text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>{dev}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {fields.internal_guidance && (
              <div className="rounded-lg p-3" style={{ backgroundColor: 'rgba(99, 102, 241, 0.08)' }}>
                <p className="text-xs font-semibold mb-1" style={{ color: 'var(--color-accent)' }}>📋 Внутренние инструкции</p>
                <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>{fields.internal_guidance}</p>
              </div>
            )}
            {fields.mark_missing_as_violation && (
              <div className="flex items-center gap-2 px-3 py-2 rounded-lg" style={{ backgroundColor: 'rgba(239, 68, 68, 0.06)' }}>
                <span className="text-xs" style={{ color: '#ef4444' }}>⚑</span>
                <span className="text-xs font-medium" style={{ color: '#ef4444' }}>Отсутствие → Неприемлемо</span>
              </div>
            )}
            {!fields.standard_position && !fields.fallback_positions.some(Boolean) && !fields.unacceptable_deviations.some(Boolean) && !fields.internal_guidance && (
              <p className="text-sm italic" style={{ color: 'var(--color-text-tertiary)' }}>Нет описания</p>
            )}

            {/* Actions */}
            <div className="flex items-center gap-2 pt-1">
              <button
                onClick={(e) => { e.stopPropagation(); onEdit(); }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors hover:bg-bg-hover"
                style={{ color: 'var(--color-text-primary)' }}
              >
                <Edit className="w-4 h-4" />
                Редактировать
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(); }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors hover:bg-red-500/10"
                style={{ color: '#ef4444' }}
              >
                <Trash2 className="w-4 h-4" />
                Удалить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ==================== RULE TEMPLATES ====================
const ruleTemplates = [
  {
    name: 'Срок конфиденциальности',
    rule_type: 'red_line',
    clause_category: 'confidentiality',
    condition_type: 'duration_check',
    description: 'Проверка срока действия обязательств о конфиденциальности'
  },
  {
    name: 'Ограничение ответственности',
    rule_type: 'red_line',
    clause_category: 'liability',
    condition_type: 'must_exist',
    description: 'Должен присутствовать пункт об ограничении ответственности'
  },
  {
    name: 'Неограниченная ответственность',
    rule_type: 'no_go',
    clause_category: 'liability',
    condition_type: 'must_not_exist',
    description: 'Не должно быть условий о неограниченной ответственности'
  },
  {
    name: 'Индемнификация',
    rule_type: 'fallback',
    clause_category: 'indemnification',
    condition_type: 'must_exist',
    description: 'Рекомендуется включить пункт об индемнификации'
  },
  {
    name: 'Применимое право',
    rule_type: 'red_line',
    clause_category: 'governing_law',
    condition_type: 'text_match',
    description: 'Проверка указания применимого права'
  }
]

// ==================== PLAYBOOK CARD ====================
const PlaybookCard = ({
  playbook,
  onEdit,
  onDuplicate,
  onDelete,
  onPreview
}: {
  playbook: Playbook
  onEdit: () => void
  onDuplicate: () => void
  onDelete: () => void
  onPreview: () => void
}) => {
  const [menuOpen, setMenuOpen] = useState(false)

  const getRulesCount = () => {
    const redLines = playbook.rules?.filter(r => r.rule_type === 'red_line').length || 0
    const fallbacks = playbook.rules?.filter(r => r.rule_type === 'fallback').length || 0
    const noGos = playbook.rules?.filter(r => r.rule_type === 'no_go').length || 0
    return { redLines, fallbacks, noGos, total: redLines + fallbacks + noGos }
  }

  const counts = getRulesCount()

  return (
    <div
      className="group relative rounded-xl border p-5 transition-all hover:border-accent/50 hover:shadow-lg"
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
            <BookOpen className="w-6 h-6" style={{ color: 'var(--color-accent)' }} />
          </div>
          <div>
            <h3
              className="font-semibold text-base cursor-pointer hover:text-accent transition-colors"
              style={{ color: 'var(--color-text-primary)' }}
              onClick={onEdit}
            >
              {playbook.display_name}
            </h3>
            <div className="flex items-center gap-2 mt-0.5">
              {playbook.is_system && (
                <span className="text-xs px-1.5 py-0.5 rounded" style={{ backgroundColor: 'rgba(99, 102, 241, 0.1)', color: 'var(--color-accent)' }}>
                  Системный
                </span>
              )}
              {playbook.document_type && (
                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  {playbook.document_type}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Menu */}
        <div className="relative">
          <button
            className="p-1.5 rounded-lg hover:bg-bg-hover opacity-0 group-hover:opacity-100 transition-all"
            style={{ color: 'var(--color-text-secondary)' }}
            onClick={() => setMenuOpen(!menuOpen)}
          >
            <MoreVertical className="w-4 h-4" />
          </button>

          {menuOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
              <div
                className="absolute right-0 top-8 w-44 rounded-xl border shadow-xl py-1.5 z-20"
                style={{
                  backgroundColor: 'var(--color-bg-primary)',
                  borderColor: 'var(--color-border)'
                }}
              >
                <button
                  className="w-full px-3 py-2 text-left text-sm flex items-center gap-2.5 hover:bg-bg-hover transition-colors"
                  style={{ color: 'var(--color-text-primary)' }}
                  onClick={() => { onPreview(); setMenuOpen(false); }}
                >
                  <Eye className="w-4 h-4" />
                  Предпросмотр
                </button>
                <button
                  className="w-full px-3 py-2 text-left text-sm flex items-center gap-2.5 hover:bg-bg-hover transition-colors"
                  style={{ color: 'var(--color-text-primary)' }}
                  onClick={() => { onEdit(); setMenuOpen(false); }}
                >
                  <Edit className="w-4 h-4" />
                  Редактировать
                </button>
                <button
                  className="w-full px-3 py-2 text-left text-sm flex items-center gap-2.5 hover:bg-bg-hover transition-colors"
                  style={{ color: 'var(--color-text-primary)' }}
                  onClick={() => { onDuplicate(); setMenuOpen(false); }}
                >
                  <Copy className="w-4 h-4" />
                  Дублировать
                </button>
                {!playbook.is_system && (
                  <>
                    <div className="my-1.5 border-t" style={{ borderColor: 'var(--color-border)' }} />
                    <button
                      className="w-full px-3 py-2 text-left text-sm flex items-center gap-2.5 hover:bg-red-500/10 transition-colors"
                      style={{ color: '#ef4444' }}
                      onClick={() => { onDelete(); setMenuOpen(false); }}
                    >
                      <Trash2 className="w-4 h-4" />
                      Удалить
                    </button>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Description */}
      {playbook.description && (
        <p
          className="text-sm mb-4 line-clamp-2"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {playbook.description}
        </p>
      )}

      {/* Rules summary */}
      <div className="flex items-center gap-3 mb-4">
        {counts.redLines > 0 && (
          <div className="flex items-center gap-1 text-xs" style={{ color: '#ef4444' }}>
            <Target className="w-3.5 h-3.5" />
            <span>{counts.redLines}</span>
          </div>
        )}
        {counts.fallbacks > 0 && (
          <div className="flex items-center gap-1 text-xs" style={{ color: '#eab308' }}>
            <Shield className="w-3.5 h-3.5" />
            <span>{counts.fallbacks}</span>
          </div>
        )}
        {counts.noGos > 0 && (
          <div className="flex items-center gap-1 text-xs" style={{ color: '#dc2626' }}>
            <Ban className="w-3.5 h-3.5" />
            <span>{counts.noGos}</span>
          </div>
        )}
        <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {counts.total} правил
        </span>
      </div>

      {/* Stats */}
      <div className="flex items-center gap-4 text-xs mb-4" style={{ color: 'var(--color-text-tertiary)' }}>
        <span className="flex items-center gap-1">
          <CheckCircle className="w-3.5 h-3.5" />
          {playbook.usage_count || 0} проверок
        </span>
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={onEdit}
          className="flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors hover:bg-accent/10"
          style={{
            backgroundColor: 'var(--color-bg-hover)',
            color: 'var(--color-text-primary)',
          }}
        >
          <Edit className="w-4 h-4" />
          Редактировать
        </button>
      </div>
    </div>
  )
}

// ==================== ENHANCED PLAYBOOK EDITOR ====================
const PlaybookEditor = ({
  playbook,
  onSave,
  onCancel,
  isNew
}: {
  playbook: Partial<Playbook>
  onSave: (data: Partial<Playbook>) => void
  onCancel: () => void
  isNew: boolean
}) => {
  const [form, setForm] = useState({
    name: playbook.name || '',
    display_name: playbook.display_name || '',
    description: playbook.description || '',
    document_type: playbook.document_type || 'contract',
    jurisdiction: playbook.jurisdiction || '',
    is_public: playbook.is_public || false,
    rules: playbook.rules || []
  })
  const [expandedRules, setExpandedRules] = useState<Set<number>>(new Set())
  const [editingRuleIndex, setEditingRuleIndex] = useState<number | null>(null)
  const [showTemplates, setShowTemplates] = useState(false)
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null)
  const [activeSection, setActiveSection] = useState<'settings' | 'rules'>('rules')

  // Harvey fields — keyed by rule.id
  const [ruleHarveyFields, setRuleHarveyFields] = useState<Record<string, HarveyFields>>(() => {
    const fields: Record<string, HarveyFields> = {}
    playbook.rules?.forEach((rule) => {
      fields[rule.id] = parseHarveyFromDescription(rule.description, rule.suggested_clause_template, rule.fallback_options)
    })
    return fields
  })

  const updateHarveyField = (ruleId: string, field: keyof HarveyFields, value: string | boolean | string[]) => {
    setRuleHarveyFields(prev => ({
      ...prev,
      [ruleId]: { ...prev[ruleId] || EMPTY_HARVEY, [field]: value }
    }))
  }

  const addHarveyArrayItem = (ruleId: string, field: 'fallback_positions' | 'unacceptable_deviations') => {
    setRuleHarveyFields(prev => {
      const current = prev[ruleId] || EMPTY_HARVEY
      return { ...prev, [ruleId]: { ...current, [field]: [...current[field], ''] } }
    })
  }

  const removeHarveyArrayItem = (ruleId: string, field: 'fallback_positions' | 'unacceptable_deviations', index: number) => {
    setRuleHarveyFields(prev => {
      const current = prev[ruleId] || EMPTY_HARVEY
      const newArr = current[field].filter((_, i) => i !== index)
      return { ...prev, [ruleId]: { ...current, [field]: newArr.length > 0 ? newArr : [''] } }
    })
  }

  const updateHarveyArrayItem = (ruleId: string, field: 'fallback_positions' | 'unacceptable_deviations', index: number, value: string) => {
    setRuleHarveyFields(prev => {
      const current = prev[ruleId] || EMPTY_HARVEY
      const newArr = [...current[field]]
      newArr[index] = value
      return { ...prev, [ruleId]: { ...current, [field]: newArr } }
    })
  }

  // Toggle rule expansion
  const toggleRuleExpand = (index: number) => {
    setExpandedRules(prev => {
      const newSet = new Set(prev)
      if (newSet.has(index)) {
        newSet.delete(index)
      } else {
        newSet.add(index)
      }
      return newSet
    })
  }

  // Add rule from template
  const addRuleFromTemplate = (template: typeof ruleTemplates[0]) => {
    const newRule: PlaybookRule = {
      id: `new_${Date.now()}`,
      playbook_id: playbook.id || '',
      rule_type: template.rule_type as any,
      clause_category: template.clause_category,
      rule_name: template.name,
      description: template.description,
      condition_type: template.condition_type,
      condition_config: {},
      priority: form.rules.length,
      severity: 'medium',
      is_active: true,
      created_at: new Date().toISOString()
    }
    setRuleHarveyFields(prev => ({
      ...prev,
      [newRule.id]: parseHarveyFromDescription(template.description, undefined)
    }))
    setForm(prev => ({ ...prev, rules: [...prev.rules, newRule] }))
    setShowTemplates(false)
    toast.success('Правило добавлено')
  }

  // Add blank rule
  const addBlankRule = () => {
    const newRule: PlaybookRule = {
      id: `new_${Date.now()}`,
      playbook_id: playbook.id || '',
      rule_type: 'red_line',
      clause_category: '',
      rule_name: '',
      description: '',
      condition_type: 'must_exist',
      condition_config: {},
      priority: form.rules.length,
      severity: 'medium',
      is_active: true,
      created_at: new Date().toISOString()
    }
    setRuleHarveyFields(prev => ({ ...prev, [newRule.id]: { ...EMPTY_HARVEY } }))
    setForm(prev => ({ ...prev, rules: [...prev.rules, newRule] }))
    setEditingRuleIndex(form.rules.length)
    setExpandedRules(prev => new Set(prev).add(form.rules.length))
  }

  // Update rule
  const updateRule = (index: number, updates: Partial<PlaybookRule>) => {
    setForm(prev => ({
      ...prev,
      rules: prev.rules.map((r, i) => i === index ? { ...r, ...updates } : r)
    }))
  }

  // Remove rule
  const removeRule = (index: number) => {
    setForm(prev => ({
      ...prev,
      rules: prev.rules.filter((_, i) => i !== index)
    }))
    setEditingRuleIndex(null)
  }

  // Drag and drop handlers
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

    const newRules = [...form.rules]
    const [draggedRule] = newRules.splice(draggedIndex, 1)
    newRules.splice(dropIndex, 0, draggedRule)
    
    // Update priorities
    newRules.forEach((rule, i) => {
      rule.priority = i
    })

    setForm(prev => ({ ...prev, rules: newRules }))
    setDraggedIndex(null)
    toast.success('Порядок правил обновлён')
  }

  return (
    <div className="h-full flex flex-col" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      {/* Header */}
      <div
        className="flex items-center justify-between px-6 py-4 border-b shrink-0"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-center gap-4">
          <button
            onClick={onCancel}
            className="p-2 rounded-lg hover:bg-bg-hover transition-colors"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <h2 className="text-xl font-bold" style={{ color: 'var(--color-text-primary)' }}>
              {isNew ? 'Создание Playbook' : 'Редактирование Playbook'}
            </h2>
            <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              {form.display_name || 'Новый playbook'}
            </p>
          </div>
        </div>
        <button
          onClick={() => {
            // Validate required fields
            if (!form.name || form.name.length < 1) {
              toast.error('Укажите идентификатор playbook')
              return
            }
            if (!form.display_name || form.display_name.length < 1) {
              toast.error('Укажите название playbook')
              return
            }
            if (!form.document_type) {
              toast.error('Выберите тип документа')
              return
            }
            // Validate rules
            for (const rule of form.rules) {
              if (!rule.rule_name || rule.rule_name.length < 1) {
                toast.error('Все правила должны иметь название')
                return
              }
            }
            // Serialize Harvey fields into backend fields
            const normalizedRules = form.rules.map(r => {
              const harvey = ruleHarveyFields[r.id] || EMPTY_HARVEY
              const fallbackOptions = {
                standard_position: harvey.standard_position,
                fallbacks: harvey.fallback_positions.filter(Boolean),
                unacceptable: harvey.unacceptable_deviations.filter(Boolean),
                guidance: harvey.internal_guidance,
                mark_missing: harvey.mark_missing_as_violation,
              }
              return {
                ...r,
                description: harvey.internal_guidance || r.description,
                suggested_clause_template: harvey.standard_position || r.suggested_clause_template,
                fallback_options: fallbackOptions,
                clause_category: r.clause_category || r.rule_name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_а-яё]/gi, '').slice(0, 40) || 'general'
              }
            })
            onSave({ ...form, rules: normalizedRules })
          }}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-colors"
          style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
        >
          <Save className="w-4 h-4" />
          Сохранить
        </button>
      </div>

      {/* Tabs */}
      <div
        className="flex items-center gap-1 px-6 py-2 border-b"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <button
          onClick={() => setActiveSection('rules')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeSection === 'rules' ? 'bg-accent/10' : 'hover:bg-bg-hover'
          }`}
          style={{ color: activeSection === 'rules' ? 'var(--color-accent)' : 'var(--color-text-secondary)' }}
        >
          <Layers className="w-4 h-4" />
          Правила ({form.rules.length})
        </button>
        <button
          onClick={() => setActiveSection('settings')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeSection === 'settings' ? 'bg-accent/10' : 'hover:bg-bg-hover'
          }`}
          style={{ color: activeSection === 'settings' ? 'var(--color-accent)' : 'var(--color-text-secondary)' }}
        >
          <Settings className="w-4 h-4" />
          Настройки
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {activeSection === 'settings' ? (
          /* Settings Section */
          <div className="p-6 max-w-2xl space-y-6">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  Идентификатор (ID)
                </label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ 
                    ...form, 
                    name: e.target.value
                      .toLowerCase()
                      .replace(/\s+/g, '_')
                      .replace(/[^a-z0-9_]/g, '') // Remove invalid characters
                  })}
                  placeholder="nda_compliance"
                  className="w-full px-4 py-2.5 rounded-lg border text-sm transition-colors focus:border-accent outline-none"
                  style={{
                    backgroundColor: 'var(--color-bg-secondary)',
                    borderColor: 'var(--color-border)',
                    color: 'var(--color-text-primary)'
                  }}
                />
                <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                  Только строчные буквы (a-z), цифры и подчёркивания
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  Название
                </label>
                <input
                  type="text"
                  value={form.display_name}
                  onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                  placeholder="NDA Compliance Check"
                  className="w-full px-4 py-2.5 rounded-lg border text-sm transition-colors focus:border-accent outline-none"
                  style={{
                    backgroundColor: 'var(--color-bg-secondary)',
                    borderColor: 'var(--color-border)',
                    color: 'var(--color-text-primary)'
                  }}
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                Описание
              </label>
              <textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="Опишите назначение этого playbook..."
                rows={4}
                className="w-full px-4 py-3 rounded-lg border text-sm resize-none transition-colors focus:border-accent outline-none"
                style={{
                  backgroundColor: 'var(--color-bg-secondary)',
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-primary)'
                }}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  Тип документа
                </label>
                <select
                  value={form.document_type}
                  onChange={(e) => setForm({ ...form, document_type: e.target.value })}
                  className="w-full px-4 py-2.5 rounded-lg border text-sm transition-colors focus:border-accent outline-none"
                  style={{
                    backgroundColor: 'var(--color-bg-secondary)',
                    borderColor: 'var(--color-border)',
                    color: 'var(--color-text-primary)'
                  }}
                >
                  <option value="contract">Контракт</option>
                  <option value="nda">NDA</option>
                  <option value="employment">Трудовой договор</option>
                  <option value="license">Лицензионное соглашение</option>
                  <option value="lease">Договор аренды</option>
                  <option value="loan">Кредитный договор</option>
                  <option value="msa">Master Service Agreement</option>
                  <option value="sow">Statement of Work</option>
                  <option value="court_document">Судебный документ</option>
                  <option value="other">Другое</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  Юрисдикция
                </label>
                <input
                  type="text"
                  value={form.jurisdiction}
                  onChange={(e) => setForm({ ...form, jurisdiction: e.target.value })}
                  placeholder="Россия, EU, USA..."
                  className="w-full px-4 py-2.5 rounded-lg border text-sm transition-colors focus:border-accent outline-none"
                  style={{
                    backgroundColor: 'var(--color-bg-secondary)',
                    borderColor: 'var(--color-border)',
                    color: 'var(--color-text-primary)'
                  }}
                />
              </div>
            </div>
          </div>
        ) : (
          /* Rules Section */
          <div className="p-6">
            {/* Rules toolbar */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <button
                  onClick={addBlankRule}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                  style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
                >
                  <Plus className="w-4 h-4" />
                  Добавить правило
                </button>
                <button
                  onClick={() => setShowTemplates(!showTemplates)}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors hover:bg-bg-hover"
                  style={{ 
                    backgroundColor: showTemplates ? 'var(--color-bg-hover)' : 'transparent',
                    color: 'var(--color-text-primary)',
                    border: `1px solid var(--color-border)`
                  }}
                >
                  <Sparkles className="w-4 h-4" />
                  Из шаблона
                </button>
              </div>

              {form.rules.length > 0 && (
                <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                  <Info className="w-4 h-4" />
                  Перетаскивайте правила для изменения приоритета
                </div>
              )}
            </div>

            {/* Templates dropdown */}
            {showTemplates && (
              <div
                className="mb-4 p-4 rounded-xl border"
                style={{
                  backgroundColor: 'var(--color-bg-secondary)',
                  borderColor: 'var(--color-border)'
                }}
              >
                <h4 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-primary)' }}>
                  Шаблоны правил
                </h4>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                  {ruleTemplates.map((template, idx) => (
                    <button
                      key={idx}
                      onClick={() => addRuleFromTemplate(template)}
                      className="flex items-center gap-2 p-3 rounded-lg text-left hover:bg-bg-hover transition-colors"
                      style={{ color: 'var(--color-text-primary)' }}
                    >
                      <RuleTypeBadge type={template.rule_type} />
                      <span className="text-sm truncate">{template.name}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Rules list */}
            <div className="space-y-3">
              {form.rules.map((rule, index) => (
                editingRuleIndex === index ? (
                  /* Edit mode */
                  <div
                    key={rule.id}
                    className="rounded-xl border p-5 space-y-4"
                    style={{
                      backgroundColor: 'var(--color-bg-secondary)',
                      borderColor: 'var(--color-accent)'
                    }}
                  >
                    {/* Row 1: rule name */}
                    <div>
                      <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>
                        Название правила
                      </label>
                      <input
                        type="text"
                        value={rule.rule_name}
                        onChange={(e) => updateRule(index, { rule_name: e.target.value })}
                        placeholder="Срок конфиденциальности"
                        autoFocus
                        className="w-full px-3 py-2 rounded-lg border text-sm"
                        style={{
                          backgroundColor: 'var(--color-bg-primary)',
                          borderColor: 'var(--color-border)',
                          color: 'var(--color-text-primary)'
                        }}
                      />
                    </div>

                    {/* Rule type */}
                    <div>
                      <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>
                        Тип правила
                      </label>
                      <div className="flex gap-2">
                        {(['red_line', 'fallback', 'no_go'] as const).map(type => (
                          <button
                            key={type}
                            type="button"
                            onClick={() => updateRule(index, { rule_type: type })}
                            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium border transition-colors"
                            style={{
                              borderColor: rule.rule_type === type
                                ? (type === 'red_line' ? '#ef4444' : type === 'no_go' ? '#dc2626' : '#eab308')
                                : 'var(--color-border)',
                              backgroundColor: rule.rule_type === type
                                ? (type === 'red_line' ? 'rgba(239,68,68,0.1)' : type === 'no_go' ? 'rgba(220,38,38,0.1)' : 'rgba(234,179,8,0.1)')
                                : 'var(--color-bg-primary)',
                              color: rule.rule_type === type
                                ? (type === 'red_line' ? '#ef4444' : type === 'no_go' ? '#dc2626' : '#eab308')
                                : 'var(--color-text-tertiary)',
                            }}
                          >
                            {type === 'red_line' ? 'Red Line' : type === 'no_go' ? 'No-Go' : 'Fallback'}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Standard position */}
                    <div>
                      <label className="block text-xs font-semibold mb-1.5" style={{ color: '#22c55e' }}>
                        ✅ Стандартная позиция
                        <span className="ml-1 font-normal" style={{ color: 'var(--color-text-tertiary)' }}>— идеальная формулировка</span>
                      </label>
                      <textarea
                        value={ruleHarveyFields[rule.id]?.standard_position || ''}
                        onChange={(e) => updateHarveyField(rule.id, 'standard_position', e.target.value)}
                        placeholder="Обязательства по конфиденциальности действуют в течение 3 лет с даты раскрытия информации"
                        rows={2}
                        className="w-full px-3 py-2 rounded-lg border text-sm resize-none"
                        style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                      />
                    </div>

                    {/* Fallback positions — multiple */}
                    <div>
                      <label className="block text-xs font-semibold mb-1.5" style={{ color: '#eab308' }}>
                        🟡 Запасные варианты
                        <span className="ml-1 font-normal" style={{ color: 'var(--color-text-tertiary)' }}>— допустимые альтернативы</span>
                      </label>
                      <div className="space-y-2">
                        {(ruleHarveyFields[rule.id]?.fallback_positions || ['']).map((pos, fbIdx) => (
                          <div key={fbIdx} className="flex gap-2 items-start">
                            <span className="text-xs font-semibold mt-2.5 w-4 shrink-0 text-center" style={{ color: '#eab308' }}>{fbIdx + 1}</span>
                            <textarea
                              value={pos}
                              onChange={(e) => updateHarveyArrayItem(rule.id, 'fallback_positions', fbIdx, e.target.value)}
                              placeholder="Допускается сокращение срока до 2 лет, если на этом настаивает контрагент"
                              rows={2}
                              className="flex-1 px-3 py-2 rounded-lg border text-sm resize-none"
                              style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                            />
                            {(ruleHarveyFields[rule.id]?.fallback_positions || ['']).length > 1 && (
                              <button
                                type="button"
                                onClick={() => removeHarveyArrayItem(rule.id, 'fallback_positions', fbIdx)}
                                className="mt-2 p-1.5 rounded-lg hover:bg-red-500/10 transition-colors"
                                style={{ color: '#9ca3af' }}
                              >
                                <X className="w-3.5 h-3.5" />
                              </button>
                            )}
                          </div>
                        ))}
                        <button
                          type="button"
                          onClick={() => addHarveyArrayItem(rule.id, 'fallback_positions')}
                          className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border transition-colors hover:bg-bg-hover"
                          style={{ borderColor: 'var(--color-border)', color: '#eab308', borderStyle: 'dashed' }}
                        >
                          <Plus className="w-3.5 h-3.5" />
                          Добавить запасной вариант
                        </button>
                      </div>
                    </div>

                    {/* Unacceptable deviations — multiple */}
                    <div>
                      <label className="block text-xs font-semibold mb-1.5" style={{ color: '#ef4444' }}>
                        ❌ Недопустимые отклонения
                        <span className="ml-1 font-normal" style={{ color: 'var(--color-text-tertiary)' }}>— что нельзя принимать</span>
                      </label>
                      <div className="space-y-2">
                        {(ruleHarveyFields[rule.id]?.unacceptable_deviations || []).map((dev, devIdx) => (
                          <div key={devIdx} className="flex gap-2 items-start">
                            <span className="text-xs font-bold mt-2.5 w-4 shrink-0 text-center" style={{ color: '#ef4444' }}>✕</span>
                            <textarea
                              value={dev}
                              onChange={(e) => updateHarveyArrayItem(rule.id, 'unacceptable_deviations', devIdx, e.target.value)}
                              placeholder="Бессрочный характер обязательств или срок менее 1 года"
                              rows={2}
                              className="flex-1 px-3 py-2 rounded-lg border text-sm resize-none"
                              style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                            />
                            <button
                              type="button"
                              onClick={() => removeHarveyArrayItem(rule.id, 'unacceptable_deviations', devIdx)}
                              className="mt-2 p-1.5 rounded-lg hover:bg-red-500/10 transition-colors"
                              style={{ color: '#9ca3af' }}
                            >
                              <X className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        ))}
                        <button
                          type="button"
                          onClick={() => addHarveyArrayItem(rule.id, 'unacceptable_deviations')}
                          className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border transition-colors hover:bg-bg-hover"
                          style={{ borderColor: 'var(--color-border)', color: '#ef4444', borderStyle: 'dashed' }}
                        >
                          <Plus className="w-3.5 h-3.5" />
                          Добавить недопустимое отклонение
                        </button>
                      </div>
                    </div>

                    {/* Internal guidance */}
                    <div>
                      <label className="block text-xs font-semibold mb-1.5" style={{ color: 'var(--color-accent)' }}>
                        📋 Внутренние инструкции
                        <span className="ml-1 font-normal" style={{ color: 'var(--color-text-tertiary)' }}>— советы для юриста</span>
                      </label>
                      <textarea
                        value={ruleHarveyFields[rule.id]?.internal_guidance || ''}
                        onChange={(e) => updateHarveyField(rule.id, 'internal_guidance', e.target.value)}
                        placeholder="Мы стремимся к 3-летнему сроку. Если контрагент требует менее 2 лет — необходимо согласование с руководителем юридического отдела"
                        rows={3}
                        className="w-full px-3 py-2 rounded-lg border text-sm resize-none"
                        style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                      />
                    </div>

                    {/* Mark missing as violation checkbox */}
                    <label className="flex items-start gap-3 cursor-pointer rounded-lg px-3 py-2.5 border transition-colors hover:bg-bg-hover"
                      style={{ borderColor: 'var(--color-border)' }}
                    >
                      <input
                        type="checkbox"
                        checked={ruleHarveyFields[rule.id]?.mark_missing_as_violation ?? false}
                        onChange={(e) => updateHarveyField(rule.id, 'mark_missing_as_violation', e.target.checked)}
                        className="mt-0.5 w-4 h-4 rounded accent-red-500 shrink-0"
                      />
                      <div>
                        <div className="text-xs font-medium" style={{ color: 'var(--color-text-primary)' }}>
                          Если оговорки нет в документе — отметить как Неприемлемо
                        </div>
                        <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                          Отсутствие этого пункта будет считаться нарушением
                        </div>
                      </div>
                    </label>

                    <div className="flex items-center justify-between pt-1">
                      <button
                        onClick={() => removeRule(index)}
                        className="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors hover:bg-red-500/10"
                        style={{ color: '#ef4444' }}
                      >
                        Удалить
                      </button>
                      <button
                        onClick={() => setEditingRuleIndex(null)}
                        className="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                        style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
                      >
                        Готово
                      </button>
                    </div>
                  </div>
                ) : (
                  /* View mode - draggable card */
                  <DraggableRuleCard
                    key={rule.id}
                    rule={rule}
                    index={index}
                    isExpanded={expandedRules.has(index)}
                    onToggleExpand={() => toggleRuleExpand(index)}
                    onEdit={() => setEditingRuleIndex(index)}
                    onDelete={() => removeRule(index)}
                    onDragStart={handleDragStart}
                    onDragOver={handleDragOver}
                    onDrop={handleDrop}
                    isDragging={draggedIndex === index}
                    harveyFields={ruleHarveyFields[rule.id]}
                  />
                )
              ))}

              {form.rules.length === 0 && (
                <div className="text-center py-16 rounded-xl border-2 border-dashed" style={{ borderColor: 'var(--color-border)' }}>
                  <Target className="w-16 h-16 mx-auto mb-4" style={{ color: 'var(--color-text-tertiary)' }} />
                  <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--color-text-primary)' }}>
                    Нет правил
                  </h3>
                  <p className="text-sm mb-4" style={{ color: 'var(--color-text-secondary)' }}>
                    Добавьте правила для проверки документов
                  </p>
                  <div className="flex items-center justify-center gap-3">
                    <button
                      onClick={addBlankRule}
                      className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium"
                      style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
                    >
                      <Plus className="w-4 h-4" />
                      Создать правило
                    </button>
                    <button
                      onClick={() => setShowTemplates(true)}
                      className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border"
                      style={{ 
                        borderColor: 'var(--color-border)',
                        color: 'var(--color-text-primary)'
                      }}
                    >
                      <Sparkles className="w-4 h-4" />
                      Из шаблона
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ==================== MAIN PAGE ====================
export default function PlaybooksPage() {
  const { caseId } = useParams<{ caseId: string }>()

  const [playbooks, setPlaybooks] = useState<Playbook[]>([])
  const [checks, setChecks] = useState<PlaybookCheck[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'playbooks' | 'history'>('playbooks')
  const [searchQuery, setSearchQuery] = useState('')
  const [editingPlaybook, setEditingPlaybook] = useState<Partial<Playbook> | null>(null)
  const [isNewPlaybook, setIsNewPlaybook] = useState(false)
  const [filterType, setFilterType] = useState<string>('all')

  // Navigation
  const navItems = [
    { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
    { id: 'documents', label: 'Документы', icon: FileText, path: `/cases/${caseId}/documents` },
    { id: 'editor', label: 'Редактор', icon: FileEdit, path: `/cases/${caseId}/editor` },
    { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
    { id: 'playbooks', label: 'Playbooks', icon: BookOpen, path: `/cases/${caseId}/playbooks` },
    { id: 'workflows', label: 'Workflows', icon: Workflow, path: `/cases/${caseId}/workflows` },
  ]

  // Load data
  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true)

        const [playbooksData, checksData] = await Promise.all([
          playbooksApi.getPlaybooks(),
          playbooksApi.getChecks({ case_id: caseId, limit: 50 })
        ])

        setPlaybooks(playbooksData)
        setChecks(checksData)
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

  // Save playbook
  const handleSavePlaybook = async (data: Partial<Playbook>) => {
    try {
      if (isNewPlaybook) {
        await playbooksApi.createPlaybook({
          name: data.name!,
          display_name: data.display_name!,
          description: data.description,
          document_type: data.document_type || 'contract',
          jurisdiction: data.jurisdiction,
          is_public: data.is_public,
          rules: data.rules?.map(r => ({
            rule_type: r.rule_type,
            clause_category: r.clause_category,
            rule_name: r.rule_name,
            description: r.description,
            condition_type: r.condition_type,
            condition_config: r.condition_config,
            priority: r.priority,
            severity: r.severity,
            is_active: r.is_active
          }))
        })
        toast.success('Playbook создан успешно!')
      } else {
        // Use updatePlaybookWithRules to properly sync rules
        await playbooksApi.updatePlaybookWithRules(editingPlaybook!.id!, data)
        toast.success('Playbook сохранён')
      }

      const updated = await playbooksApi.getPlaybooks()
      setPlaybooks(updated)
      setEditingPlaybook(null)
      setIsNewPlaybook(false)
    } catch (error: any) {
      console.error('Save error:', error)
      toast.error('Ошибка сохранения: ' + (error.message || 'Неизвестная ошибка'))
    }
  }

  // Duplicate playbook
  const handleDuplicate = async (playbook: Playbook) => {
    try {
      await playbooksApi.duplicatePlaybook(playbook.id)
      toast.success('Playbook скопирован')
      const updated = await playbooksApi.getPlaybooks()
      setPlaybooks(updated)
    } catch (error) {
      toast.error('Ошибка копирования')
    }
  }

  // Delete playbook
  const handleDelete = async (playbook: Playbook) => {
    if (!confirm(`Удалить "${playbook.display_name}"?`)) return

    try {
      await playbooksApi.deletePlaybook(playbook.id)
      toast.success('Playbook удалён')
      setPlaybooks(prev => prev.filter(p => p.id !== playbook.id))
    } catch (error) {
      toast.error('Ошибка удаления')
    }
  }

  // Filter playbooks
  const filteredPlaybooks = playbooks.filter(p => {
    const matchesSearch = p.display_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      p.description?.toLowerCase().includes(searchQuery.toLowerCase())
    const matchesType = filterType === 'all' || p.document_type === filterType
    return matchesSearch && matchesType
  })

  // Get unique document types
  const documentTypes = [...new Set(playbooks.map(p => p.document_type).filter(Boolean))]

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

  // Editor view
  if (editingPlaybook) {
    return (
      <div className="flex h-screen" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
        <UnifiedSidebar navItems={navItems} title="Legal AI" />
        <div className="flex-1 overflow-hidden">
          <PlaybookEditor
            playbook={editingPlaybook}
            onSave={handleSavePlaybook}
            onCancel={() => {
              setEditingPlaybook(null)
              setIsNewPlaybook(false)
            }}
            isNew={isNewPlaybook}
          />
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
          className="flex items-center justify-between px-6 py-5 border-b"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div>
            <h1 className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>
              Playbooks
            </h1>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              Наборы правил для автоматической проверки документов
            </p>
          </div>

          <button
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-colors hover:opacity-90"
            style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
            onClick={() => {
              setEditingPlaybook({
                name: '',
                display_name: '',
                description: '',
                document_type: 'contract',
                rules: []
              })
              setIsNewPlaybook(true)
            }}
          >
            <Plus className="w-4 h-4" />
            Создать Playbook
          </button>
        </header>

        {/* Info Banner */}
        <div
          className="mx-6 mt-4 p-4 rounded-xl flex items-start gap-3"
          style={{ backgroundColor: 'rgba(99, 102, 241, 0.08)' }}
        >
          <BookOpen className="w-5 h-5 shrink-0 mt-0.5" style={{ color: 'var(--color-accent)' }} />
          <div>
            <p className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
              💡 Как использовать Playbooks
            </p>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              Создайте playbook с правилами проверки. Затем на странице <strong>Документы</strong> нажмите "Проверить Playbook" 
              на любом документе для автоматического анализа на соответствие вашим требованиям.
            </p>
          </div>
        </div>

        {/* Tabs */}
        <div
          className="flex items-center gap-6 px-6 py-3 border-b"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <button
            onClick={() => setActiveTab('playbooks')}
            className={`text-sm font-medium pb-2 border-b-2 transition-colors`}
            style={{
              color: activeTab === 'playbooks' ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
              borderColor: activeTab === 'playbooks' ? 'var(--color-accent)' : 'transparent'
            }}
          >
            Мои Playbooks ({playbooks.length})
          </button>
          <button
            onClick={() => setActiveTab('history')}
            className={`text-sm font-medium pb-2 border-b-2 transition-colors`}
            style={{
              color: activeTab === 'history' ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
              borderColor: activeTab === 'history' ? 'var(--color-accent)' : 'transparent'
            }}
          >
            История проверок ({checks.length})
          </button>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-4 px-6 py-4">
          <div className="relative flex-1 max-w-md">
            <Search
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4"
              style={{ color: 'var(--color-text-tertiary)' }}
            />
            <input
              type="text"
              placeholder="Поиск playbooks..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 rounded-lg border text-sm transition-colors focus:border-accent outline-none"
              style={{
                backgroundColor: 'var(--color-bg-secondary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)'
              }}
            />
          </div>

          {documentTypes.length > 0 && (
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              className="px-4 py-2.5 rounded-lg border text-sm transition-colors outline-none"
              style={{
                backgroundColor: 'var(--color-bg-secondary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)'
              }}
            >
              <option value="all">Все типы</option>
              {documentTypes.map(type => (
                <option key={type} value={type}>{type}</option>
              ))}
            </select>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 pb-6">
          {activeTab === 'playbooks' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredPlaybooks.map(playbook => (
                <PlaybookCard
                  key={playbook.id}
                  playbook={playbook}
                  onEdit={() => setEditingPlaybook(playbook)}
                  onDuplicate={() => handleDuplicate(playbook)}
                  onDelete={() => handleDelete(playbook)}
                  onPreview={() => {
                    // TODO: Implement preview
                    toast.info('Предпросмотр в разработке')
                  }}
                />
              ))}

              {filteredPlaybooks.length === 0 && (
                <div className="col-span-full text-center py-16">
                  <BookOpen
                    className="w-16 h-16 mx-auto mb-4"
                    style={{ color: 'var(--color-text-tertiary)' }}
                  />
                  <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--color-text-primary)' }}>
                    {searchQuery ? 'Ничего не найдено' : 'Нет playbooks'}
                  </h3>
                  <p className="text-sm mb-4" style={{ color: 'var(--color-text-secondary)' }}>
                    {searchQuery ? 'Попробуйте изменить поисковый запрос' : 'Создайте первый playbook для проверки документов'}
                  </p>
                  {!searchQuery && (
                    <button
                      onClick={() => {
                        setEditingPlaybook({
                          name: '',
                          display_name: '',
                          description: '',
                          document_type: 'contract',
                          rules: []
                        })
                        setIsNewPlaybook(true)
                      }}
                      className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium"
                      style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
                    >
                      <Plus className="w-4 h-4" />
                      Создать Playbook
                    </button>
                  )}
                </div>
              )}
            </div>
          ) : (
            /* History tab */
            <div className="space-y-3">
              {checks.map(check => (
                <div
                  key={check.id}
                  className="flex items-center justify-between p-4 rounded-xl border transition-colors hover:border-accent/30"
                  style={{
                    backgroundColor: 'var(--color-bg-secondary)',
                    borderColor: 'var(--color-border)'
                  }}
                >
                  <div className="flex items-center gap-4">
                    {check.overall_status === 'compliant' && <CheckCircle className="w-6 h-6" style={{ color: '#22c55e' }} />}
                    {check.overall_status === 'non_compliant' && <XCircle className="w-6 h-6" style={{ color: '#ef4444' }} />}
                    {check.overall_status === 'needs_review' && <AlertTriangle className="w-6 h-6" style={{ color: '#eab308' }} />}
                    {!check.overall_status && <FileText className="w-6 h-6" style={{ color: 'var(--color-text-tertiary)' }} />}
                    <div>
                      <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                        {check.document_name || 'Документ'}
                      </div>
                      <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                        {new Date(check.created_at).toLocaleString('ru-RU')}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-6">
                    <div className="text-right">
                      <div className="text-lg font-bold" style={{ 
                        color: (check.compliance_score || 0) >= 80 ? '#22c55e' : 
                               (check.compliance_score || 0) >= 50 ? '#eab308' : '#ef4444'
                      }}>
                        {check.compliance_score?.toFixed(0) || 0}%
                      </div>
                      <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                        соответствие
                      </div>
                    </div>
                    <button
                      className="p-2 rounded-lg hover:bg-bg-hover transition-colors"
                      style={{ color: 'var(--color-text-secondary)' }}
                    >
                      <Eye className="w-5 h-5" />
                    </button>
                  </div>
                </div>
              ))}

              {checks.length === 0 && (
                <div className="text-center py-16">
                  <CheckCircle
                    className="w-16 h-16 mx-auto mb-4"
                    style={{ color: 'var(--color-text-tertiary)' }}
                  />
                  <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--color-text-primary)' }}>
                    История проверок пуста
                  </h3>
                  <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                    Проверки документов появятся здесь после запуска
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
