import { useState, useEffect } from "react"
import Modal from "@/components/UI/Modal"
import { Popover } from "@mui/material"
import { Button } from "@/components/UI/Button"
import Input from "@/components/UI/Input"
import { Textarea } from "@/components/UI/Textarea"
import { toast } from "sonner"
import { tabularReviewApi } from "@/services/tabularReviewApi"

interface ColumnBuilderProps {
  isOpen: boolean
  onClose: () => void
  onSave: (column: {
    column_label: string
    column_type: string
    prompt: string
    column_config?: {
      options?: Array<{ label: string; color: string }>
      allow_custom?: boolean
    }
  }) => Promise<void>
  editingColumn?: {
    id: string
    label: string
    type: string
    prompt: string
    column_config?: {
      options?: Array<{ label: string; color: string }>
      allow_custom?: boolean
    }
  } | null
  /** Якорь для поповера — окно открывается внутри колонки (под кнопкой/заголовком) */
  anchorEl?: HTMLElement | null
  /** Начать сразу со второго шага (промпт уже введён inline) */
  startAtStep?: 1 | 2
  /** Промпт, введённый на первом шаге (inline), передаётся сразу на шаг 2 */
  initialPrompt?: string
  /** Режим отображения: модалка / поповер / inline внутри таблицы */
  mode?: 'modal' | 'popover' | 'inline'
}

const COLUMN_TYPES = [
  {
    value: "text",
    label: "Текст",
    icon: "📝",
    description: "Краткий ответ словами: стороны, суть, условия.",
  },
  {
    value: "number",
    label: "Число",
    icon: "#",
    description: "Количество, проценты, номера без валюты.",
  },
  {
    value: "currency",
    label: "Валюта",
    icon: "$",
    description: "Суммы с валютой: требования, платежи, штрафы.",
  },
  {
    value: "yes_no",
    label: "Да/Нет",
    icon: "✓",
    description: "Есть ли в документе указанный факт.",
  },
  {
    value: "date",
    label: "Дата",
    icon: "📅",
    description: "Дата подписания, вынесения акта, срока.",
  },
  {
    value: "tag",
    label: "Тег",
    icon: "🏷️",
    description: "Категория из заранее заданного списка.",
  },
  {
    value: "verbatim",
    label: "Дословно",
    icon: "💬",
    description: "Точная цитата из документа без перефразирования.",
  },
  {
    value: "manual_input",
    label: "Ручной ввод",
    icon: "✏️",
    description: "Заполняете сами, без автоматического извлечения.",
  },
]

// Цвета для тегов (как у Legora)
const TAG_COLORS = [
  "#3B82F6", // синий
  "#10B981", // зеленый
  "#F59E0B", // желтый
  "#EF4444", // красный
  "#8B5CF6", // фиолетовый
  "#EC4899", // розовый
  "#06B6D4", // голубой
  "#84CC16", // лайм
]

function suggestLabelFromPrompt(promptText: string): string {
  const trimmed = promptText.trim()
  if (!trimmed) return ""
  const firstLine = trimmed.split(/\n/)[0]?.trim() || trimmed
  if (firstLine.length <= 45) return firstLine
  return firstLine.slice(0, 42).trim() + "…"
}

const popoverProps = {
  anchorReference: "anchorEl" as const,
  anchorOrigin: { vertical: "bottom" as const, horizontal: "right" as const },
  transformOrigin: { vertical: "top" as const, horizontal: "right" as const },
  slotProps: { root: { disableScrollLock: true }, backdrop: { sx: { backgroundColor: "transparent" } } },
  PaperProps: { sx: { minWidth: 320, maxWidth: 380, p: 2, borderRadius: 2, boxShadow: 2 } },
}

export function ColumnBuilder({ isOpen, onClose, onSave, editingColumn, anchorEl, startAtStep, initialPrompt, mode = 'modal' }: ColumnBuilderProps) {
  const [step, setStep] = useState<1 | 2>(1)
  const [columnLabel, setColumnLabel] = useState(editingColumn?.label || "")
  const [columnType, setColumnType] = useState(editingColumn?.type || "text")
  const [prompt, setPrompt] = useState(editingColumn?.prompt || "")
  const [saving, setSaving] = useState(false)
  
  const [tagOptions, setTagOptions] = useState<Array<{ label: string; color: string }>>(
    editingColumn?.column_config?.options || [
      { label: "Email", color: TAG_COLORS[0] },
      { label: "Contract", color: TAG_COLORS[1] },
      { label: "Letter", color: TAG_COLORS[2] },
    ]
  )
  const [newTagLabel, setNewTagLabel] = useState("")
  const [inferringType, setInferringType] = useState(false)
  const [typeInferenceReason, setTypeInferenceReason] = useState<string | null>(null)
  
  // При открытии: сброс или подстановка данных (создание и редактирование — один поток)
  useEffect(() => {
    if (!isOpen) return
    if (editingColumn) {
      setStep(1)
      setColumnLabel(editingColumn.label)
      setColumnType(editingColumn.type)
      setPrompt(editingColumn.prompt || "")
      setTagOptions(editingColumn.column_config?.options || [
        { label: "Email", color: TAG_COLORS[0] },
        { label: "Contract", color: TAG_COLORS[1] },
        { label: "Letter", color: TAG_COLORS[2] },
      ])
    } else {
      const effectiveStep = startAtStep || 1
      const effectivePrompt = initialPrompt || ""
      setStep(effectiveStep)
      setPrompt(effectivePrompt)
      setColumnLabel(effectiveStep === 2 && effectivePrompt ? suggestLabelFromPrompt(effectivePrompt) : "")
      setColumnType("text")
      setTypeInferenceReason(null)
      setTagOptions([
        { label: "Email", color: TAG_COLORS[0] },
        { label: "Contract", color: TAG_COLORS[1] },
        { label: "Letter", color: TAG_COLORS[2] },
      ])
    }
  }, [isOpen, editingColumn, startAtStep, initialPrompt])

  useEffect(() => {
    if (!isOpen || editingColumn) return
    const effectiveStep = startAtStep || 1
    const effectivePrompt = (initialPrompt || "").trim()
    if (effectiveStep !== 2 || !effectivePrompt) return
    const label = suggestLabelFromPrompt(effectivePrompt)
    void inferTypeForStep2(label, effectivePrompt)
  }, [isOpen, editingColumn, startAtStep, initialPrompt])

  const inferTypeForStep2 = async (label: string, question: string) => {
    setInferringType(true)
    setTypeInferenceReason(null)
    try {
      const inferred = await tabularReviewApi.inferColumnType(question, label || undefined)
      setColumnType(inferred.column_type)
      setTypeInferenceReason(inferred.reason)
      if (!label.trim() && inferred.suggested_label) {
        setColumnLabel(inferred.suggested_label)
      }
    } catch (error) {
      console.error("Failed to infer column type:", error)
      setColumnType("text")
    } finally {
      setInferringType(false)
    }
  }

  const handleContinueToStep2 = async () => {
    if (!prompt.trim()) {
      toast.error("Введите вопрос для колонки")
      return
    }
    const label = suggestLabelFromPrompt(prompt)
    setColumnLabel(label)
    setStep(2)
    await inferTypeForStep2(label, prompt)
  }

  const handleBackToStep1 = () => {
    setStep(1)
  }

  const handleAddTag = () => {
    if (!newTagLabel.trim()) return
    const color = TAG_COLORS[tagOptions.length % TAG_COLORS.length]
    setTagOptions([...tagOptions, { label: newTagLabel.trim(), color }])
    setNewTagLabel("")
  }

  const handleRemoveTag = (index: number) => {
    setTagOptions(tagOptions.filter((_, i) => i !== index))
  }

  const handleSave = async () => {
    if (!columnLabel.trim() || !prompt.trim()) {
      return
    }

    // Для tag нужны опции
    if (columnType === "tag" && tagOptions.length === 0) {
      toast.error("Добавьте хотя бы одну опцию для тегов")
      return
    }

    setSaving(true)
    try {
      const columnConfig = columnType === "tag"
        ? { options: tagOptions, allow_custom: false }
        : undefined

      await onSave({
        column_label: columnLabel,
        column_type: columnType,
        prompt: prompt,
        column_config: columnConfig,
      })
      // Reset form
      setColumnLabel("")
      setColumnType("text")
      setPrompt("")
      setTagOptions([
        { label: "Email", color: TAG_COLORS[0] },
        { label: "Contract", color: TAG_COLORS[1] },
        { label: "Letter", color: TAG_COLORS[2] },
      ])
      onClose()
    } catch (error) {
      console.error("Error saving column:", error)
    } finally {
      setSaving(false)
    }
  }

  // Сброс тегов при смене типа колонки
  const handleColumnTypeChange = (newType: string) => {
    setColumnType(newType)
    if (newType !== "tag") {
      setTagOptions([])
    } else if (tagOptions.length === 0) {
      setTagOptions([
        { label: "Email", color: TAG_COLORS[0] },
        { label: "Contract", color: TAG_COLORS[1] },
        { label: "Letter", color: TAG_COLORS[2] },
      ])
    }
  }

  // Шаг 1: промпт (создание и редактирование)
  const step1Content = (
    <>
      <p className="text-sm text-muted-foreground mb-4">
        Один вопрос — одна колонка. ИИ ответит отдельно по каждому документу в таблице.
      </p>
      <div className="space-y-4">
        <div>
          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Например: дата подписания этого документа"
            rows={4}
            className="resize-none"
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={handleContinueToStep2} disabled={!prompt.trim()}>
            Далее
          </Button>
        </div>
      </div>
    </>
  )

  const step2Footer = (
    <div
      className="flex justify-end gap-2 pt-3 mt-1 border-t border-border shrink-0"
      style={{ backgroundColor: 'var(--color-bg-elevated, #fff)' }}
    >
      {!startAtStep || startAtStep < 2 ? (
        <Button variant="ghost" onClick={handleBackToStep1} disabled={saving}>
          Назад
        </Button>
      ) : null}
      <Button variant="outline" onClick={onClose} disabled={saving}>
        Отмена
      </Button>
      <Button onClick={handleSave} disabled={saving || !columnLabel.trim()}>
        {saving ? "Сохранение…" : "Сохранить"}
      </Button>
    </div>
  )

  // Шаг 2: название колонки и тип (создание и редактирование)
  const step2Content = (
    <div className="flex flex-col">
      <div className="space-y-4">
        <div>
          <label className="text-sm font-medium mb-2 block">Название колонки</label>
          <Input
            value={columnLabel}
            onChange={(e) => setColumnLabel(e.target.value)}
            placeholder="Например: Дата подписания"
          />
        </div>
        <div>
          <label className="text-sm font-medium mb-2 block">Тип колонки</label>
          {inferringType && (
            <p className="text-xs text-muted-foreground mb-2">Подбираем тип по вопросу…</p>
          )}
          {!inferringType && typeInferenceReason && (
            <p className="text-xs text-muted-foreground mb-2">Рекомендация: {typeInferenceReason}</p>
          )}
          <div className="grid grid-cols-2 gap-2">
            {COLUMN_TYPES.map((type) => {
              const isSelected = columnType === type.value
              return (
                <button
                  key={type.value}
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleColumnTypeChange(type.value)
                  }}
                  onPointerDown={(e) => e.stopPropagation()}
                  className={[
                    "rounded-lg border px-3 py-2.5 transition-all duration-150 text-left h-full",
                    isSelected
                      ? "border-[var(--color-accent)] bg-[var(--color-accent-subtle,rgba(99,102,241,0.12))] shadow-sm"
                      : "border-border bg-background hover:border-[var(--color-accent)] hover:bg-[var(--color-bg-hover)]",
                  ].join(" ")}
                >
                  <div className="flex items-start gap-2 min-w-0">
                    <span className="text-base leading-none shrink-0 mt-0.5" aria-hidden>
                      {type.icon}
                    </span>
                    <div className="min-w-0">
                      <span
                        className={`text-sm font-medium block ${
                          isSelected ? "text-[var(--color-accent)]" : "text-foreground"
                        }`}
                      >
                        {type.label}
                      </span>
                      <p className="text-xs text-muted-foreground mt-1 leading-snug">
                        {type.description}
                      </p>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
        {columnType === "tag" && (
          <div>
            <label className="text-sm font-medium mb-2 block">Опции тега</label>
            <div className="space-y-2">
              {tagOptions.map((option, index) => (
                <div key={index} className="flex items-center gap-2 p-2 border rounded">
                  <div className="w-4 h-4 rounded shrink-0" style={{ backgroundColor: option.color }} />
                  <Input
                    value={option.label}
                    onChange={(e) => {
                      const next = [...tagOptions]
                      next[index] = { ...next[index], label: e.target.value }
                      setTagOptions(next)
                    }}
                    className="flex-1"
                  />
                  <Button variant="ghost" size="sm" className="text-red-500" onClick={() => handleRemoveTag(index)}>×</Button>
                </div>
              ))}
              <div className="flex gap-2">
                <Input value={newTagLabel} onChange={(e) => setNewTagLabel(e.target.value)} placeholder="Новая опция" onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), handleAddTag())} />
                <Button variant="outline" size="sm" onClick={handleAddTag} disabled={!newTagLabel.trim()}>+ Добавить</Button>
              </div>
            </div>
          </div>
        )}
      </div>
      {step2Footer}
    </div>
  )

  const usePopover = anchorEl && typeof anchorEl.isConnected === 'boolean' && anchorEl.isConnected

  // Привязываем поповер к DOM-дереву колонки, чтобы он визуально жил "внутри" хедера
  const popoverContainer = anchorEl
    ? (anchorEl.closest('th') as HTMLElement | null) ??
      (anchorEl.closest('.MuiTableCell-root') as HTMLElement | null) ??
      undefined
    : undefined

  const popoverPropsWithContainer = {
    ...popoverProps,
    disablePortal: true,
    container: popoverContainer,
  }

  // Inline-режим: оба шага рендерятся как обычный контент без Modal/Popover
  if (mode === 'inline') {
    return (
      <div className="px-1">
        <h3 className="text-sm font-semibold mb-3">
          {step === 1 ? 'Промпт' : 'Название и тип колонки'}
        </h3>
        {step === 1 ? step1Content : step2Content}
      </div>
    )
  }

  if (step === 1) {
    if (usePopover && mode === 'popover') {
      return (
        <Popover open={isOpen} anchorEl={anchorEl} onClose={onClose} {...popoverPropsWithContainer}>
          <div className="px-1"><h3 className="text-sm font-semibold mb-3">Промпт</h3>{step1Content}</div>
        </Popover>
      )
    }
    return (
      <Modal isOpen={isOpen} onClose={onClose} title="Промпт" size="sm">
        {step1Content}
      </Modal>
    )
  }

  // Шаг 2 всегда в широкой модалке — не в узком поповере/оверлее таблицы
  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Название и тип колонки" size="lg" fitContent>
      {step2Content}
    </Modal>
  )
}

