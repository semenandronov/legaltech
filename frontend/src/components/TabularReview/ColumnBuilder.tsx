import { useState, useEffect } from "react"
import Modal from "@/components/UI/Modal"
import { Button } from "@/components/UI/Button"
import Input from "@/components/UI/Input"
import { Textarea } from "@/components/UI/Textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/UI/Select"
import { Button as MUIButton, CircularProgress, Tooltip } from "@mui/material"
import { AutoAwesome as AutoAwesomeIcon } from "@mui/icons-material"
import { tabularReviewApi } from "@/services/tabularReviewApi"
import { toast } from "sonner"

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
}

const COLUMN_TYPES = [
  { value: "text", label: "Text", icon: "📝" },
  { value: "number", label: "Number", icon: "#" },
  { value: "currency", label: "Currency", icon: "$" },
  { value: "yes_no", label: "Yes/No", icon: "✓" },
  { value: "date", label: "Date", icon: "📅" },
  { value: "tag", label: "Tag", icon: "🏷️" },
  { value: "verbatim", label: "Verbatim", icon: "💬" },
  { value: "manual_input", label: "Manual input", icon: "✏️" },
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

export function ColumnBuilder({ isOpen, onClose, onSave, editingColumn }: ColumnBuilderProps) {
  const isCreate = !editingColumn
  const [step, setStep] = useState<1 | 2>(1)
  const [columnLabel, setColumnLabel] = useState(editingColumn?.label || "")
  const [columnType, setColumnType] = useState(editingColumn?.type || "text")
  const [prompt, setPrompt] = useState(editingColumn?.prompt || "")
  const [saving, setSaving] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  
  // Конфигурация для tag
  const [tagOptions, setTagOptions] = useState<Array<{ label: string; color: string }>>(
    editingColumn?.column_config?.options || [
      { label: "Email", color: TAG_COLORS[0] },
      { label: "Contract", color: TAG_COLORS[1] },
      { label: "Letter", color: TAG_COLORS[2] },
    ]
  )
  const [newTagLabel, setNewTagLabel] = useState("")
  
  // При открытии в режиме создания — сброс на шаг 1
  useEffect(() => {
    if (isOpen && isCreate) {
      setStep(1)
      setPrompt("")
      setColumnLabel("")
      setColumnType("verbatim")
    }
  }, [isOpen, isCreate])
  
  // Обновляем поля при изменении editingColumn
  useEffect(() => {
    if (editingColumn) {
      setColumnLabel(editingColumn.label)
      setColumnType(editingColumn.type)
      setPrompt(editingColumn.prompt || "")
      setTagOptions(editingColumn.column_config?.options || [
        { label: "Email", color: TAG_COLORS[0] },
        { label: "Contract", color: TAG_COLORS[1] },
        { label: "Letter", color: TAG_COLORS[2] },
      ])
    } else if (!isOpen) {
      setColumnLabel("")
      setColumnType("text")
      setPrompt("")
      setTagOptions([
        { label: "Email", color: TAG_COLORS[0] },
        { label: "Contract", color: TAG_COLORS[1] },
        { label: "Letter", color: TAG_COLORS[2] },
      ])
    }
  }, [editingColumn, isOpen])

  const handleContinueToStep2 = () => {
    if (!prompt.trim()) {
      toast.error("Введите вопрос для колонки")
      return
    }
    setColumnLabel(suggestLabelFromPrompt(prompt))
    setColumnType("verbatim")
    setStep(2)
  }

  const handleBackToStep1 = () => {
    setStep(1)
  }

  const handleGeneratePrompt = async () => {
    if (!columnLabel.trim()) {
      toast.error("Введите название колонки для генерации промпта")
      return
    }

    setIsGenerating(true)
    try {
      const result = await tabularReviewApi.generateColumnPrompt(columnLabel, columnType)
      setPrompt(result.prompt)
      toast.success("Промпт сгенерирован")
    } catch (error: any) {
      console.error("Error generating prompt:", error)
      toast.error("Ошибка при генерации промпта: " + (error.message || "Неизвестная ошибка"))
    } finally {
      setIsGenerating(false)
    }
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

  // ——— Режим создания: два шага ———
  if (isCreate && step === 1) {
    return (
      <Modal isOpen={isOpen} onClose={onClose} title="Create column" size="sm">
        <p className="text-sm text-muted-foreground mb-4">
          Get started by asking Harvey a question.
        </p>
        <div className="space-y-4">
          <div>
            <Textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="What is the signing date of this agreement?"
              rows={4}
              className="resize-none"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={handleContinueToStep2} disabled={!prompt.trim()}>
              Continue
            </Button>
          </div>
        </div>
      </Modal>
    )
  }

  if (isCreate && step === 2) {
    return (
      <Modal isOpen={isOpen} onClose={onClose} title="Confirm column properties" size="sm">
        <p className="text-sm text-muted-foreground mb-4">
          Based on your question, Harvey has suggested the column header and type.
        </p>
        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium mb-2 block">Label</label>
            <Input
              value={columnLabel}
              onChange={(e) => setColumnLabel(e.target.value)}
              placeholder="e.g. Indemnification Clause"
            />
          </div>
          <div>
            <label className="text-sm font-medium mb-2 block">Type</label>
            <Select value={columnType} onValueChange={(v) => handleColumnTypeChange(v)}>
              <SelectTrigger
                onClick={(e) => e.stopPropagation()}
                onPointerDown={(e) => e.stopPropagation()}
              >
                <SelectValue placeholder="Select type" />
              </SelectTrigger>
              <SelectContent onPointerDownOutside={(e) => {}} onEscapeKeyDown={(e) => {}}>
                {COLUMN_TYPES.map((type) => (
                  <SelectItem key={type.value} value={type.value}>
                    <span className="flex items-center gap-2">
                      <span>{type.icon}</span>
                      <span>{type.label}</span>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {columnType === "tag" && (
            <div>
              <label className="text-sm font-medium mb-2 block">Options</label>
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
                  <Input value={newTagLabel} onChange={(e) => setNewTagLabel(e.target.value)} placeholder="New option" onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), handleAddTag())} />
                  <Button variant="outline" size="sm" onClick={handleAddTag} disabled={!newTagLabel.trim()}>+ Add</Button>
                </div>
              </div>
            </div>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={handleBackToStep1} disabled={saving}>
              Back
            </Button>
            <Button variant="outline" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={saving || !columnLabel.trim()}>
              {saving ? "Saving…" : "Add column"}
            </Button>
          </div>
        </div>
      </Modal>
    )
  }

  // ——— Режим редактирования: одна форма ———
  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Редактировать колонку" size="md">
      <div className="space-y-4">
        <div>
          <label className="text-sm font-medium mb-2 block">Название колонки</label>
          <Input value={columnLabel} onChange={(e) => setColumnLabel(e.target.value)} placeholder="Например: Loan Type, Payment Date" />
        </div>
        <div>
          <label className="text-sm font-medium mb-2 block">Format</label>
          <Select value={columnType} onValueChange={(value) => handleColumnTypeChange(value)}>
            <SelectTrigger onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
              <SelectValue placeholder="Выберите тип колонки" />
            </SelectTrigger>
            <SelectContent onPointerDownOutside={() => {}} onEscapeKeyDown={() => {}}>
              {COLUMN_TYPES.map((type) => (
                <SelectItem key={type.value} value={type.value}>
                  <span className="flex items-center gap-2"><span>{type.icon}</span><span>{type.label}</span></span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {columnType === "tag" && (
          <div>
            <label className="text-sm font-medium mb-2 block">Options</label>
            <div className="space-y-2">
              {tagOptions.map((option, index) => (
                <div key={index} className="flex items-center gap-2 p-2 border rounded">
                  <div className="w-4 h-4 rounded" style={{ backgroundColor: option.color }} />
                  <Input value={option.label} onChange={(e) => { const newOptions = [...tagOptions]; newOptions[index].label = e.target.value; setTagOptions(newOptions) }} className="flex-1" />
                  <Button variant="ghost" size="sm" onClick={() => handleRemoveTag(index)} className="text-red-500">×</Button>
                </div>
              ))}
              <div className="flex gap-2">
                <Input value={newTagLabel} onChange={(e) => setNewTagLabel(e.target.value)} placeholder="Новая опция" onKeyPress={(e) => { if (e.key === "Enter") { e.preventDefault(); handleAddTag() } }} />
                <Button variant="outline" size="sm" onClick={handleAddTag} disabled={!newTagLabel.trim()}>+ Add option</Button>
              </div>
            </div>
          </div>
        )}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium">Prompt</label>
            <Tooltip title="Сгенерировать промпт с помощью AI">
              <MUIButton size="small" variant="outlined" startIcon={isGenerating ? <CircularProgress size={16} /> : <AutoAwesomeIcon />} onClick={handleGeneratePrompt} disabled={isGenerating || !columnLabel.trim()} sx={{ textTransform: 'none' }}>
                {isGenerating ? "Генерация..." : "✨ AI Generate"}
              </MUIButton>
            </Tooltip>
          </div>
          <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Write your prompt..." rows={6} className="font-mono text-sm" />
        </div>
        <div className="flex justify-end gap-2 pt-4">
          <Button variant="outline" onClick={onClose} disabled={saving}>Отмена</Button>
          <Button onClick={handleSave} disabled={saving || !columnLabel.trim() || !prompt.trim()}>{saving ? "Сохранение..." : "Сохранить"}</Button>
        </div>
      </div>
    </Modal>
  )
}

