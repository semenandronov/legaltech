import { useState } from "react"
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
  }) => Promise<void>
}

const COLUMN_TYPES = [
  { value: "text", label: "Text (свободный текст)" },
  { value: "date", label: "Date (дата)" },
  { value: "currency", label: "Currency (валюта)" },
  { value: "number", label: "Number (число)" },
  { value: "yes_no", label: "Yes/No (да/нет)" },
  { value: "tags", label: "Tags (теги)" },
  { value: "verbatim", label: "Verbatim (точная цитата)" },
]

export function ColumnBuilder({ isOpen, onClose, onSave }: ColumnBuilderProps) {
  const [columnLabel, setColumnLabel] = useState("")
  const [columnType, setColumnType] = useState("text")
  const [prompt, setPrompt] = useState("")
  const [saving, setSaving] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)

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

  const handleSave = async () => {
    if (!columnLabel.trim() || !prompt.trim()) {
      return
    }

    setSaving(true)
    try {
      await onSave({
        column_label: columnLabel,
        column_type: columnType,
        prompt: prompt,
      })
      // Reset form
      setColumnLabel("")
      setColumnType("text")
      setPrompt("")
      onClose()
    } catch (error) {
      console.error("Error saving column:", error)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Добавить колонку" size="md">
      <div className="space-y-4">
        <div>
          <label className="text-sm font-medium mb-2 block">
            Название колонки
          </label>
          <Input
            value={columnLabel}
            onChange={(e) => setColumnLabel(e.target.value)}
            placeholder="Например: Loan Type, Payment Date"
          />
        </div>

        <div>
          <label className="text-sm font-medium mb-2 block">
            Тип данных
          </label>
          <Select value={columnType} onValueChange={setColumnType}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {COLUMN_TYPES.map((type) => (
                <SelectItem key={type.value} value={type.value}>
                  {type.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium">
            Вопрос/Prompt для AI
          </label>
            <Tooltip title="Сгенерировать промпт с помощью AI">
              <MUIButton
                size="small"
                variant="outlined"
                startIcon={isGenerating ? <CircularProgress size={16} /> : <AutoAwesomeIcon />}
                onClick={handleGeneratePrompt}
                disabled={isGenerating || !columnLabel.trim()}
                sx={{ textTransform: 'none' }}
              >
                {isGenerating ? "Генерация..." : "AI Generate"}
              </MUIButton>
            </Tooltip>
          </div>
          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Например: What is the loan type? или Extract the payment due date"
            rows={4}
          />
          <p className="text-xs text-muted-foreground mt-1">
            Четко опишите, какую информацию нужно извлечь из документов
          </p>
        </div>

        <div className="flex justify-end gap-2 pt-4">
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Отмена
          </Button>
          <Button onClick={handleSave} disabled={saving || !columnLabel.trim() || !prompt.trim()}>
            {saving ? "Сохранение..." : "Сохранить"}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

