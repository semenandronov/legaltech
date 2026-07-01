import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { FileText, Upload, Trash2, Loader2 } from 'lucide-react'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { buildMainNavItems } from '../lib/mainNavItems'
import {
  fetchAdminDraftTemplates,
  uploadAdminDraftTemplate,
  deleteAdminDraftTemplate,
  type AdminDraftTemplateRow,
  extractErrorMessage,
} from '../services/api'

const DraftTemplatesAdminPage = () => {
  const [templates, setTemplates] = useState<AdminDraftTemplateRow[]>([])
  const [loading, setLoading] = useState(true)
  const [listLoading, setListLoading] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadData = async (initial = false) => {
    if (initial) {
      setLoading(true)
      setStatusError(null)
    } else {
      setListLoading(true)
    }
    try {
      const response = await fetchAdminDraftTemplates()
      setTemplates(response.templates || [])
    } catch (err: unknown) {
      const message = extractErrorMessage(err)
      if (initial) {
        setStatusError(message)
        toast.error(message)
      } else {
        toast.error(`Список шаблонов: ${message}`)
      }
      if (initial) setTemplates([])
    } finally {
      if (initial) setLoading(false)
      else setListLoading(false)
    }
  }

  useEffect(() => {
    void loadData(true)
  }, [])

  const onUpload = async (list: FileList | null) => {
    if (!list || list.length === 0) return
    const file = list[0]
    const t = title.trim() || file.name.replace(/\.[^/.]+$/, '')
    if (!t) {
      toast.error('Укажите название шаблона')
      return
    }
    setUploading(true)
    try {
      await uploadAdminDraftTemplate(file, t, description.trim())
      toast.success('Шаблон сохранён и доступен в режиме Draft')
      setTitle('')
      setDescription('')
      await loadData(false)
    } catch (err: unknown) {
      toast.error(extractErrorMessage(err))
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const onDelete = async (id: string, label: string) => {
    if (!window.confirm(`Удалить шаблон «${label}»?`)) return
    setDeletingId(id)
    try {
      await deleteAdminDraftTemplate(id)
      toast.success('Шаблон удалён')
      await loadData(false)
    } catch (err: unknown) {
      toast.error(extractErrorMessage(err))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="h-screen flex overflow-hidden" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      <UnifiedSidebar navItems={buildMainNavItems()} title="Legal AI" />

      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-4xl mx-auto px-8 py-10">
            <div className="mb-8">
              <h1 className="text-2xl font-semibold mb-1" style={{ color: 'var(--color-text-primary)' }}>
                Шаблоны Draft
              </h1>
              <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                Загрузка файла → конвертация в HTML на сервере → публичный выбор в чате (дело) и автоподбор LLM
              </p>
              <p className="text-xs mt-2" style={{ color: 'var(--color-text-muted)' }}>
                URL этой страницы: <span className="font-mono">/admin/draft-templates</span>
              </p>
            </div>

            {loading ? (
              <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-text-muted)' }}>
                <Loader2 className="w-4 h-4 animate-spin" />
                Загрузка данных…
              </div>
            ) : statusError ? (
              <div
                className="rounded-xl border p-5"
                style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
              >
                <p className="text-sm mb-3" style={{ color: 'var(--color-text-primary)' }}>
                  {statusError}
                </p>
                <button
                  type="button"
                  onClick={() => void loadData(true)}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm border"
                  style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                >
                  Повторить
                </button>
              </div>
            ) : (
              <>
                <div
                  className="rounded-xl border p-4 mb-6 space-y-4"
                  style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
                >
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="block text-sm">
                      <span style={{ color: 'var(--color-text-muted)' }}>Название (для списка в чате)</span>
                      <input
                        type="text"
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
                        style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                        placeholder="Например: Претензия по договору поставки"
                      />
                    </label>
                    <label className="block text-sm sm:col-span-2">
                      <span style={{ color: 'var(--color-text-muted)' }}>Краткое описание (для автоподбора)</span>
                      <input
                        type="text"
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
                        style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                        placeholder="Когда использовать этот шаблон"
                      />
                    </label>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".pdf,.docx,.doc,.txt,.html,.htm,.rtf"
                      className="hidden"
                      onChange={(e) => void onUpload(e.target.files)}
                    />
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={uploading}
                      className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm border disabled:opacity-50"
                      style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                    >
                      {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                      {uploading ? 'Загрузка…' : 'Выбрать файл и сохранить'}
                    </button>
                  </div>
                </div>

                <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--color-border)' }}>
                  <div
                    className="px-4 py-3 text-sm font-medium border-b flex items-center gap-2"
                    style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                  >
                    <FileText className="w-4 h-4" />
                    Загруженные шаблоны ({templates.length})
                  </div>

                  {listLoading ? (
                    <div className="px-4 py-5 text-sm flex items-center gap-2" style={{ color: 'var(--color-text-muted)' }}>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Загрузка списка…
                    </div>
                  ) : templates.length === 0 ? (
                    <div className="px-4 py-5 text-sm" style={{ color: 'var(--color-text-muted)' }}>
                      Пока нет загруженных шаблонов.
                    </div>
                  ) : (
                    <div className="divide-y" style={{ borderColor: 'var(--color-border)' }}>
                      {templates.map((row) => (
                        <div key={row.id} className="px-4 py-3 flex items-start gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                              {row.title}
                            </div>
                            {row.description ? (
                              <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                                {row.description}
                              </div>
                            ) : null}
                            <div className="text-xs mt-1 font-mono truncate" style={{ color: 'var(--color-text-muted)' }}>
                              id: {row.id} · HTML: {row.content_length} симв.
                              {row.created_at ? ` · ${row.created_at}` : ''}
                            </div>
                          </div>
                          <button
                            type="button"
                            disabled={deletingId === row.id || uploading}
                            onClick={() => void onDelete(row.id, row.title)}
                            className="p-2 rounded-lg hover:bg-red-50 disabled:opacity-50 shrink-0"
                            style={{ color: '#dc2626' }}
                            aria-label={`Удалить ${row.title}`}
                          >
                            {deletingId === row.id ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <Trash2 className="w-4 h-4" />
                            )}
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default DraftTemplatesAdminPage
