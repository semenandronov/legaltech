/**
 * Playbooks Management Page
 * 
 * Эта страница для УПРАВЛЕНИЯ playbooks (создание, редактирование, удаление).
 * ЗАПУСК playbooks происходит из:
 * - Страницы Документов (кнопка "Проверить Playbook" на каждом документе)
 * - Word Add-In (если есть)
 */
import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  BookOpen,
  Plus,
  Search,
  ChevronRight,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
  MoreVertical,
  Copy,
  Trash2,
  Edit,
  FileText,
  Loader2,
  Shield,
  Target,
  Ban,
  X,
  Save,
  ArrowLeft,
  MessageSquare,
  Table,
  FileEdit,
  Workflow
} from 'lucide-react'
import { toast } from 'sonner'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import * as playbooksApi from '../services/playbooksApi'
import type { Playbook, PlaybookRule, PlaybookCheck } from '../services/playbooksApi'

// Компонент для типа правила
const RuleTypeBadge = ({ type }: { type: string }) => {
  const getStyle = () => {
    switch (type) {
      case 'red_line':
        return { bg: 'rgba(239, 68, 68, 0.15)', color: '#ef4444', icon: Target, label: 'Обязательное' }
      case 'no_go':
        return { bg: 'rgba(220, 38, 38, 0.15)', color: '#dc2626', icon: Ban, label: 'Запрещённое' }
      case 'fallback':
        return { bg: 'rgba(234, 179, 8, 0.15)', color: '#eab308', icon: Shield, label: 'Рекомендуемое' }
      default:
        return { bg: 'rgba(156, 163, 175, 0.15)', color: '#9ca3af', icon: Shield, label: type }
    }
  }

  const style = getStyle()
  const Icon = style.icon

  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium"
      style={{ backgroundColor: style.bg, color: style.color }}
    >
      <Icon className="w-3 h-3" />
      {style.label}
    </span>
  )
}

// Карточка Playbook для списка
const PlaybookCard = ({
  playbook,
  onEdit,
  onDuplicate,
  onDelete
}: {
  playbook: Playbook
  onEdit: () => void
  onDuplicate: () => void
  onDelete: () => void
}) => {
  const [menuOpen, setMenuOpen] = useState(false)

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
            className="w-10 h-10 rounded-lg flex items-center justify-center"
            style={{ backgroundColor: 'rgba(99, 102, 241, 0.15)' }}
          >
            <BookOpen className="w-5 h-5" style={{ color: 'var(--color-accent)' }} />
          </div>
          <div>
            <h3
              className="font-semibold text-base cursor-pointer hover:text-accent"
              style={{ color: 'var(--color-text-primary)' }}
              onClick={onEdit}
            >
              {playbook.display_name}
            </h3>
            <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              {playbook.is_system ? 'Системный' : 'Пользовательский'}
              {playbook.document_type && ` • ${playbook.document_type}`}
            </p>
          </div>
        </div>

        {/* Menu */}
        <div className="relative">
          <button
            className="p-1.5 rounded-md hover:bg-bg-hover opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ color: 'var(--color-text-secondary)' }}
            onClick={() => setMenuOpen(!menuOpen)}
          >
            <MoreVertical className="w-4 h-4" />
          </button>

          {menuOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
              <div
                className="absolute right-0 top-8 w-40 rounded-lg border shadow-lg py-1 z-20"
                style={{
                  backgroundColor: 'var(--color-bg-primary)',
                  borderColor: 'var(--color-border)'
                }}
              >
                <button
                  className="w-full px-3 py-2 text-left text-sm flex items-center gap-2 hover:bg-bg-hover"
                  style={{ color: 'var(--color-text-primary)' }}
                  onClick={() => {
                    onEdit()
                    setMenuOpen(false)
                  }}
                >
                  <Edit className="w-4 h-4" />
                  Редактировать
                </button>
                <button
                  className="w-full px-3 py-2 text-left text-sm flex items-center gap-2 hover:bg-bg-hover"
                  style={{ color: 'var(--color-text-primary)' }}
                  onClick={() => {
                    onDuplicate()
                    setMenuOpen(false)
                  }}
                >
                  <Copy className="w-4 h-4" />
                  Дублировать
                </button>
                {!playbook.is_system && (
                  <button
                    className="w-full px-3 py-2 text-left text-sm flex items-center gap-2 hover:bg-bg-hover"
                    style={{ color: 'var(--color-error)' }}
                    onClick={() => {
                      onDelete()
                      setMenuOpen(false)
                    }}
                  >
                    <Trash2 className="w-4 h-4" />
                    Удалить
                  </button>
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

      {/* Stats */}
      <div className="flex items-center gap-4 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
        <span className="flex items-center gap-1">
          <Target className="w-3.5 h-3.5" />
          {playbook.rules_count} правил
        </span>
        <span className="flex items-center gap-1">
          <CheckCircle className="w-3.5 h-3.5" />
          {playbook.usage_count} проверок
        </span>
      </div>

      {/* Edit button */}
      <button
        onClick={onEdit}
        className="w-full mt-4 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors"
        style={{
          backgroundColor: 'var(--color-bg-hover)',
          color: 'var(--color-text-primary)',
        }}
      >
        <Edit className="w-4 h-4" />
        Редактировать правила
      </button>
    </div>
  )
}

// Форма редактирования Playbook
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
  const [editingRule, setEditingRule] = useState<number | null>(null)
  const [newRule, setNewRule] = useState(false)

  const addRule = () => {
    setForm(prev => ({
      ...prev,
      rules: [
        ...prev.rules,
        {
          id: `new_${Date.now()}`,
          playbook_id: playbook.id || '',
          rule_type: 'red_line',
          clause_category: '',
          rule_name: '',
          description: '',
          condition_type: 'must_exist',
          condition_config: {},
          priority: prev.rules.length,
          severity: 'medium',
          is_active: true,
          created_at: new Date().toISOString()
        } as PlaybookRule
      ]
    }))
    setEditingRule(form.rules.length)
    setNewRule(true)
  }

  const updateRule = (index: number, updates: Partial<PlaybookRule>) => {
    setForm(prev => ({
      ...prev,
      rules: prev.rules.map((r, i) => i === index ? { ...r, ...updates } : r)
    }))
  }

  const removeRule = (index: number) => {
    setForm(prev => ({
      ...prev,
      rules: prev.rules.filter((_, i) => i !== index)
    }))
    setEditingRule(null)
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div
        className="flex items-center justify-between p-4 border-b shrink-0"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-center gap-3">
          <button
            onClick={onCancel}
            className="p-2 rounded-lg hover:bg-bg-hover"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
            {isNew ? 'Новый Playbook' : 'Редактирование Playbook'}
          </h2>
        </div>
        <button
          onClick={() => onSave(form)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium"
          style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
        >
          <Save className="w-4 h-4" />
          Сохранить
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Basic Info */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>
              Название (ID)
            </label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value.toLowerCase().replace(/\s/g, '_') })}
              placeholder="nda_compliance"
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{
                backgroundColor: 'var(--color-bg-secondary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)'
              }}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>
              Отображаемое название
            </label>
            <input
              type="text"
              value={form.display_name}
              onChange={(e) => setForm({ ...form, display_name: e.target.value })}
              placeholder="NDA Compliance Check"
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{
                backgroundColor: 'var(--color-bg-secondary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)'
              }}
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>
            Описание
          </label>
          <textarea
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="Описание playbook..."
            rows={3}
            className="w-full px-3 py-2 rounded-lg border text-sm resize-none"
            style={{
              backgroundColor: 'var(--color-bg-secondary)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)'
            }}
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>
              Тип документа
            </label>
            <select
              value={form.document_type}
              onChange={(e) => setForm({ ...form, document_type: e.target.value })}
              className="w-full px-3 py-2 rounded-lg border text-sm"
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
              <option value="court_document">Судебный документ</option>
              <option value="other">Другое</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>
              Юрисдикция
            </label>
            <input
              type="text"
              value={form.jurisdiction}
              onChange={(e) => setForm({ ...form, jurisdiction: e.target.value })}
              placeholder="Россия"
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{
                backgroundColor: 'var(--color-bg-secondary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)'
              }}
            />
          </div>
        </div>

        {/* Rules */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-base font-semibold" style={{ color: 'var(--color-text-primary)' }}>
              Правила ({form.rules.length})
            </h3>
            <button
              onClick={addRule}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-medium"
              style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
            >
              <Plus className="w-4 h-4" />
              Добавить правило
            </button>
          </div>

          <div className="space-y-3">
            {form.rules.map((rule, index) => (
              <div
                key={rule.id}
                className="rounded-lg border p-4"
                style={{
                  backgroundColor: 'var(--color-bg-secondary)',
                  borderColor: editingRule === index ? 'var(--color-accent)' : 'var(--color-border)'
                }}
              >
                {editingRule === index ? (
                  // Edit mode
                  <div className="space-y-3">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                          Название правила
                        </label>
                        <input
                          type="text"
                          value={rule.rule_name}
                          onChange={(e) => updateRule(index, { rule_name: e.target.value })}
                          placeholder="Срок конфиденциальности"
                          className="w-full px-3 py-2 rounded-lg border text-sm"
                          style={{
                            backgroundColor: 'var(--color-bg-primary)',
                            borderColor: 'var(--color-border)',
                            color: 'var(--color-text-primary)'
                          }}
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                          Тип правила
                        </label>
                        <select
                          value={rule.rule_type}
                          onChange={(e) => updateRule(index, { rule_type: e.target.value as any })}
                          className="w-full px-3 py-2 rounded-lg border text-sm"
                          style={{
                            backgroundColor: 'var(--color-bg-primary)',
                            borderColor: 'var(--color-border)',
                            color: 'var(--color-text-primary)'
                          }}
                        >
                          <option value="red_line">Обязательное (Red Line)</option>
                          <option value="fallback">Рекомендуемое (Fallback)</option>
                          <option value="no_go">Запрещённое (No-Go)</option>
                        </select>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                          Категория пункта
                        </label>
                        <input
                          type="text"
                          value={rule.clause_category}
                          onChange={(e) => updateRule(index, { clause_category: e.target.value })}
                          placeholder="confidentiality"
                          className="w-full px-3 py-2 rounded-lg border text-sm"
                          style={{
                            backgroundColor: 'var(--color-bg-primary)',
                            borderColor: 'var(--color-border)',
                            color: 'var(--color-text-primary)'
                          }}
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                          Тип условия
                        </label>
                        <select
                          value={rule.condition_type}
                          onChange={(e) => updateRule(index, { condition_type: e.target.value })}
                          className="w-full px-3 py-2 rounded-lg border text-sm"
                          style={{
                            backgroundColor: 'var(--color-bg-primary)',
                            borderColor: 'var(--color-border)',
                            color: 'var(--color-text-primary)'
                          }}
                        >
                          <option value="must_exist">Должен присутствовать</option>
                          <option value="must_not_exist">Не должен присутствовать</option>
                          <option value="value_check">Проверка значения</option>
                          <option value="duration_check">Проверка срока</option>
                          <option value="text_match">Текст должен содержать</option>
                          <option value="text_not_match">Текст не должен содержать</option>
                        </select>
                      </div>
                    </div>

                    <div>
                      <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                        Описание правила
                      </label>
                      <textarea
                        value={rule.description || ''}
                        onChange={(e) => updateRule(index, { description: e.target.value })}
                        placeholder="Подробное описание правила..."
                        rows={2}
                        className="w-full px-3 py-2 rounded-lg border text-sm resize-none"
                        style={{
                          backgroundColor: 'var(--color-bg-primary)',
                          borderColor: 'var(--color-border)',
                          color: 'var(--color-text-primary)'
                        }}
                      />
                    </div>

                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => removeRule(index)}
                        className="px-3 py-1.5 rounded-lg text-sm font-medium"
                        style={{ backgroundColor: 'rgba(239, 68, 68, 0.1)', color: '#ef4444' }}
                      >
                        Удалить
                      </button>
                      <button
                        onClick={() => {
                          setEditingRule(null)
                          setNewRule(false)
                        }}
                        className="px-3 py-1.5 rounded-lg text-sm font-medium"
                        style={{ backgroundColor: 'var(--color-accent)', color: 'white' }}
                      >
                        Готово
                      </button>
                    </div>
                  </div>
                ) : (
                  // View mode
                  <div
                    className="flex items-center justify-between cursor-pointer"
                    onClick={() => setEditingRule(index)}
                  >
                    <div className="flex items-center gap-3">
                      <RuleTypeBadge type={rule.rule_type} />
                      <span className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                        {rule.rule_name || 'Без названия'}
                      </span>
                    </div>
                    <ChevronRight className="w-4 h-4" style={{ color: 'var(--color-text-tertiary)' }} />
                  </div>
                )}
              </div>
            ))}

            {form.rules.length === 0 && (
              <div className="text-center py-8">
                <Target className="w-12 h-12 mx-auto mb-3" style={{ color: 'var(--color-text-tertiary)' }} />
                <p style={{ color: 'var(--color-text-secondary)' }}>
                  Нет правил. Добавьте первое правило.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// Главная страница
export default function PlaybooksPage() {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()

  const [playbooks, setPlaybooks] = useState<Playbook[]>([])
  const [checks, setChecks] = useState<PlaybookCheck[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'playbooks' | 'history'>('playbooks')
  const [searchQuery, setSearchQuery] = useState('')
  const [editingPlaybook, setEditingPlaybook] = useState<Partial<Playbook> | null>(null)
  const [isNewPlaybook, setIsNewPlaybook] = useState(false)

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

  // Сохранение playbook
  const handleSavePlaybook = async (data: Partial<Playbook>) => {
    try {
      if (isNewPlaybook) {
        await playbooksApi.createPlaybook({
          name: data.name!,
          display_name: data.display_name!,
          description: data.description,
          contract_type: data.document_type || 'contract',
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
        toast.success('Playbook создан')
      } else {
        await playbooksApi.updatePlaybook(editingPlaybook!.id!, data)
        toast.success('Playbook сохранён')
      }

      // Reload
      const updated = await playbooksApi.getPlaybooks()
      setPlaybooks(updated)
      setEditingPlaybook(null)
      setIsNewPlaybook(false)
    } catch (error) {
      toast.error('Ошибка сохранения')
    }
  }

  // Дублирование playbook
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

  // Удаление playbook
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

  // Фильтрация
  const filteredPlaybooks = playbooks.filter(p =>
    p.display_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    p.description?.toLowerCase().includes(searchQuery.toLowerCase())
  )

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
          className="flex items-center justify-between px-6 py-4 border-b"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div>
            <h1 className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>
              Управление Playbooks
            </h1>
            <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              Создание и редактирование правил проверки документов
            </p>
          </div>

          <button
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium"
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
          className="mx-6 mt-4 p-4 rounded-lg flex items-start gap-3"
          style={{ backgroundColor: 'rgba(99, 102, 241, 0.1)' }}
        >
          <BookOpen className="w-5 h-5 shrink-0 mt-0.5" style={{ color: 'var(--color-accent)' }} />
          <div>
            <p className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
              Как использовать Playbooks
            </p>
            <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              Для проверки документа перейдите на страницу <strong>Документы</strong> и нажмите кнопку
              "Проверить Playbook" на нужном документе.
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
            Мои Playbooks
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

        {/* Search */}
        <div className="px-6 py-4">
          <div className="relative max-w-md">
            <Search
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4"
              style={{ color: 'var(--color-text-tertiary)' }}
            />
            <input
              type="text"
              placeholder="Поиск playbooks..."
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
          {activeTab === 'playbooks' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredPlaybooks.map(playbook => (
                <PlaybookCard
                  key={playbook.id}
                  playbook={playbook}
                  onEdit={() => setEditingPlaybook(playbook)}
                  onDuplicate={() => handleDuplicate(playbook)}
                  onDelete={() => handleDelete(playbook)}
                />
              ))}

              {filteredPlaybooks.length === 0 && (
                <div className="col-span-full text-center py-12">
                  <BookOpen
                    className="w-12 h-12 mx-auto mb-4"
                    style={{ color: 'var(--color-text-tertiary)' }}
                  />
                  <p style={{ color: 'var(--color-text-secondary)' }}>
                    {searchQuery ? 'Ничего не найдено' : 'Нет playbooks. Создайте первый!'}
                  </p>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              {checks.map(check => (
                <div
                  key={check.id}
                  className="flex items-center justify-between p-4 rounded-lg border"
                  style={{
                    backgroundColor: 'var(--color-bg-secondary)',
                    borderColor: 'var(--color-border)'
                  }}
                >
                  <div className="flex items-center gap-4">
                    {check.overall_status === 'compliant' && <CheckCircle className="w-5 h-5" style={{ color: '#22c55e' }} />}
                    {check.overall_status === 'non_compliant' && <XCircle className="w-5 h-5" style={{ color: '#ef4444' }} />}
                    {check.overall_status === 'needs_review' && <AlertTriangle className="w-5 h-5" style={{ color: '#eab308' }} />}
                    <div>
                      <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                        {check.document_name || 'Документ'}
                      </div>
                      <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                        {new Date(check.created_at).toLocaleString('ru-RU')}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="text-right">
                      <div className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                        {check.compliance_score?.toFixed(0) || 0}%
                      </div>
                      <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                        соответствие
                      </div>
                    </div>
                  </div>
                </div>
              ))}

              {checks.length === 0 && (
                <div className="text-center py-12">
                  <CheckCircle
                    className="w-12 h-12 mx-auto mb-4"
                    style={{ color: 'var(--color-text-tertiary)' }}
                  />
                  <p style={{ color: 'var(--color-text-secondary)' }}>
                    История проверок пуста
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
