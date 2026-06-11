import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { FolderOpen, MessageSquare, Clock, Gavel, Upload, Trash2, Loader2 } from 'lucide-react'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import {
  fetchCourtPracticeStatus,
  startCourtPracticeUploadJob,
  buildCourtPracticeJobSseUrl,
  deleteCourtPracticeBatch,
  deleteAllCourtPractice,
  type CourtPracticeStatus,
  extractErrorMessage,
} from '../services/api'

const navItems = [
  { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
  { id: 'assistant', label: 'Ассистент', icon: MessageSquare, path: '/assistant' },
  { id: 'history', label: 'История', icon: Clock, path: '/history' },
]

const CourtPracticeManagePage = () => {
  const [status, setStatus] = useState<CourtPracticeStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [jobProgress, setJobProgress] = useState<{ percent: number; message: string } | null>(null)
  const [deletingAll, setDeletingAll] = useState(false)
  const [maxRows, setMaxRows] = useState<string>('100')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const jobStreamRef = useRef<EventSource | null>(null)

  const loadData = async () => {
    setLoading(true)
    setStatusError(null)
    try {
      const st = await fetchCourtPracticeStatus()
      setStatus(st)
    } catch (err: unknown) {
      const message = extractErrorMessage(err)
      setStatusError(message)
      toast.error(message)
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
    return () => {
      jobStreamRef.current?.close()
    }
  }, [])

  const onUploadCsv = async (list: FileList | null) => {
    if (!list || list.length === 0) return
    const file = list[0]
    if (!file.name.toLowerCase().endsWith('.csv')) {
      toast.error('Загрузите файл в формате CSV')
      return
    }
    const limit = maxRows.trim() ? parseInt(maxRows, 10) : undefined
    if (maxRows.trim() && (Number.isNaN(limit) || (limit ?? 0) < 1)) {
      toast.error('Лимит строк должен быть положительным числом')
      return
    }

    setUploading(true)
    setJobProgress({ percent: 0, message: 'Создаю задачу индексации…' })
    try {
      const start = await startCourtPracticeUploadJob(file, limit)
      const url = buildCourtPracticeJobSseUrl(start.job_id)
      jobStreamRef.current?.close()
      const es = new EventSource(url)
      jobStreamRef.current = es

      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data || '{}') as Record<string, unknown>
          const t = String(data.type || '').toLowerCase()
          if (typeof data.progress_percent === 'number') {
            setJobProgress({
              percent: data.progress_percent,
              message: String(data.message || ''),
            })
          } else if (typeof data.message === 'string' && data.message) {
            setJobProgress((prev) => ({ percent: prev?.percent ?? 0, message: data.message as string }))
          }
          if (t === 'failed') {
            toast.error(String(data.message || 'Ошибка индексации'))
            es.close()
            jobStreamRef.current = null
            setUploading(false)
          }
          if (t === 'completed') {
            toast.success(String(data.message || 'Индексация завершена'))
            es.close()
            jobStreamRef.current = null
            setUploading(false)
            setJobProgress({ percent: 100, message: String(data.message || 'Готово') })
            void loadData()
          }
        } catch {
          /* ignore parse */
        }
      }
      es.onerror = () => {
        setJobProgress((prev) => ({ percent: prev?.percent ?? 0, message: 'Переподключение к прогрессу…' }))
      }
    } catch (err: unknown) {
      toast.error(extractErrorMessage(err))
      setUploading(false)
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const onDeleteBatch = async (batchId: string) => {
    if (!window.confirm(`Удалить пакет ${batchId}?`)) return
    try {
      const res = await deleteCourtPracticeBatch(batchId)
      toast.success(`Удалено: ${res.deleted_documents} дел, ${res.deleted_chunks} фрагментов`)
      void loadData()
    } catch (err: unknown) {
      toast.error(extractErrorMessage(err))
    }
  }

  const onDeleteAll = async () => {
    if (!window.confirm('Удалить всю базу судебной практики?')) return
    setDeletingAll(true)
    try {
      const res = await deleteAllCourtPractice()
      toast.success(`Очищено: ${res.deleted_documents} дел, ${res.deleted_chunks} фрагментов`)
      void loadData()
    } catch (err: unknown) {
      toast.error(extractErrorMessage(err))
    } finally {
      setDeletingAll(false)
    }
  }

  return (
    <div className="h-screen flex overflow-hidden" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      <UnifiedSidebar navItems={navItems} title="Legal AI" />

      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-4xl mx-auto px-8 py-10">
            <div className="mb-8">
              <h1 className="text-2xl font-semibold mb-1" style={{ color: 'var(--color-text-primary)' }}>
                Судебная практика
              </h1>
              <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                Загрузка CSV с судебными актами для пилота (рекомендуется ~100 дел). Эмбеддинги: Giga EmbeddingsGigaR.
              </p>
            </div>

            {loading ? (
              <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-text-muted)' }}>
                <Loader2 className="w-4 h-4 animate-spin" />
                Загрузка…
              </div>
            ) : statusError ? (
              <div
                className="rounded-xl border p-5"
                style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
              >
                <p className="text-sm mb-3" style={{ color: 'var(--color-text-primary)' }}>
                  {statusError}
                </p>
                <button type="button" onClick={() => void loadData()} className="text-sm underline">
                  Повторить
                </button>
              </div>
            ) : !status?.is_uploader ? (
              <div
                className="rounded-xl border p-5"
                style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
              >
                <p className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                  Доступ к загрузке есть только у уполномоченных аккаунтов (см. COURT_PRACTICE_UPLOADER_EMAILS).
                </p>
              </div>
            ) : (
              <>
                {jobProgress && (
                  <div
                    className="rounded-xl border p-4 mb-4 text-sm"
                    style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
                  >
                    <div className="flex justify-between gap-3 mb-2">
                      <span>{jobProgress.message || 'Индексация…'}</span>
                      <span>{Math.round(jobProgress.percent)}%</span>
                    </div>
                    <div className="h-2 rounded bg-gray-200 overflow-hidden">
                      <div
                        className="h-2 bg-teal-600 transition-all"
                        style={{ width: `${Math.min(100, Math.max(0, jobProgress.percent))}%` }}
                      />
                    </div>
                  </div>
                )}

                <div
                  className="rounded-xl border p-4 mb-6 flex flex-wrap items-center justify-between gap-3"
                  style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
                >
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-lg flex items-center justify-center bg-teal-100">
                      <Gavel className="w-5 h-5 text-teal-700" />
                    </div>
                    <div>
                      <div className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                        Документов: {status.document_count} · фрагментов: {status.chunk_count}
                      </div>
                      <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                        В чате включите тумблер «Суд. практика»
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                      Макс. строк CSV
                      <input
                        type="number"
                        min={1}
                        className="ml-2 w-20 px-2 py-1 rounded border text-sm"
                        value={maxRows}
                        onChange={(e) => setMaxRows(e.target.value)}
                        disabled={uploading}
                      />
                    </label>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".csv,text/csv"
                      className="hidden"
                      onChange={(e) => void onUploadCsv(e.target.files)}
                    />
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={uploading || deletingAll}
                      className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm border disabled:opacity-50"
                    >
                      {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                      {uploading ? 'Индексация…' : 'Загрузить CSV'}
                    </button>
                    <button
                      type="button"
                      onClick={() => void onDeleteAll()}
                      disabled={deletingAll || uploading || status.chunk_count === 0}
                      className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm border text-red-600 disabled:opacity-50"
                    >
                      {deletingAll ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                      Очистить всё
                    </button>
                  </div>
                </div>

                <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--color-border)' }}>
                  <div className="px-4 py-3 text-sm font-medium border-b" style={{ borderColor: 'var(--color-border)' }}>
                    Пакеты загрузки ({status.batches?.length ?? 0})
                  </div>
                  {!status.batches?.length ? (
                    <p className="px-4 py-6 text-sm" style={{ color: 'var(--color-text-muted)' }}>
                      Пока нет загруженных пакетов. Загрузите CSV с колонками: текст документа, айди документа (и при
                      необходимости номер дела, суд, дата).
                    </p>
                  ) : (
                    <ul>
                      {status.batches.map((b) => (
                        <li
                          key={b.batch_id}
                          className="px-4 py-3 flex items-center justify-between gap-2 border-b last:border-b-0 text-sm"
                          style={{ borderColor: 'var(--color-border)' }}
                        >
                          <div>
                            <div className="font-mono text-xs">{b.batch_id}</div>
                            <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                              {b.documents} дел · {b.chunks} фрагментов
                              {b.created_at ? ` · ${new Date(b.created_at).toLocaleString('ru-RU')}` : ''}
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={() => void onDeleteBatch(b.batch_id)}
                            className="text-red-600 text-xs hover:underline"
                          >
                            Удалить
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div
                  className="mt-6 rounded-lg border p-4 text-xs leading-relaxed"
                  style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
                >
                  <p className="font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>
                    Формат CSV
                  </p>
                  <p>
                    Обязательные колонки: <code>текст документа</code> (или text), <code>айди документа</code> (или
                    document_id). Опционально: номер дела, суд, дата, уровень суда. Акты до 10k символов индексируются
                    одним фрагментом.
                  </p>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default CourtPracticeManagePage
