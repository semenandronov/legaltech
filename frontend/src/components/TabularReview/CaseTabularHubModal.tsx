import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  X,
  Table,
  Plus,
  LayoutTemplate,
  ChevronRight,
  ChevronLeft,
  Loader2,
  Search,
  Trash2,
  Scale,
} from 'lucide-react'
import { toast } from 'sonner'
import { tabularReviewApi } from '@/services/tabularReviewApi'
import {
  applyTabularTemplateToReview,
  fetchDdTemplateCatalog,
  type TabularTemplateCatalogItem,
} from '@/utils/tabularTemplateApply'

type HubStep = 'list' | 'templates' | 'files'

export interface CaseTabularReviewSummary {
  id: string
  name: string
  status: string
  updated_at?: string
  created_at?: string
  description?: string
}

interface CaseFileOption {
  id: string
  filename: string
}

interface CaseTabularHubModalProps {
  open: boolean
  onClose: () => void
  caseId: string
  files: CaseFileOption[]
  reviews: CaseTabularReviewSummary[]
  loadingReviews?: boolean
  onReviewOpen: (reviewId: string) => void
  onReviewsChanged?: () => void
}

export function CaseTabularHubModal({
  open,
  onClose,
  caseId,
  files,
  reviews,
  loadingReviews = false,
  onReviewOpen,
  onReviewsChanged,
}: CaseTabularHubModalProps) {
  const [step, setStep] = useState<HubStep>('list')
  const [templates, setTemplates] = useState<TabularTemplateCatalogItem[]>([])
  const [loadingTemplates, setLoadingTemplates] = useState(false)
  const [selectedTemplate, setSelectedTemplate] = useState<TabularTemplateCatalogItem | null>(null)
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set())
  const [fileSearch, setFileSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const [tableName, setTableName] = useState('')

  const resetFlow = useCallback(() => {
    setStep('list')
    setSelectedTemplate(null)
    setSelectedFileIds(new Set())
    setFileSearch('')
    setTableName('')
  }, [])

  useEffect(() => {
    if (!open) {
      resetFlow()
      return
    }
    setLoadingTemplates(true)
    fetchDdTemplateCatalog()
      .then(setTemplates)
      .catch(() => setTemplates([]))
      .finally(() => setLoadingTemplates(false))
  }, [open, resetFlow])

  const filteredFiles = useMemo(() => {
    const q = fileSearch.trim().toLowerCase()
    if (!q) return files
    return files.filter((f) => f.filename.toLowerCase().includes(q))
  }, [files, fileSearch])

  const allFilesSelected =
    filteredFiles.length > 0 && filteredFiles.every((f) => selectedFileIds.has(f.id))

  const toggleAllFiles = () => {
    if (allFilesSelected) {
      setSelectedFileIds(new Set())
    } else {
      setSelectedFileIds(new Set(filteredFiles.map((f) => f.id)))
    }
  }

  const startBlankCreate = () => {
    setSelectedTemplate(null)
    setTableName('Новая таблица')
    setSelectedFileIds(new Set(files.map((f) => f.id)))
    setStep('files')
  }

  const startTemplateCreate = (template: TabularTemplateCatalogItem) => {
    setSelectedTemplate(template)
    setTableName(template.name)
    setSelectedFileIds(new Set(files.map((f) => f.id)))
    setStep('files')
  }

  const handleDeleteReview = async (reviewId: string, reviewName: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(`Удалить таблицу «${reviewName}»?`)) return
    try {
      await tabularReviewApi.deleteReview(reviewId)
      toast.success('Таблица удалена')
      onReviewsChanged?.()
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Не удалось удалить'
      toast.error(message)
    }
  }

  const handleCreate = async () => {
    if (selectedFileIds.size === 0) {
      toast.error('Выберите хотя бы один документ')
      return
    }
    const name = tableName.trim() || 'Новая таблица'
    setCreating(true)
    try {
      const review = await tabularReviewApi.createReview(
        caseId,
        name,
        selectedTemplate?.description,
        [...selectedFileIds],
      )
      if (selectedTemplate) {
        await applyTabularTemplateToReview(review.id, selectedTemplate.id, selectedTemplate.source)
      }
      toast.success(
        selectedTemplate
          ? `Таблица создана по шаблону «${selectedTemplate.name}»`
          : 'Таблица создана',
      )
      onClose()
      onReviewOpen(review.id)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Не удалось создать таблицу'
      toast.error(message)
    } finally {
      setCreating(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-label="Закрыть"
      />
      <div
        className="relative w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden rounded-2xl shadow-xl"
        style={{
          backgroundColor: 'var(--color-bg-elevated)',
          border: '1px solid var(--color-border)',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-4 border-b shrink-0"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div className="flex items-center gap-2 min-w-0">
            {step !== 'list' && (
              <button
                type="button"
                onClick={() => setStep(step === 'files' ? (selectedTemplate ? 'templates' : 'list') : 'list')}
                className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)]"
                style={{ color: 'var(--color-text-muted)' }}
                aria-label="Назад"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
            )}
            <div className="min-w-0">
              <h2 className="text-base font-semibold truncate" style={{ color: 'var(--color-text-primary)' }}>
                {step === 'list' && 'Таблицы по делу'}
                {step === 'templates' && 'Шаблоны due diligence'}
                {step === 'files' && (selectedTemplate ? 'Документы для шаблона' : 'Новая таблица')}
              </h2>
              {step === 'list' && (
                <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                  Одинаковые вопросы ко всем выбранным документам
                </p>
              )}
              {step === 'templates' && (
                <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                  Три рабочих пресета для арбитражной практики
                </p>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)] shrink-0"
            style={{ color: 'var(--color-text-muted)' }}
            aria-label="Закрыть"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {step === 'list' && (
            <>
              {loadingReviews ? (
                <div className="flex justify-center py-12">
                  <Loader2 className="w-6 h-6 animate-spin" style={{ color: 'var(--color-text-muted)' }} />
                </div>
              ) : reviews.length === 0 ? (
                <div className="text-center py-6">
                  <div
                    className="w-11 h-11 rounded-xl mx-auto mb-4 flex items-center justify-center"
                    style={{ backgroundColor: 'var(--color-bg-primary)', border: '1px solid var(--color-border)' }}
                  >
                    <Table className="w-5 h-5" style={{ color: 'var(--color-text-muted)' }} />
                  </div>
                  <p className="text-sm font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>
                    Таблиц в этом деле пока нет
                  </p>
                  <p className="text-sm mb-6 max-w-sm mx-auto leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
                    Возьмите шаблон DD: коммерческая аренда, поставка или услуги/подряд —
                    либо создайте пустую таблицу.
                  </p>
                  <div className="flex flex-col sm:flex-row gap-2.5 justify-center">
                    <button
                      type="button"
                      onClick={() => setStep('templates')}
                      className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium"
                      style={{
                        backgroundColor: 'var(--color-accent)',
                        color: '#fff',
                      }}
                    >
                      <LayoutTemplate className="w-4 h-4" />
                      Выбрать шаблон
                    </button>
                    <button
                      type="button"
                      onClick={startBlankCreate}
                      disabled={files.length === 0}
                      className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium border disabled:opacity-40"
                      style={{
                        borderColor: 'var(--color-border)',
                        color: 'var(--color-text-primary)',
                        backgroundColor: 'var(--color-bg-primary)',
                      }}
                    >
                      <Plus className="w-4 h-4" />
                      Пустая таблица
                    </button>
                  </div>
                  {files.length === 0 && (
                    <p className="text-xs mt-4" style={{ color: 'var(--color-text-muted)' }}>
                      Сначала загрузите документы в дело
                    </p>
                  )}
                </div>
              ) : (
                <>
                  <div className="flex gap-2 mb-4">
                    <button
                      type="button"
                      onClick={() => setStep('templates')}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium"
                      style={{
                        backgroundColor: 'var(--color-accent)',
                        color: '#fff',
                      }}
                    >
                      <LayoutTemplate className="w-3.5 h-3.5" />
                      Шаблоны
                    </button>
                    <button
                      type="button"
                      onClick={startBlankCreate}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border"
                      style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                    >
                      <Plus className="w-3.5 h-3.5" />
                      Пустая таблица
                    </button>
                  </div>
                  <ul className="space-y-2">
                    {reviews.map((review) => (
                      <li key={review.id}>
                        <div
                          className="w-full flex items-center gap-3 px-3.5 py-3 rounded-xl border hover:bg-[var(--color-bg-hover)] transition-colors group"
                          style={{ borderColor: 'var(--color-border)' }}
                        >
                          <button
                            type="button"
                            onClick={() => {
                              onClose()
                              onReviewOpen(review.id)
                            }}
                            className="flex flex-1 items-center gap-3 min-w-0 text-left"
                          >
                            <Table className="w-4 h-4 shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium truncate" style={{ color: 'var(--color-text-primary)' }}>
                                {review.name}
                              </p>
                              {review.updated_at && (
                                <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                                  Обновлено: {new Date(review.updated_at).toLocaleDateString('ru-RU')}
                                </p>
                              )}
                            </div>
                            <ChevronRight className="w-4 h-4 shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => handleDeleteReview(review.id, review.name, e)}
                            className="p-1.5 rounded-lg opacity-0 group-hover:opacity-100 hover:bg-[var(--color-bg-hover)] shrink-0"
                            style={{ color: 'var(--color-text-muted)' }}
                            title="Удалить"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}

          {step === 'templates' && (
            <>
              <p className="text-sm mb-4 leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
                Выберите сценарий — в таблицу добавятся готовые колонки-вопросы. Заполните их по однотипным
                документам, затем сверьте ответы по подсветке в оригинале.
              </p>
              {loadingTemplates ? (
                <div className="flex justify-center py-10">
                  <Loader2 className="w-6 h-6 animate-spin" style={{ color: 'var(--color-text-muted)' }} />
                </div>
              ) : (
                <ul className="space-y-2.5">
                  {templates.map((template) => (
                    <li key={template.id}>
                      <button
                        type="button"
                        onClick={() => startTemplateCreate(template)}
                        className="w-full text-left rounded-xl border p-4 transition-colors hover:bg-[var(--color-bg-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
                        style={{
                          borderColor: 'var(--color-border)',
                          backgroundColor: 'var(--color-bg-primary)',
                        }}
                      >
                        <div className="flex items-start gap-3">
                          <div
                            className="mt-0.5 w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                            style={{
                              backgroundColor: 'color-mix(in srgb, var(--color-accent) 12%, transparent)',
                              color: 'var(--color-accent)',
                            }}
                          >
                            <Scale className="w-4 h-4" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-start justify-between gap-2">
                              <div className="min-w-0">
                                <p className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                                  {template.name}
                                </p>
                                {template.legalBasis && (
                                  <span
                                    className="inline-block mt-1.5 text-[11px] font-medium px-2 py-0.5 rounded-md"
                                    style={{
                                      backgroundColor: 'color-mix(in srgb, var(--color-accent) 10%, transparent)',
                                      color: 'var(--color-accent)',
                                    }}
                                  >
                                    {template.legalBasis}
                                  </span>
                                )}
                              </div>
                              <ChevronRight
                                className="w-4 h-4 shrink-0 mt-1"
                                style={{ color: 'var(--color-text-muted)' }}
                              />
                            </div>
                            {template.description && (
                              <p className="text-xs mt-2 leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
                                {template.description}
                              </p>
                            )}
                            {template.documentHint && (
                              <p className="text-xs mt-1.5" style={{ color: 'var(--color-text-muted)' }}>
                                Документы: {template.documentHint}
                              </p>
                            )}
                            {template.columnLabels && template.columnLabels.length > 0 && (
                              <div className="flex flex-wrap gap-1.5 mt-3">
                                {template.columnLabels.map((label) => (
                                  <span
                                    key={label}
                                    className="text-[11px] px-2 py-0.5 rounded-md border"
                                    style={{
                                      borderColor: 'var(--color-border)',
                                      color: 'var(--color-text-secondary, var(--color-text-muted))',
                                      backgroundColor: 'var(--color-bg-elevated)',
                                    }}
                                  >
                                    {label}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}

          {step === 'files' && (
            <>
              <label className="block mb-4">
                <span className="text-xs font-medium mb-1.5 block" style={{ color: 'var(--color-text-muted)' }}>
                  Название таблицы
                </span>
                <input
                  type="text"
                  value={tableName}
                  onChange={(e) => setTableName(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border text-sm outline-none focus:border-[var(--color-accent)]"
                  style={{
                    borderColor: 'var(--color-border)',
                    backgroundColor: 'var(--color-bg-primary)',
                    color: 'var(--color-text-primary)',
                  }}
                  placeholder="Например: DD аренда — договоры 2022–2024"
                />
              </label>
              {selectedTemplate && (
                <div
                  className="text-xs mb-3 px-3 py-2.5 rounded-lg border"
                  style={{
                    borderColor: 'var(--color-border)',
                    backgroundColor: 'var(--color-bg-primary)',
                    color: 'var(--color-text-muted)',
                  }}
                >
                  <span style={{ color: 'var(--color-text-primary)', fontWeight: 600 }}>
                    {selectedTemplate.name}
                  </span>
                  {selectedTemplate.legalBasis ? ` · ${selectedTemplate.legalBasis}` : ''}
                  {' — '}
                  {selectedTemplate.columnsCount} колонки
                </div>
              )}
              <div
                className="flex items-center gap-2 px-3 py-2 rounded-lg border mb-3"
                style={{ borderColor: 'var(--color-border)' }}
              >
                <Search className="w-4 h-4 shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                <input
                  type="search"
                  value={fileSearch}
                  onChange={(e) => setFileSearch(e.target.value)}
                  placeholder="Поиск по файлам…"
                  className="flex-1 bg-transparent text-sm outline-none"
                  style={{ color: 'var(--color-text-primary)' }}
                />
              </div>
              <button
                type="button"
                onClick={toggleAllFiles}
                className="text-xs mb-2 hover:underline"
                style={{ color: 'var(--color-accent)' }}
              >
                {allFilesSelected ? 'Снять выделение' : 'Выбрать все'}
              </button>
              <ul
                className="max-h-52 overflow-y-auto rounded-lg border divide-y"
                style={{ borderColor: 'var(--color-border)' }}
              >
                {filteredFiles.map((file) => (
                  <li key={file.id}>
                    <label className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-[var(--color-bg-hover)]">
                      <input
                        type="checkbox"
                        checked={selectedFileIds.has(file.id)}
                        onChange={() => {
                          setSelectedFileIds((prev) => {
                            const next = new Set(prev)
                            if (next.has(file.id)) next.delete(file.id)
                            else next.add(file.id)
                            return next
                          })
                        }}
                        className="rounded"
                      />
                      <span className="text-sm truncate" style={{ color: 'var(--color-text-primary)' }}>
                        {file.filename}
                      </span>
                    </label>
                  </li>
                ))}
                {filteredFiles.length === 0 && (
                  <li className="px-3 py-6 text-center text-sm" style={{ color: 'var(--color-text-muted)' }}>
                    Файлы не найдены
                  </li>
                )}
              </ul>
            </>
          )}
        </div>

        {/* Footer */}
        {step === 'files' && (
          <div
            className="flex items-center justify-between px-5 py-3.5 border-t shrink-0"
            style={{ borderColor: 'var(--color-border)' }}
          >
            <span className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
              {selectedFileIds.size > 0
                ? `${selectedFileIds.size} файл(ов)`
                : 'Выберите документы'}
            </span>
            <button
              type="button"
              onClick={handleCreate}
              disabled={creating || selectedFileIds.size === 0}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-40"
              style={{
                backgroundColor: 'var(--color-accent)',
                color: '#fff',
              }}
            >
              {creating && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Создать и открыть
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
