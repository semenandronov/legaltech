"use client"

import { useEffect, useMemo, useState } from 'react'
import {
  Calendar,
  ChevronDown,
  FileUp,
  Hash,
  Loader2,
  Plus,
  Quote,
  Tag,
  ToggleLeft,
  Type,
  Wallet,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import type {
  ColumnFlagRule,
  ColumnRunCondition,
  TabularColumn,
  TabularColumnConfig,
  UserFlagColor,
} from '@/services/tabularReviewApi'
import { tabularReviewApi } from '@/services/tabularReviewApi'
import { TAG_PILL_CLASSES } from '@/utils/tabularPillUtils'
import { MikeModalShell } from './MikeModalShell'

const TAG_COLORS = [
  '#3B82F6',
  '#10B981',
  '#F59E0B',
  '#EF4444',
  '#8B5CF6',
  '#EC4899',
  '#06B6D4',
  '#84CC16',
]

const FLAG_COLORS: Array<{ value: UserFlagColor; label: string; className: string }> = [
  { value: 'red', label: 'Красный', className: 'bg-red-500' },
  { value: 'orange', label: 'Оранжевый', className: 'bg-orange-500' },
  { value: 'yellow', label: 'Жёлтый', className: 'bg-amber-400' },
  { value: 'green', label: 'Зелёный', className: 'bg-green-500' },
]

const CONDITION_OPERATORS: Array<{ value: ColumnRunCondition['operator']; label: string }> = [
  { value: 'is_yes', label: 'равно «Да»' },
  { value: 'is_no', label: 'равно «Нет»' },
  { value: 'equals', label: 'равно' },
  { value: 'not_equals', label: 'не равно' },
  { value: 'contains', label: 'содержит' },
  { value: 'is_empty', label: 'пусто / прочерк' },
  { value: 'is_not_empty', label: 'заполнено' },
]

const FORMAT_OPTIONS: Array<{
  value: TabularColumn['column_type']
  label: string
  icon: typeof Type
}> = [
  { value: 'text', label: 'Текст', icon: Type },
  { value: 'number', label: 'Число', icon: Hash },
  { value: 'currency', label: 'Валюта', icon: Wallet },
  { value: 'yes_no', label: 'Да/Нет', icon: ToggleLeft },
  { value: 'date', label: 'Дата', icon: Calendar },
  { value: 'tag', label: 'Тег', icon: Tag },
  { value: 'verbatim', label: 'Цитата', icon: Quote },
  { value: 'manual_input', label: 'Ручной ввод', icon: Type },
]

function operatorNeedsValue(operator: ColumnRunCondition['operator']): boolean {
  return operator === 'equals' || operator === 'not_equals' || operator === 'contains'
}

interface ColumnDraft {
  name: string
  prompt: string
  format: TabularColumn['column_type']
  tags: string[]
  tagInput: string
  conditionEnabled: boolean
  conditionSourceId: string
  conditionOperator: ColumnRunCondition['operator']
  conditionValue: string
  autoFlagsEnabled: boolean
  flagRules: ColumnFlagRule[]
}

const EMPTY_DRAFT: ColumnDraft = {
  name: '',
  prompt: '',
  format: 'text',
  tags: [],
  tagInput: '',
  conditionEnabled: false,
  conditionSourceId: '',
  conditionOperator: 'is_yes',
  conditionValue: '',
  autoFlagsEnabled: false,
  flagRules: [],
}

export interface MikeColumnSavePayload {
  column_label: string
  column_type: TabularColumn['column_type']
  prompt: string
  column_config?: TabularColumnConfig
}

interface MikeAddColumnModalProps {
  open: boolean
  onClose: () => void
  editingColumn?: TabularColumn | null
  /** Existing review columns (for run_condition source picker). */
  existingColumns?: TabularColumn[]
  onAdd: (columns: MikeColumnSavePayload[]) => Promise<void>
  onSave?: (columnId: string, payload: MikeColumnSavePayload) => Promise<void>
  onDelete?: (columnId: string) => Promise<boolean | void>
  /** Open checklist import / bulk column builder instead. */
  onImportChecklist?: () => void
}

function draftFromColumn(column: TabularColumn): ColumnDraft {
  const condition = column.column_config?.run_condition
  const flagRules = column.column_config?.flag_rules ?? []
  return {
    name: column.column_label,
    prompt: column.prompt || '',
    format: column.column_type,
    tags: column.column_config?.options?.map((opt) => opt.label) ?? [],
    tagInput: '',
    conditionEnabled: Boolean(condition?.source_column_id),
    conditionSourceId: condition?.source_column_id ?? '',
    conditionOperator: condition?.operator ?? 'is_yes',
    conditionValue: condition?.value ?? '',
    autoFlagsEnabled: flagRules.length > 0,
    flagRules,
  }
}

function buildColumnConfig(draft: ColumnDraft): TabularColumnConfig {
  const config: TabularColumnConfig = {}

  if (draft.format === 'tag') {
    config.options = draft.tags.map((label, index) => ({
      label,
      color: TAG_COLORS[index % TAG_COLORS.length],
    }))
  }

  if (draft.conditionEnabled && draft.conditionSourceId) {
    const runCondition: ColumnRunCondition = {
      source_column_id: draft.conditionSourceId,
      operator: draft.conditionOperator,
    }
    if (operatorNeedsValue(draft.conditionOperator)) {
      runCondition.value = draft.conditionValue.trim()
    }
    config.run_condition = runCondition
  }

  if (draft.autoFlagsEnabled && draft.flagRules.length > 0) {
    config.flag_rules = draft.flagRules
  }

  return config
}

function payloadFromDraft(draft: ColumnDraft): MikeColumnSavePayload {
  return {
    column_label: draft.name.trim(),
    column_type: draft.format,
    prompt: draft.format === 'manual_input' ? '' : draft.prompt.trim(),
    column_config: buildColumnConfig(draft),
  }
}

function defaultYesNoFlagRules(): ColumnFlagRule[] {
  return [
    { flag: 'red', match: { operator: 'is_yes' } },
    { flag: 'green', match: { operator: 'is_no' } },
  ]
}

export function MikeAddColumnModal({
  open,
  onClose,
  editingColumn,
  existingColumns = [],
  onAdd,
  onSave,
  onDelete,
  onImportChecklist,
}: MikeAddColumnModalProps) {
  const isEditing = Boolean(editingColumn)
  const [columns, setColumns] = useState<ColumnDraft[]>([{ ...EMPTY_DRAFT }])
  const [generatingIndices, setGeneratingIndices] = useState<number[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [formatMenuIndex, setFormatMenuIndex] = useState<number | null>(null)

  const sourceColumns = useMemo(() => {
    return existingColumns.filter((col) => col.id !== editingColumn?.id)
  }, [existingColumns, editingColumn?.id])

  useEffect(() => {
    if (!open) return
    if (editingColumn) {
      setColumns([draftFromColumn(editingColumn)])
    } else {
      setColumns([{ ...EMPTY_DRAFT }])
    }
    setGeneratingIndices([])
    setFormatMenuIndex(null)
  }, [open, editingColumn])

  function updateColumn(index: number, patch: Partial<ColumnDraft>) {
    setColumns((prev) => prev.map((col, i) => (i === index ? { ...col, ...patch } : col)))
  }

  function addAnotherColumn() {
    setColumns((prev) => [...prev, { ...EMPTY_DRAFT }])
  }

  function removeColumn(index: number) {
    setColumns((prev) =>
      prev.length === 1 ? [{ ...EMPTY_DRAFT }] : prev.filter((_, i) => i !== index),
    )
  }

  function commitTag(index: number) {
    const col = columns[index]
    if (!col) return
    const tag = col.tagInput.trim()
    if (!tag || col.tags.includes(tag)) {
      updateColumn(index, { tagInput: '' })
      return
    }
    updateColumn(index, { tags: [...col.tags, tag], tagInput: '' })
  }

  function handleTagKeyDown(event: React.KeyboardEvent<HTMLInputElement>, index: number) {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault()
      commitTag(index)
    } else if (
      event.key === 'Backspace' &&
      columns[index]?.tagInput === '' &&
      (columns[index]?.tags.length ?? 0) > 0
    ) {
      updateColumn(index, { tags: columns[index]!.tags.slice(0, -1) })
    }
  }

  async function autoGeneratePrompt(index: number) {
    const title = columns[index]?.name?.trim() ?? ''
    if (!title) return
    setGeneratingIndices((prev) => [...prev, index])
    try {
      const col = columns[index]!
      const result = await tabularReviewApi.generateColumnPrompt(title, col.format)
      updateColumn(index, { prompt: result.prompt })
    } catch (error) {
      console.error('Auto-generate prompt failed:', error)
    } finally {
      setGeneratingIndices((prev) => prev.filter((v) => v !== index))
    }
  }

  function validateDraft(draft: ColumnDraft): string | null {
    if (!draft.name.trim()) return 'Укажите название колонки'
    if (draft.format !== 'manual_input' && !draft.prompt.trim()) return 'Укажите промпт'
    if (draft.conditionEnabled) {
      if (!draft.conditionSourceId) return 'Выберите колонку-условие'
      if (operatorNeedsValue(draft.conditionOperator) && !draft.conditionValue.trim()) {
        return 'Укажите значение условия'
      }
    }
    if (draft.autoFlagsEnabled) {
      if (draft.flagRules.length === 0) return 'Добавьте хотя бы одно правило автофлага'
      for (const rule of draft.flagRules) {
        if (operatorNeedsValue(rule.match.operator) && !String(rule.match.value || '').trim()) {
          return 'У автофлага не хватает значения для сравнения'
        }
      }
    }
    return null
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const firstError = columns.map(validateDraft).find(Boolean)
    if (firstError || submitting) {
      if (firstError) toast.error(firstError)
      return
    }

    setSubmitting(true)
    try {
      if (isEditing && editingColumn && onSave) {
        await onSave(editingColumn.id, payloadFromDraft(columns[0]!))
      } else {
        await onAdd(columns.map(payloadFromDraft))
      }
      onClose()
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete() {
    if (!editingColumn || !onDelete || submitting) return
    setSubmitting(true)
    try {
      const deleted = await onDelete(editingColumn.id)
      if (deleted !== false) {
        onClose()
      }
    } finally {
      setSubmitting(false)
    }
  }

  const breadcrumbs = isEditing
    ? ['Табличный обзор', 'Редактировать колонку']
    : ['Табличный обзор', 'Новая колонка']

  const canSubmit =
    !submitting &&
    columns.every((col) => !validateDraft(col))

  return (
    <MikeModalShell
      open={open}
      onClose={onClose}
      breadcrumbs={breadcrumbs}
      className="ws-mike-add-column-modal"
      bodyClassName="ws-mike-add-column-modal-body"
      footer={
        <form onSubmit={(event) => void handleSubmit(event)} className="ws-mike-add-column-footer-form">
          <div>
            {isEditing && onDelete && (
              <button
                type="button"
                onClick={() => void handleDelete()}
                disabled={submitting}
                className="ws-mike-add-column-delete"
              >
                Удалить
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose} className="ws-mike-add-column-cancel">
              Отмена
            </button>
            <button type="submit" disabled={!canSubmit} className="ws-mike-add-column-submit">
              {submitting
                ? 'Сохранение…'
                : isEditing
                  ? 'Сохранить'
                  : columns.length > 1
                    ? `Добавить колонки (${columns.length})`
                    : 'Добавить колонку'}
            </button>
          </div>
        </form>
      }
    >
      {columns.map((column, index) => {
        const FormatIcon =
          FORMAT_OPTIONS.find((option) => option.value === column.format)?.icon ?? Type

        return (
          <div key={index} className="ws-mike-add-column-card">
            {!isEditing && columns.length > 1 && (
              <div className="flex justify-end mb-2">
                <button
                  type="button"
                  onClick={() => removeColumn(index)}
                  className="text-xs text-gray-400 hover:text-gray-600"
                >
                  Убрать
                </button>
              </div>
            )}

            <label className="ws-mike-add-column-label">Название</label>
            <input
              type="text"
              value={column.name}
              onChange={(event) => updateColumn(index, { name: event.target.value })}
              className="ws-mike-add-column-input"
              placeholder="Например: Стороны договора"
            />

            <div className="mt-3 relative">
              <label className="ws-mike-add-column-label">Формат</label>
              <button
                type="button"
                onClick={() => setFormatMenuIndex(formatMenuIndex === index ? null : index)}
                className="ws-mike-add-column-format-btn"
              >
                <span className="flex items-center gap-1.5">
                  <FormatIcon className="h-3.5 w-3.5 text-gray-400" />
                  {FORMAT_OPTIONS.find((option) => option.value === column.format)?.label}
                </span>
                <ChevronDown className="h-3.5 w-3.5 text-gray-400" />
              </button>
              {formatMenuIndex === index && (
                <div className="ws-mike-add-column-format-menu">
                  {FORMAT_OPTIONS.map((option) => {
                    const Icon = option.icon
                    return (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => {
                          updateColumn(index, {
                            format: option.value,
                            tags: [],
                            tagInput: '',
                            autoFlagsEnabled:
                              option.value === 'yes_no' ? column.autoFlagsEnabled : column.autoFlagsEnabled,
                            flagRules:
                              option.value === 'yes_no' && column.flagRules.length === 0
                                ? defaultYesNoFlagRules()
                                : column.flagRules,
                          })
                          setFormatMenuIndex(null)
                        }}
                        className={`ws-mike-add-column-format-option ${
                          column.format === option.value
                            ? 'ws-mike-add-column-format-option--active'
                            : ''
                        }`}
                      >
                        <Icon className="h-3.5 w-3.5 text-gray-400" />
                        {option.label}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>

            {column.format === 'tag' && (
              <div className="mt-3">
                <label className="ws-mike-add-column-label">Теги</label>
                <div className="ws-mike-add-column-tags">
                  {column.tags.map((tag, tagIdx) => (
                    <span
                      key={tag}
                      className={`ws-tabular-pill ${TAG_PILL_CLASSES[tagIdx % TAG_PILL_CLASSES.length]}`}
                    >
                      {tag}
                      <button
                        type="button"
                        onClick={() =>
                          updateColumn(index, {
                            tags: column.tags.filter((item) => item !== tag),
                          })
                        }
                        className="ws-mike-edit-col-tag-remove"
                        aria-label={`Удалить тег ${tag}`}
                      >
                        <X className="h-2 w-2" />
                      </button>
                    </span>
                  ))}
                  <input
                    type="text"
                    value={column.tagInput}
                    onChange={(event) => updateColumn(index, { tagInput: event.target.value })}
                    onKeyDown={(event) => handleTagKeyDown(event, index)}
                    onBlur={() => commitTag(index)}
                    placeholder={column.tags.length === 0 ? 'Добавить теги…' : ''}
                    className="ws-mike-add-column-tag-input"
                  />
                </div>
              </div>
            )}

            {column.format !== 'manual_input' && (
              <div className="mt-4">
                <div className="flex items-center justify-between gap-2">
                  <label className="ws-mike-add-column-label mb-0">Промпт</label>
                  <button
                    type="button"
                    onClick={() => void autoGeneratePrompt(index)}
                    disabled={!column.name.trim() || generatingIndices.includes(index)}
                    className="ws-mike-add-column-autogen"
                  >
                    {generatingIndices.includes(index) ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Plus className="h-4 w-4" />
                    )}
                    Автогенерация
                  </button>
                </div>
                <textarea
                  rows={6}
                  value={column.prompt}
                  onChange={(event) => updateColumn(index, { prompt: event.target.value })}
                  placeholder="Опишите, что ИИ должен извлечь из каждого документа для этой колонки…"
                  className="ws-mike-add-column-textarea"
                />
              </div>
            )}

            {sourceColumns.length > 0 && (
              <div className="ws-mike-add-column-advanced mt-4">
                <label className="ws-mike-add-column-check">
                  <input
                    type="checkbox"
                    checked={column.conditionEnabled}
                    onChange={(event) =>
                      updateColumn(index, {
                        conditionEnabled: event.target.checked,
                        conditionSourceId:
                          column.conditionSourceId || sourceColumns[0]?.id || '',
                      })
                    }
                  />
                  <span>Запускать только при условии</span>
                </label>
                {column.conditionEnabled && (
                  <div className="ws-mike-add-column-condition-grid">
                    <select
                      value={column.conditionSourceId}
                      onChange={(event) =>
                        updateColumn(index, { conditionSourceId: event.target.value })
                      }
                      className="ws-mike-add-column-select"
                      aria-label="Колонка-условие"
                    >
                      <option value="">Колонка…</option>
                      {sourceColumns.map((col) => (
                        <option key={col.id} value={col.id}>
                          {col.column_label}
                        </option>
                      ))}
                    </select>
                    <select
                      value={column.conditionOperator}
                      onChange={(event) =>
                        updateColumn(index, {
                          conditionOperator: event.target.value as ColumnRunCondition['operator'],
                        })
                      }
                      className="ws-mike-add-column-select"
                      aria-label="Оператор условия"
                    >
                      {CONDITION_OPERATORS.map((op) => (
                        <option key={op.value} value={op.value}>
                          {op.label}
                        </option>
                      ))}
                    </select>
                    {operatorNeedsValue(column.conditionOperator) && (
                      <input
                        type="text"
                        value={column.conditionValue}
                        onChange={(event) =>
                          updateColumn(index, { conditionValue: event.target.value })
                        }
                        className="ws-mike-add-column-input"
                        placeholder="Значение"
                      />
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="ws-mike-add-column-advanced mt-3">
              <label className="ws-mike-add-column-check">
                <input
                  type="checkbox"
                  checked={column.autoFlagsEnabled}
                  onChange={(event) => {
                    const enabled = event.target.checked
                    updateColumn(index, {
                      autoFlagsEnabled: enabled,
                      flagRules:
                        enabled && column.flagRules.length === 0
                          ? column.format === 'yes_no'
                            ? defaultYesNoFlagRules()
                            : [
                                {
                                  flag: 'orange',
                                  match: { operator: 'contains', value: '' },
                                },
                              ]
                          : column.flagRules,
                    })
                  }}
                />
                <span>Автофлаги по значению ячейки</span>
              </label>
              {column.autoFlagsEnabled && (
                <div className="space-y-2 mt-2">
                  {column.flagRules.map((rule, ruleIdx) => (
                    <div key={ruleIdx} className="ws-mike-add-column-flag-row">
                      <select
                        value={rule.match.operator}
                        onChange={(event) => {
                          const operator = event.target.value as ColumnRunCondition['operator']
                          const next = [...column.flagRules]
                          next[ruleIdx] = {
                            ...rule,
                            match: {
                              operator,
                              value: operatorNeedsValue(operator) ? rule.match.value ?? '' : null,
                            },
                          }
                          updateColumn(index, { flagRules: next })
                        }}
                        className="ws-mike-add-column-select"
                        aria-label="Оператор автофлага"
                      >
                        {CONDITION_OPERATORS.map((op) => (
                          <option key={op.value} value={op.value}>
                            {op.label}
                          </option>
                        ))}
                      </select>
                      {operatorNeedsValue(rule.match.operator) && (
                        <input
                          type="text"
                          value={rule.match.value ?? ''}
                          onChange={(event) => {
                            const next = [...column.flagRules]
                            next[ruleIdx] = {
                              ...rule,
                              match: { ...rule.match, value: event.target.value },
                            }
                            updateColumn(index, { flagRules: next })
                          }}
                          className="ws-mike-add-column-input"
                          placeholder="Значение"
                        />
                      )}
                      <div className="ws-mike-add-column-flag-swatches">
                        {FLAG_COLORS.map((color) => (
                          <button
                            key={color.value}
                            type="button"
                            title={color.label}
                            aria-label={color.label}
                            onClick={() => {
                              const next = [...column.flagRules]
                              next[ruleIdx] = { ...rule, flag: color.value }
                              updateColumn(index, { flagRules: next })
                            }}
                            className={`ws-mike-flag-swatch ${color.className} ${
                              rule.flag === color.value ? 'ws-mike-flag-swatch--active' : ''
                            }`}
                          />
                        ))}
                      </div>
                      <button
                        type="button"
                        className="text-xs text-gray-400 hover:text-gray-600"
                        onClick={() =>
                          updateColumn(index, {
                            flagRules: column.flagRules.filter((_, i) => i !== ruleIdx),
                          })
                        }
                      >
                        Убрать
                      </button>
                    </div>
                  ))}
                  <button
                    type="button"
                    className="ws-mike-add-column-autogen"
                    onClick={() =>
                      updateColumn(index, {
                        flagRules: [
                          ...column.flagRules,
                          {
                            flag: 'yellow',
                            match: { operator: 'contains', value: '' },
                          },
                        ],
                      })
                    }
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Правило
                  </button>
                </div>
              )}
            </div>
          </div>
        )
      })}

      {!isEditing && (
        <button type="button" onClick={addAnotherColumn} className="ws-mike-add-column-another">
          <Plus className="h-4 w-4" />
          Добавить ещё колонку
        </button>
      )}

      {!isEditing && onImportChecklist && (
        <button
          type="button"
          className="ws-mike-add-column-another mt-2"
          onClick={() => {
            onClose()
            onImportChecklist()
          }}
        >
          <FileUp className="h-4 w-4" />
          Импорт чек-листа из файла
        </button>
      )}
    </MikeModalShell>
  )
}
