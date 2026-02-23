/**
 * Playbooks Management Page
 */
import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import {
  BookOpen,
  Plus,
  Search,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Trash2,
  FileText,
  Loader2,
  Save,
  ArrowLeft,
  MessageSquare,
  Table,
  FileEdit,
  Workflow,
  X,
  MoreVertical,
  Copy,
  Edit,
} from 'lucide-react'
import { toast } from 'sonner'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import * as playbooksApi from '../services/playbooksApi'
import type { Playbook, PlaybookRule, PlaybookCheck } from '../services/playbooksApi'

// ── Color palette (B&W only) ───────────────────────────────────────────────────
const C = {
  border:   '#e5e7eb',
  bg:       '#f9fafb',
  bgHover:  '#f3f4f6',
  heading:  '#111827',
  body:     '#374151',
  label:    '#6b7280',
  subtle:   '#9ca3af',
  btnBg:    '#111827',
  btnText:  'white',
}

// ── Harvey Fields ─────────────────────────────────────────────────────────────
interface HarveyFields {
  standard_position: string
  fallback_positions: string[]
  unacceptable_deviations: string[]
  internal_guidance: string
  mark_missing_as_violation: boolean
}

const EMPTY_HARVEY: HarveyFields = {
  standard_position: '',
  fallback_positions: [''],
  unacceptable_deviations: [],
  internal_guidance: '',
  mark_missing_as_violation: false,
}

const parseHarvey = (
  description?: string,
  suggested_clause_template?: string,
  fallback_options?: any
): HarveyFields => {
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

  const desc = description || ''
  const hasLegacyFormat =
    desc.includes('СТАНДАРТ:') || desc.includes('ЗАПАСНОЙ ВАРИАНТ:') ||
    desc.includes('НЕДОПУСТИМО:') || desc.includes('ИНСТРУКЦИИ:')

  if (!hasLegacyFormat) {
    return { ...EMPTY_HARVEY, standard_position: suggested_clause_template || '', internal_guidance: desc }
  }

  const sections: Record<string, string> = {}
  for (const part of desc.split('\n\n')) {
    const idx = part.indexOf(':')
    if (idx > 0) sections[part.substring(0, idx).trim()] = part.substring(idx + 1).trim()
  }
  return {
    standard_position: sections['СТАНДАРТ'] || suggested_clause_template || '',
    fallback_positions: sections['ЗАПАСНОЙ ВАРИАНТ'] ? [sections['ЗАПАСНОЙ ВАРИАНТ']] : [''],
    unacceptable_deviations: sections['НЕДОПУСТИМО'] ? [sections['НЕДОПУСТИМО']] : [],
    internal_guidance: sections['ИНСТРУКЦИИ'] || '',
    mark_missing_as_violation: false,
  }
}

// ── RuleAccordion ─────────────────────────────────────────────────────────────
interface RuleAccordionProps {
  rule: PlaybookRule
  index?: number
  isExpanded: boolean
  onToggle: () => void
  onDelete: () => void
  harvey: HarveyFields
  onUpdateRule: (updates: Partial<PlaybookRule>) => void
  onUpdateHarvey: (field: keyof HarveyFields, value: any) => void
  onAddItem: (field: 'fallback_positions' | 'unacceptable_deviations') => void
  onRemoveItem: (field: 'fallback_positions' | 'unacceptable_deviations', i: number) => void
  onUpdateItem: (field: 'fallback_positions' | 'unacceptable_deviations', i: number, v: string) => void
}


const inputCls = [
  'w-full px-3 py-2 rounded border text-sm resize-none',
  'focus:outline-none focus:ring-1 focus:ring-gray-400',
].join(' ')

const inputStyle = { borderColor: C.border, color: C.body, backgroundColor: C.bg }

function RuleAccordion({
  rule, isExpanded, onToggle, onDelete,
  harvey, onUpdateRule, onUpdateHarvey, onAddItem, onRemoveItem, onUpdateItem,
}: RuleAccordionProps) {
  return (
    <div style={{ borderBottom: `1px solid ${C.border}` }}>
      {/* Header row */}
      <button
        className="w-full flex items-center justify-between py-4 px-5 text-left transition-colors"
        style={{ backgroundColor: isExpanded ? C.bgHover : 'white' }}
        onMouseEnter={e => { if (!isExpanded) (e.currentTarget as HTMLElement).style.backgroundColor = C.bgHover }}
        onMouseLeave={e => { if (!isExpanded) (e.currentTarget as HTMLElement).style.backgroundColor = 'white' }}
        onClick={onToggle}
      >
        <span className="text-sm font-medium truncate" style={{ color: C.heading }}>
          {rule.rule_name || 'Без названия'}
        </span>
        {isExpanded
          ? <ChevronUp className="w-4 h-4 shrink-0" style={{ color: C.subtle }} />
          : <ChevronDown className="w-4 h-4 shrink-0" style={{ color: C.subtle }} />}
      </button>

      {/* Expanded body */}
      {isExpanded && (
        <div className="px-5 pb-6 space-y-5" style={{ backgroundColor: 'white' }}>
          {/* Rule name */}
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: C.label }}>Название</label>
            <input
              type="text"
              value={rule.rule_name}
              onChange={e => onUpdateRule({ rule_name: e.target.value })}
              placeholder="Название правила"
              className="w-full px-3 py-2 rounded border text-sm focus:outline-none focus:ring-1 focus:ring-gray-400"
              style={inputStyle}
              autoFocus
            />
          </div>

          {/* Standard position */}
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: C.label }}>
              Стандартная позиция
            </label>
            <textarea
              value={harvey.standard_position}
              onChange={e => onUpdateHarvey('standard_position', e.target.value)}
              placeholder="Идеальная формулировка условия..."
              rows={3}
              className={inputCls}
              style={inputStyle}
            />
          </div>

          {/* Fallback positions */}
          <div>
            <label className="block text-xs font-medium mb-2" style={{ color: C.label }}>
              Запасные варианты
            </label>
            <div className="space-y-2">
              {harvey.fallback_positions.map((pos, i) => (
                <div key={i} className="flex gap-2 items-start">
                  <textarea
                    value={pos}
                    onChange={e => onUpdateItem('fallback_positions', i, e.target.value)}
                    placeholder="Допустимая альтернатива..."
                    rows={2}
                    className={inputCls + ' flex-1'}
                    style={inputStyle}
                  />
                  {harvey.fallback_positions.length > 1 && (
                    <button
                      type="button"
                      onClick={() => onRemoveItem('fallback_positions', i)}
                      className="mt-1 p-1.5 rounded transition-colors"
                      style={{ color: C.subtle }}
                      onMouseEnter={e => (e.currentTarget as HTMLElement).style.backgroundColor = C.bgHover}
                      onMouseLeave={e => (e.currentTarget as HTMLElement).style.backgroundColor = 'transparent'}
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={() => onAddItem('fallback_positions')}
              className="mt-2 text-xs flex items-center gap-1"
              style={{ color: C.label }}
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.textDecoration = 'underline'}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.textDecoration = 'none'}
            >
              <Plus className="w-3 h-3" />
              Добавить запасной вариант
            </button>
          </div>

          {/* Unacceptable deviations */}
          <div>
            <label className="block text-xs font-medium mb-2" style={{ color: C.label }}>
              Недопустимые отклонения
            </label>
            <div className="space-y-2">
              {harvey.unacceptable_deviations.map((dev, i) => (
                <div key={i} className="flex gap-2 items-start">
                  <textarea
                    value={dev}
                    onChange={e => onUpdateItem('unacceptable_deviations', i, e.target.value)}
                    placeholder="Неприемлемое условие..."
                    rows={2}
                    className={inputCls + ' flex-1'}
                    style={inputStyle}
                  />
                  <button
                    type="button"
                    onClick={() => onRemoveItem('unacceptable_deviations', i)}
                    className="mt-1 p-1.5 rounded transition-colors"
                    style={{ color: C.subtle }}
                    onMouseEnter={e => (e.currentTarget as HTMLElement).style.backgroundColor = C.bgHover}
                    onMouseLeave={e => (e.currentTarget as HTMLElement).style.backgroundColor = 'transparent'}
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={() => onAddItem('unacceptable_deviations')}
              className="mt-2 text-xs flex items-center gap-1"
              style={{ color: C.label }}
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.textDecoration = 'underline'}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.textDecoration = 'none'}
            >
              <Plus className="w-3 h-3" />
              Добавить недопустимое отклонение
            </button>
          </div>

          {/* Guidance */}
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: C.label }}>Руководство</label>
            <textarea
              value={harvey.internal_guidance}
              onChange={e => onUpdateHarvey('internal_guidance', e.target.value)}
              placeholder="Инструкции и рекомендации для юриста..."
              rows={3}
              className={inputCls}
              style={inputStyle}
            />
          </div>

          {/* Required clause */}
          <label
            className="flex items-start gap-3 cursor-pointer p-3 rounded border transition-colors"
            style={{ borderColor: C.border }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.backgroundColor = C.bgHover}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.backgroundColor = 'transparent'}
          >
            <input
              type="checkbox"
              checked={harvey.mark_missing_as_violation}
              onChange={e => onUpdateHarvey('mark_missing_as_violation', e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded"
            />
            <div>
              <div className="text-sm font-medium" style={{ color: C.heading }}>Обязательный пункт</div>
              <div className="text-xs mt-0.5" style={{ color: C.label }}>
                Если для этого правила отсутствует пункт, отметьте правило как неприемлемое
              </div>
            </div>
          </label>

          {/* Delete */}
          <div className="flex justify-end pt-1">
            <button
              type="button"
              onClick={onDelete}
              className="text-xs flex items-center gap-1.5 px-3 py-1.5 rounded transition-colors"
              style={{ color: C.label }}
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.backgroundColor = C.bgHover}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.backgroundColor = 'transparent'}
            >
              <Trash2 className="w-3.5 h-3.5" />
              Удалить правило
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── PlaybookEditor ─────────────────────────────────────────────────────────────
function PlaybookEditor({
  playbook, onSave, onCancel,
}: {
  playbook: Partial<Playbook>
  onSave: (data: Partial<Playbook>) => void
  onCancel: () => void
}) {
  const [form, setForm] = useState({
    name: playbook.name || '',
    display_name: playbook.display_name || '',
    document_type: playbook.document_type || 'contract',
    jurisdiction: playbook.jurisdiction || '',
    rules: (playbook.rules || []) as PlaybookRule[],
  })

  const [expandedRules, setExpandedRules] = useState<Set<number>>(new Set())

  const [harveyMap, setHarveyMap] = useState<Record<string, HarveyFields>>(() => {
    const map: Record<string, HarveyFields> = {}
    playbook.rules?.forEach(r => {
      map[r.id] = parseHarvey(r.description, r.suggested_clause_template, r.fallback_options)
    })
    return map
  })

  const toggleExpand = (i: number) => {
    setExpandedRules(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }

  const addRule = () => {
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
      created_at: new Date().toISOString(),
    }
    setHarveyMap(prev => ({ ...prev, [newRule.id]: { ...EMPTY_HARVEY } }))
    const newIdx = form.rules.length
    setForm(prev => ({ ...prev, rules: [...prev.rules, newRule] }))
    setExpandedRules(prev => new Set(prev).add(newIdx))
  }

  const updateRule = (index: number, updates: Partial<PlaybookRule>) => {
    setForm(prev => ({
      ...prev,
      rules: prev.rules.map((r, i) => i === index ? { ...r, ...updates } : r),
    }))
  }

  const removeRule = (index: number) => {
    setForm(prev => ({ ...prev, rules: prev.rules.filter((_, i) => i !== index) }))
    setExpandedRules(prev => {
      const next = new Set<number>()
      prev.forEach(i => { if (i < index) next.add(i); else if (i > index) next.add(i - 1) })
      return next
    })
  }

  const updateHarvey = (ruleId: string, field: keyof HarveyFields, value: any) => {
    setHarveyMap(prev => ({ ...prev, [ruleId]: { ...prev[ruleId] ?? EMPTY_HARVEY, [field]: value } }))
  }

  const addItem = (ruleId: string, field: 'fallback_positions' | 'unacceptable_deviations') => {
    setHarveyMap(prev => {
      const cur = prev[ruleId] ?? EMPTY_HARVEY
      return { ...prev, [ruleId]: { ...cur, [field]: [...cur[field], ''] } }
    })
  }

  const removeItem = (ruleId: string, field: 'fallback_positions' | 'unacceptable_deviations', idx: number) => {
    setHarveyMap(prev => {
      const cur = prev[ruleId] ?? EMPTY_HARVEY
      const arr = cur[field].filter((_, i) => i !== idx)
      return { ...prev, [ruleId]: { ...cur, [field]: arr.length > 0 ? arr : field === 'fallback_positions' ? [''] : [] } }
    })
  }

  const updateItem = (ruleId: string, field: 'fallback_positions' | 'unacceptable_deviations', idx: number, v: string) => {
    setHarveyMap(prev => {
      const cur = prev[ruleId] ?? EMPTY_HARVEY
      const arr = [...cur[field]]
      arr[idx] = v
      return { ...prev, [ruleId]: { ...cur, [field]: arr } }
    })
  }

  const handleSave = () => {
    if (!form.display_name.trim()) { toast.error('Укажите название'); return }

    const name = form.name.trim() ||
      form.display_name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '').slice(0, 40) ||
      `playbook_${Date.now()}`

    const normalizedRules = form.rules.map(r => {
      const h = harveyMap[r.id] ?? EMPTY_HARVEY
      return {
        ...r,
        description: h.internal_guidance || r.description,
        suggested_clause_template: h.standard_position || r.suggested_clause_template,
        fallback_options: {
          standard_position: h.standard_position,
          fallbacks: h.fallback_positions.filter(Boolean),
          unacceptable: h.unacceptable_deviations.filter(Boolean),
          guidance: h.internal_guidance,
          mark_missing: h.mark_missing_as_violation,
        },
        clause_category: r.clause_category ||
          r.rule_name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '').slice(0, 40) || 'general',
      }
    })

    onSave({ ...form, name, rules: normalizedRules })
  }

  return (
    <div className="h-full flex flex-col" style={{ backgroundColor: 'white' }}>
      {/* Header */}
      <div
        className="flex items-center gap-3 px-6 py-4 border-b shrink-0"
        style={{ borderColor: C.border }}
      >
        <button
          onClick={onCancel}
          className="p-2 rounded transition-colors"
          style={{ color: C.label }}
          onMouseEnter={e => (e.currentTarget as HTMLElement).style.backgroundColor = C.bgHover}
          onMouseLeave={e => (e.currentTarget as HTMLElement).style.backgroundColor = 'transparent'}
        >
          <ArrowLeft className="w-4 h-4" />
        </button>

        <input
          type="text"
          value={form.display_name}
          onChange={e => setForm(f => ({
            ...f,
            display_name: e.target.value,
            name: f.name || e.target.value.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '').slice(0, 40),
          }))}
          placeholder="Название playbook"
          className="flex-1 text-base font-semibold border-0 focus:outline-none bg-transparent"
          style={{ color: C.heading }}
        />

        <select
          value={form.document_type}
          onChange={e => setForm(f => ({ ...f, document_type: e.target.value }))}
          className="px-3 py-1.5 rounded border text-sm focus:outline-none"
          style={{ borderColor: C.border, color: C.label, backgroundColor: C.bg }}
        >
          <option value="contract">Контракт</option>
          <option value="nda">NDA</option>
          <option value="employment">Трудовой договор</option>
          <option value="license">Лицензионное соглашение</option>
          <option value="lease">Аренда</option>
          <option value="loan">Кредит</option>
          <option value="msa">MSA</option>
          <option value="sow">SOW</option>
          <option value="other">Другое</option>
        </select>

        <button
          onClick={handleSave}
          className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium transition-opacity hover:opacity-80"
          style={{ backgroundColor: C.btnBg, color: C.btnText }}
        >
          <Save className="w-4 h-4" />
          Сохранить
        </button>
      </div>

      {/* Rules area */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto">
        {/* Rules toolbar */}
        <div
          className="flex items-center justify-between px-6 py-3 border-b"
          style={{ borderColor: C.border }}
        >
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium" style={{ color: C.heading }}>
              Правила{form.rules.length > 0 ? ` (${form.rules.length})` : ''}
            </span>
            {expandedRules.size > 0 && (
              <button
                onClick={() => setExpandedRules(new Set())}
                className="text-xs"
                style={{ color: C.label }}
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.textDecoration = 'underline'}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.textDecoration = 'none'}
              >
                Свернуть все
              </button>
            )}
          </div>
          <button
            onClick={addRule}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-opacity hover:opacity-80"
            style={{ backgroundColor: C.btnBg, color: C.btnText }}
          >
            <Plus className="w-3.5 h-3.5" />
            Добавить правило
          </button>
        </div>

        {/* Empty state */}
        {form.rules.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 px-6 text-center">
            <div
              className="w-12 h-12 rounded-full flex items-center justify-center mb-4"
              style={{ backgroundColor: C.bg }}
            >
              <Plus className="w-5 h-5" style={{ color: C.subtle }} />
            </div>
            <p className="text-sm font-medium mb-1" style={{ color: C.heading }}>Нет правил</p>
            <p className="text-xs mb-5" style={{ color: C.label }}>Добавьте правила для проверки документов</p>
            <button
              onClick={addRule}
              className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium transition-opacity hover:opacity-80"
              style={{ backgroundColor: C.btnBg, color: C.btnText }}
            >
              <Plus className="w-4 h-4" />
              Добавить правило
            </button>
          </div>
        ) : (
          <>
            {form.rules.map((rule, index) => (
              <RuleAccordion
                key={rule.id}
                rule={rule}
                index={index}
                isExpanded={expandedRules.has(index)}
                onToggle={() => toggleExpand(index)}
                onDelete={() => removeRule(index)}
                harvey={harveyMap[rule.id] ?? EMPTY_HARVEY}
                onUpdateRule={updates => updateRule(index, updates)}
                onUpdateHarvey={(field, value) => updateHarvey(rule.id, field, value)}
                onAddItem={field => addItem(rule.id, field)}
                onRemoveItem={(field, i) => removeItem(rule.id, field, i)}
                onUpdateItem={(field, i, v) => updateItem(rule.id, field, i, v)}
              />
            ))}
            <div className="px-5 py-4">
              <button
                onClick={addRule}
                className="text-xs flex items-center gap-1.5"
                style={{ color: C.label }}
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.textDecoration = 'underline'}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.textDecoration = 'none'}
              >
                <Plus className="w-3.5 h-3.5" />
                Добавить правило
              </button>
            </div>
          </>
        )}
        </div>{/* /max-w-2xl */}
      </div>
    </div>
  )
}

// ── PlaybookCard ───────────────────────────────────────────────────────────────
function PlaybookCard({
  playbook, onEdit, onDuplicate, onDelete,
}: {
  playbook: Playbook
  onEdit: () => void
  onDuplicate: () => void
  onDelete: () => void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const total = playbook.rules?.length ?? 0

  return (
    <div
      className="group relative rounded-lg border p-5 cursor-pointer transition-colors"
      style={{ backgroundColor: 'white', borderColor: C.border }}
      onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = C.label}
      onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = C.border}
      onClick={onEdit}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="min-w-0">
          <h3 className="font-medium text-sm truncate" style={{ color: C.heading }}>
            {playbook.display_name}
          </h3>
          {playbook.document_type && (
            <span className="text-xs mt-0.5 block" style={{ color: C.subtle }}>
              {playbook.document_type}
            </span>
          )}
        </div>

        <div className="relative shrink-0 ml-2" onClick={e => e.stopPropagation()}>
          <button
            className="p-1.5 rounded opacity-0 group-hover:opacity-100 transition-all"
            style={{ color: C.label }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.backgroundColor = C.bgHover}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.backgroundColor = 'transparent'}
            onClick={() => setMenuOpen(!menuOpen)}
          >
            <MoreVertical className="w-4 h-4" />
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
              <div
                className="absolute right-0 top-8 w-40 rounded-lg border shadow-lg py-1 z-20"
                style={{ backgroundColor: 'white', borderColor: C.border }}
              >
                <button
                  className="w-full px-3 py-2 text-left text-sm flex items-center gap-2 transition-colors"
                  style={{ color: C.body }}
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.backgroundColor = C.bgHover}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.backgroundColor = 'transparent'}
                  onClick={() => { onEdit(); setMenuOpen(false) }}
                >
                  <Edit className="w-3.5 h-3.5" />
                  Редактировать
                </button>
                <button
                  className="w-full px-3 py-2 text-left text-sm flex items-center gap-2 transition-colors"
                  style={{ color: C.body }}
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.backgroundColor = C.bgHover}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.backgroundColor = 'transparent'}
                  onClick={() => { onDuplicate(); setMenuOpen(false) }}
                >
                  <Copy className="w-3.5 h-3.5" />
                  Дублировать
                </button>
                {!playbook.is_system && (
                  <>
                    <div className="my-1 border-t" style={{ borderColor: C.border }} />
                    <button
                      className="w-full px-3 py-2 text-left text-sm flex items-center gap-2 transition-colors"
                      style={{ color: '#6b7280' }}
                      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = C.bgHover; (e.currentTarget as HTMLElement).style.color = '#111827' }}
                      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = 'transparent'; (e.currentTarget as HTMLElement).style.color = '#6b7280' }}
                      onClick={() => { onDelete(); setMenuOpen(false) }}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      Удалить
                    </button>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 text-xs" style={{ color: C.subtle }}>
        <span>{total} правил</span>
        {playbook.usage_count ? <span>· {playbook.usage_count} проверок</span> : null}
        {playbook.is_system && <span>· Системный</span>}
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function PlaybooksPage() {
  const { caseId } = useParams<{ caseId: string }>()

  const [playbooks, setPlaybooks] = useState<Playbook[]>([])
  const [checks, setChecks] = useState<PlaybookCheck[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'playbooks' | 'history'>('playbooks')
  const [searchQuery, setSearchQuery] = useState('')
  const [editingPlaybook, setEditingPlaybook] = useState<Partial<Playbook> | null>(null)
  const [isNewPlaybook, setIsNewPlaybook] = useState(false)

  const navItems = [
    { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
    { id: 'documents', label: 'Документы', icon: FileText, path: `/cases/${caseId}/documents` },
    { id: 'editor', label: 'Редактор', icon: FileEdit, path: `/cases/${caseId}/editor` },
    { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
    { id: 'playbooks', label: 'Playbooks', icon: BookOpen, path: `/cases/${caseId}/playbooks` },
    { id: 'workflows', label: 'Workflows', icon: Workflow, path: `/cases/${caseId}/workflows` },
  ]

  useEffect(() => {
    if (!caseId) return
    const load = async () => {
      try {
        setLoading(true)
        const [pb, ch] = await Promise.all([
          playbooksApi.getPlaybooks(),
          playbooksApi.getChecks({ case_id: caseId, limit: 50 }),
        ])
        setPlaybooks(pb)
        setChecks(ch)
      } catch {
        toast.error('Ошибка загрузки данных')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [caseId])

  const handleSave = async (data: Partial<Playbook>) => {
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
            is_active: r.is_active,
            suggested_clause_template: r.suggested_clause_template,
            fallback_options: r.fallback_options,
          })),
        })
        toast.success('Playbook создан')
      } else {
        await playbooksApi.updatePlaybookWithRules(editingPlaybook!.id!, data)
        toast.success('Playbook сохранён')
      }
      setPlaybooks(await playbooksApi.getPlaybooks())
      setEditingPlaybook(null)
      setIsNewPlaybook(false)
    } catch (e: any) {
      toast.error('Ошибка сохранения: ' + (e.message ?? 'Неизвестная ошибка'))
    }
  }

  const handleDuplicate = async (p: Playbook) => {
    try {
      await playbooksApi.duplicatePlaybook(p.id)
      toast.success('Скопировано')
      setPlaybooks(await playbooksApi.getPlaybooks())
    } catch { toast.error('Ошибка копирования') }
  }

  const handleDelete = async (p: Playbook) => {
    if (!confirm(`Удалить "${p.display_name}"?`)) return
    try {
      await playbooksApi.deletePlaybook(p.id)
      toast.success('Удалено')
      setPlaybooks(prev => prev.filter(x => x.id !== p.id))
    } catch { toast.error('Ошибка удаления') }
  }

  const startNew = () => {
    setEditingPlaybook({ name: '', display_name: '', document_type: 'contract', rules: [] })
    setIsNewPlaybook(true)
  }

  const filtered = playbooks.filter(p =>
    p.display_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    p.description?.toLowerCase().includes(searchQuery.toLowerCase())
  )

  if (loading) {
    return (
      <div className="flex h-screen" style={{ backgroundColor: C.bg }}>
        <UnifiedSidebar navItems={navItems} title="Legal AI" />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-6 h-6 animate-spin" style={{ color: C.subtle }} />
        </div>
      </div>
    )
  }

  if (editingPlaybook) {
    return (
      <div className="flex h-screen" style={{ backgroundColor: 'white' }}>
        <UnifiedSidebar navItems={navItems} title="Legal AI" />
        <div className="flex-1 overflow-hidden">
          <PlaybookEditor
            playbook={editingPlaybook}
            onSave={handleSave}
            onCancel={() => { setEditingPlaybook(null); setIsNewPlaybook(false) }}

          />
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-screen" style={{ backgroundColor: 'white' }}>
      <UnifiedSidebar navItems={navItems} title="Legal AI" />

      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header
          className="flex items-center justify-between px-6 py-5 border-b"
          style={{ borderColor: C.border }}
        >
          <h1 className="text-lg font-semibold" style={{ color: C.heading }}>Playbooks</h1>
          <button
            onClick={startNew}
            className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium transition-opacity hover:opacity-80"
            style={{ backgroundColor: C.btnBg, color: C.btnText }}
          >
            <Plus className="w-4 h-4" />
            Создать
          </button>
        </header>

        {/* Tabs */}
        <div className="flex items-center gap-6 px-6 border-b" style={{ borderColor: C.border }}>
          {(['playbooks', 'history'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className="py-3 text-sm font-medium border-b-2 transition-colors"
              style={{
                color: activeTab === tab ? C.heading : C.subtle,
                borderColor: activeTab === tab ? C.heading : 'transparent',
              }}
            >
              {tab === 'playbooks' ? `Мои playbooks (${playbooks.length})` : `История (${checks.length})`}
            </button>
          ))}
        </div>

        {/* Search (playbooks tab only) */}
        {activeTab === 'playbooks' && (
          <div className="px-6 py-3 border-b" style={{ borderColor: C.border }}>
            <div className="relative max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: C.subtle }} />
              <input
                type="text"
                placeholder="Поиск..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-4 py-2 rounded border text-sm focus:outline-none focus:ring-1 focus:ring-gray-400"
                style={{ borderColor: C.border, color: C.body, backgroundColor: C.bg }}
              />
            </div>
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {activeTab === 'playbooks' ? (
            filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-24 text-center">
                <BookOpen className="w-10 h-10 mb-4" style={{ color: C.subtle }} />
                <p className="text-sm font-medium mb-1" style={{ color: C.heading }}>
                  {searchQuery ? 'Ничего не найдено' : 'Нет playbooks'}
                </p>
                <p className="text-xs mb-5" style={{ color: C.label }}>
                  {searchQuery ? 'Попробуйте изменить запрос' : 'Создайте первый playbook'}
                </p>
                {!searchQuery && (
                  <button
                    onClick={startNew}
                    className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium"
                    style={{ backgroundColor: C.btnBg, color: C.btnText }}
                  >
                    <Plus className="w-4 h-4" />
                    Создать
                  </button>
                )}
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {filtered.map(p => (
                  <PlaybookCard
                    key={p.id}
                    playbook={p}
                    onEdit={() => setEditingPlaybook(p)}
                    onDuplicate={() => handleDuplicate(p)}
                    onDelete={() => handleDelete(p)}
                  />
                ))}
              </div>
            )
          ) : (
            /* History */
            <div className="space-y-2">
              {checks.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-24 text-center">
                  <CheckCircle className="w-10 h-10 mb-4" style={{ color: C.subtle }} />
                  <p className="text-sm" style={{ color: C.label }}>История проверок пуста</p>
                </div>
              ) : checks.map(ch => (
                <div
                  key={ch.id}
                  className="flex items-center justify-between p-4 rounded-lg border"
                  style={{ borderColor: C.border }}
                >
                  <div className="flex items-center gap-3">
                    {ch.overall_status === 'compliant' && <CheckCircle className="w-5 h-5" style={{ color: '#374151' }} />}
                    {ch.overall_status === 'non_compliant' && <XCircle className="w-5 h-5" style={{ color: '#374151' }} />}
                    {ch.overall_status === 'needs_review' && <AlertTriangle className="w-5 h-5" style={{ color: '#374151' }} />}
                    {!ch.overall_status && <FileText className="w-5 h-5" style={{ color: C.subtle }} />}
                    <div>
                      <div className="text-sm font-medium" style={{ color: C.heading }}>
                        {ch.document_name || 'Документ'}
                      </div>
                      <div className="text-xs" style={{ color: C.subtle }}>
                        {new Date(ch.created_at).toLocaleString('ru-RU')}
                      </div>
                    </div>
                  </div>
                  <span className="text-sm font-semibold" style={{ color: C.heading }}>
                    {ch.compliance_score?.toFixed(0) ?? 0}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
