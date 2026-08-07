"use client"

import { useState, useEffect, useRef } from "react"
import Modal from "@/components/UI/Modal"
import { Button } from "@/components/UI/Button"
import { Textarea } from "@/components/UI/Textarea"
import Input from "@/components/UI/Input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/UI/Select"
import { toast } from "sonner"
import { FileUp, Loader2, Pencil, Trash2, Info } from "lucide-react"
import type { ProposedColumn, TabularColumn } from "@/services/tabularReviewApi"
import { tabularReviewApi } from "@/services/tabularReviewApi"

const COLUMN_TYPES = [
  { value: "text", label: "Текст" },
  { value: "number", label: "Число" },
  { value: "currency", label: "Валюта" },
  { value: "yes_no", label: "Да/Нет" },
  { value: "date", label: "Дата" },
  { value: "tag", label: "Тег" },
  { value: "verbatim", label: "Цитата" },
  { value: "manual_input", label: "Ручной ввод" },
]

const CHECKLIST_ACCEPT = ".txt,.md,.csv,.docx"

function getColumnTypeLabel(value: string): string {
  return COLUMN_TYPES.find((t) => t.value === value)?.label ?? value
}

export interface BulkColumnBuilderProps {
  isOpen: boolean
  onClose: () => void
  reviewId: string
  /** Вызывается после успешного добавления колонок; передаёт созданные колонки */
  onColumnsAdded: (columns: TabularColumn[]) => void
  /** Если передан — предзаполняет textarea и автоматически генерирует колонки при открытии */
  initialQuestionsText?: string
}

export function BulkColumnBuilder({
  isOpen,
  onClose,
  reviewId,
  onColumnsAdded,
  initialQuestionsText,
}: BulkColumnBuilderProps) {
  const [questionsText, setQuestionsText] = useState("")
  const [proposedColumns, setProposedColumns] = useState<ProposedColumn[]>([])
  const [generating, setGenerating] = useState(false)
  const [importing, setImporting] = useState(false)
  const [adding, setAdding] = useState(false)
  const [editIndex, setEditIndex] = useState<number | null>(null)
  const [editLabel, setEditLabel] = useState("")
  const [editType, setEditType] = useState("text")
  const [editPrompt, setEditPrompt] = useState("")
  const [editClassifyOptions, setEditClassifyOptions] = useState<string[]>(["Да", "Нет"])
  const [importedFileName, setImportedFileName] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Auto-fill and auto-generate when opened with an initial prompt from inline form
  const didAutoGenerate = useRef(false)
  useEffect(() => {
    if (isOpen && initialQuestionsText && !didAutoGenerate.current) {
      didAutoGenerate.current = true
      setQuestionsText(initialQuestionsText)
      setGenerating(true)
      tabularReviewApi.generateColumnsFromQuestions(reviewId, initialQuestionsText.trim())
        .then(({ columns }) => {
          setProposedColumns(columns)
          if (columns.length === 0) toast.info("Ни одной колонки не сгенерировано. Попробуйте переформулировать.")
        })
        .catch((e: unknown) => { toast.error(e instanceof Error ? e.message : "Ошибка генерации") })
        .finally(() => setGenerating(false))
    }
    if (!isOpen) {
      didAutoGenerate.current = false
    }
  }, [isOpen, initialQuestionsText, reviewId])

  const handleGenerate = async () => {
    const text = questionsText.trim()
    if (!text) {
      toast.error("Введите вопросы для генерации столбцов")
      return
    }
    setGenerating(true)
    try {
      const { columns } = await tabularReviewApi.generateColumnsFromQuestions(reviewId, text)
      setProposedColumns(columns)
      if (columns.length === 0) {
        toast.info("Ни одной колонки не сгенерировано. Попробуйте переформулировать вопросы.")
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Ошибка генерации"
      toast.error(msg)
    } finally {
      setGenerating(false)
    }
  }

  const handleChecklistFile = async (file: File | null) => {
    if (!file) return
    setImporting(true)
    try {
      const result = await tabularReviewApi.importChecklistFile(reviewId, file)
      setQuestionsText(result.questions_text)
      setProposedColumns(result.columns)
      setImportedFileName(result.filename)
      toast.success(
        `Импортировано пунктов: ${result.item_count}` +
          (result.columns.length ? `, колонок: ${result.columns.length}` : ""),
      )
      if (result.columns.length === 0) {
        toast.info("Пункты распознаны, но колонки не сгенерированы. Нажмите «Сгенерировать столбцы».")
      }
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Не удалось импортировать чек-лист")
    } finally {
      setImporting(false)
      if (fileInputRef.current) fileInputRef.current.value = ""
    }
  }

  const handleRemove = (index: number) => {
    setProposedColumns((prev) => prev.filter((_, i) => i !== index))
    if (editIndex === index) setEditIndex(null)
    else if (editIndex != null && editIndex > index) setEditIndex(editIndex - 1)
  }

  const startEdit = (index: number) => {
    const row = proposedColumns[index]
    if (!row) return
    setEditIndex(index)
    setEditLabel(row.column_label)
    setEditType(row.column_type)
    setEditPrompt(row.prompt)
    const opts = row.column_config?.options?.map((o) => o.label)
    setEditClassifyOptions(opts?.length ? opts : ["Да", "Нет"])
  }

  const saveEdit = () => {
    if (editIndex == null) return
    const columnConfig =
      editType === "yes_no" || editType === "tag"
        ? {
            options: editClassifyOptions.map((label, i) => ({
              label,
              color: ["#10B981", "#6B7280", "#3B82F6", "#F59E0B"][i % 4],
            })),
            allow_custom: false,
          }
        : undefined
    setProposedColumns((prev) =>
      prev.map((c, i) =>
        i === editIndex
          ? {
              ...c,
              column_label: editLabel,
              column_type: editType,
              prompt: editPrompt,
              column_config: columnConfig,
            }
          : c
      )
    )
    setEditIndex(null)
  }

  const removeClassifyOption = (optIndex: number) => {
    setEditClassifyOptions((prev) => prev.filter((_, i) => i !== optIndex))
  }

  const cancelEdit = () => {
    setEditIndex(null)
  }

  const handleAddColumns = async () => {
    if (proposedColumns.length === 0) {
      toast.error("Нет колонок для добавления. Сначала нажмите «Сгенерировать столбцы».")
      return
    }
    setAdding(true)
    try {
      const { columns: created } = await tabularReviewApi.addColumnsBulk(reviewId, proposedColumns)
      toast.success(`Добавлено колонок: ${proposedColumns.length}`)
      onColumnsAdded(created)
      onClose()
      setQuestionsText("")
      setProposedColumns([])
      setImportedFileName(null)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Ошибка добавления колонок"
      toast.error(msg)
    } finally {
      setAdding(false)
    }
  }

  const handleClose = () => {
    setEditIndex(null)
    setQuestionsText("")
    setProposedColumns([])
    setImportedFileName(null)
    onClose()
  }

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Импорт чек-листа" size="lg">
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Загрузите файл с вопросами due diligence (.txt, .md, .csv, .docx) или вставьте список вручную.
          ИИ превратит пункты в колонки таблицы — проверьте и нажмите «Добавить столбцы».
        </p>

        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept={CHECKLIST_ACCEPT}
            className="hidden"
            onChange={(e) => void handleChecklistFile(e.target.files?.[0] ?? null)}
          />
          <Button
            type="button"
            variant="outline"
            disabled={generating || importing || adding}
            onClick={() => fileInputRef.current?.click()}
            className="border-border bg-background"
          >
            <FileUp className="h-4 w-4 mr-1.5" aria-hidden />
            {importing ? "Импорт…" : "Импорт чек-листа"}
          </Button>
          {importedFileName && (
            <span className="text-xs text-muted-foreground truncate max-w-[240px]" title={importedFileName}>
              {importedFileName}
            </span>
          )}
        </div>

        <Textarea
          value={questionsText}
          onChange={(e) => setQuestionsText(e.target.value)}
          placeholder="Есть ли положение о непереманивании? Кто стороны соглашения? Какая дата подписания? Каков срок действия соглашения?"
          rows={6}
          className="resize-none w-full rounded-lg border border-input bg-background"
          disabled={generating || importing}
        />
        <div className="flex items-center justify-between gap-4">
          <p className="text-sm text-muted-foreground flex-1 min-w-0">
            Формулируйте конкретные вопросы по тексту файла (даты, стороны, тип документа, суммы).
          </p>
          <button
            type="button"
            onClick={() => void handleGenerate()}
            disabled={!questionsText.trim() || generating || importing}
            aria-label="Сгенерировать столбцы"
            className="inline-flex h-10 min-w-[12.5rem] shrink-0 items-center justify-center gap-2 rounded-md bg-[#374151] px-4 text-sm font-medium text-white transition-colors hover:bg-[#4B5563] focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 disabled:cursor-not-allowed disabled:bg-[#9CA3AF] disabled:hover:bg-[#9CA3AF]"
          >
            {generating ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                Генерация…
              </>
            ) : (
              "Сгенерировать столбцы"
            )}
          </button>
        </div>

        {proposedColumns.length > 0 && (
          <div className="border border-border rounded-lg overflow-hidden bg-white">
            <div className="overflow-x-auto max-h-[320px] overflow-y-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr>
                    <th className="sticky top-0 z-10 bg-white text-left p-3 font-medium w-[140px] border-b border-border shadow-[0_1px_0_0_rgba(0,0,0,0.06)]">
                      Тип
                    </th>
                    <th className="sticky top-0 z-10 bg-white text-left p-3 font-medium border-b border-border shadow-[0_1px_0_0_rgba(0,0,0,0.06)]">
                      Название
                    </th>
                    <th className="sticky top-0 z-10 bg-white text-left p-3 font-medium min-w-[220px] border-b border-border shadow-[0_1px_0_0_rgba(0,0,0,0.06)]">
                      Запрос
                    </th>
                    <th
                      className="sticky top-0 z-10 bg-white w-[72px] border-b border-border shadow-[0_1px_0_0_rgba(0,0,0,0.06)]"
                      aria-label="Действия"
                    />
                  </tr>
                </thead>
                <tbody>
                  {proposedColumns.map((col, index) => (
                    <tr key={index} className="border-t border-border bg-background">
                      {editIndex === index ? (
                        <>
                          <td className="p-3 align-top">
                            <Select value={editType} onValueChange={setEditType}>
                              <SelectTrigger className="h-9 w-full rounded-lg border border-input bg-background">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {COLUMN_TYPES.map((t) => (
                                  <SelectItem key={t.value} value={t.value}>
                                    {t.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </td>
                          <td className="p-3 align-top">
                            <Input
                              value={editLabel}
                              onChange={(e) => setEditLabel(e.target.value)}
                              className="h-9 w-full rounded-lg border border-input"
                            />
                          </td>
                          <td className="p-3 align-top">
                            <div className="space-y-2">
                              <Textarea
                                value={editPrompt}
                                onChange={(e) => setEditPrompt(e.target.value)}
                                rows={3}
                                className="resize-none w-full rounded-lg border border-input text-sm"
                              />
                              {(editType === "yes_no" || editType === "tag") && (
                                <div className="flex flex-wrap items-center gap-2 pt-1">
                                  <span className="text-xs text-muted-foreground flex items-center gap-1">
                                    Параметры классификации
                                    <Info className="size-3.5 text-muted-foreground" aria-hidden />
                                  </span>
                                  {editClassifyOptions.map((opt, optIndex) => (
                                    <span
                                      key={optIndex}
                                      className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-muted text-sm"
                                    >
                                      {opt}
                                      <button
                                        type="button"
                                        onClick={() => removeClassifyOption(optIndex)}
                                        className="p-0.5 rounded hover:bg-muted-foreground/20"
                                        aria-label={`Удалить ${opt}`}
                                      >
                                        <span className="text-xs leading-none">×</span>
                                      </button>
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                          </td>
                          <td className="p-3 align-top">
                            <div className="flex gap-2">
                              <Button
                                size="sm"
                                onClick={saveEdit}
                                className="bg-[#374151] hover:bg-[#4B5563] text-white border-0"
                              >
                                Сохранить
                              </Button>
                              <Button size="sm" variant="outline" onClick={cancelEdit}>
                                Отмена
                              </Button>
                            </div>
                          </td>
                        </>
                      ) : (
                        <>
                          <td className="p-3">{getColumnTypeLabel(col.column_type)}</td>
                          <td className="p-3">{col.column_label}</td>
                          <td className="p-3 text-muted-foreground max-w-[300px] truncate" title={col.prompt}>
                            {col.prompt}
                          </td>
                          <td className="p-3">
                            <div className="flex gap-1">
                              <button
                                type="button"
                                onClick={() => startEdit(index)}
                                className="p-2 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground"
                                aria-label="Редактировать"
                              >
                                <Pencil className="h-4 w-4" />
                              </button>
                              <button
                                type="button"
                                onClick={() => handleRemove(index)}
                                className="p-2 rounded-md hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
                                aria-label="Удалить"
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            </div>
                          </td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div className="flex justify-between gap-2 pt-4 border-t border-border">
          <Button
            variant="outline"
            onClick={handleClose}
            disabled={adding}
            className="border-border bg-background text-muted-foreground hover:bg-muted"
          >
            Отмена
          </Button>
          <button
            type="button"
            onClick={() => void handleAddColumns()}
            disabled={proposedColumns.length === 0 || adding}
            aria-label="Добавить столбцы"
            className="inline-flex h-10 min-w-[10rem] items-center justify-center gap-2 rounded-md bg-[#374151] px-4 text-sm font-medium text-white transition-colors hover:bg-[#4B5563] focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 disabled:cursor-not-allowed disabled:bg-[#9CA3AF] disabled:hover:bg-[#9CA3AF]"
          >
            {adding ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                Добавление…
              </>
            ) : (
              "Добавить столбцы"
            )}
          </button>
        </div>
      </div>
    </Modal>
  )
}
