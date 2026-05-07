import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { FolderOpen, MessageSquare, Clock, Scale, Upload, Trash2, Loader2, Workflow } from 'lucide-react'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import {
  fetchLegalCorpusStatus,
  fetchLegalCorpusFiles,
  startLegalCorpusUploadJob,
  buildLegalCorpusJobSseUrl,
  deleteLegalCorpusFile,
  deleteAllLegalCorpusFiles,
  type LegalCorpusStatus,
  type LegalCorpusFileRow,
  extractErrorMessage,
} from '../services/api'

const navItems = [
  { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
  { id: 'assistant', label: 'Ассистент', icon: MessageSquare, path: '/assistant' },
  { id: 'workflows', label: 'Workflows', icon: Workflow, path: '/workflows' },
  { id: 'history', label: 'История', icon: Clock, path: '/history' },
]

const LegalCorpusManagePage = () => {
  const [status, setStatus] = useState<LegalCorpusStatus | null>(null)
  const [files, setFiles] = useState<LegalCorpusFileRow[]>([])
  const [loading, setLoading] = useState(true)
  const [filesLoading, setFilesLoading] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [jobProgress, setJobProgress] = useState<{ percent: number; message: string } | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [deletingAll, setDeletingAll] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const jobStreamRef = useRef<EventSource | null>(null)

  const loadData = async () => {
    setLoading(true)
    setStatusError(null)
    try {
      const st = await fetchLegalCorpusStatus()
      setStatus(st)
      setLoading(false)
      if (st.is_uploader) {
        setFilesLoading(true)
        try {
          const response = await fetchLegalCorpusFiles()
          setFiles(response.files || [])
        } catch (err: unknown) {
          toast.error(`Список файлов загружается слишком долго: ${extractErrorMessage(err)}`)
        } finally {
          setFilesLoading(false)
        }
      } else {
        setFiles([])
      }
    } catch (err: unknown) {
      const message = extractErrorMessage(err)
      setStatusError(message)
      toast.error(message)
      setStatus(null)
      setFiles([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [])

  const onUploadFiles = async (list: FileList | null) => {
    if (!list || list.length === 0) return
    setUploading(true)
    setJobProgress({ percent: 0, message: 'Создаю задачу индексации…' })
    try {
      const start = await startLegalCorpusUploadJob(Array.from(list))
      const url = buildLegalCorpusJobSseUrl(start.job_id)
      jobStreamRef.current?.close()
      const es = new EventSource(url)
      jobStreamRef.current = es

      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data || '{}') as any
          const t = String(data.type || '').toLowerCase()
          if (typeof data.progress_percent === 'number') {
            setJobProgress({ percent: data.progress_percent, message: String(data.message || '') })
          } else if (typeof data.message === 'string' && data.message) {
            setJobProgress((prev) => ({ percent: prev?.percent ?? 0, message: data.message }))
          }
          if (t === 'file_completed') {
            toast.success(String(data.message || 'Файл проиндексирован'))
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
          // ignore
        }
      }

      es.onerror = () => {
        // EventSource will auto-reconnect; show a soft message.
        setJobProgress((prev) => ({ percent: prev?.percent ?? 0, message: 'Переподключение к прогрессу…' }))
      }
    } catch (err: unknown) {
      toast.error(extractErrorMessage(err))
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const onDelete = async (corpusFileId: string, filename: string) => {
    if (!window.confirm(`Удалить «${filename}» из общего правового справочника?`)) {
      return
    }
    setDeletingId(corpusFileId)
    try {
      await deleteLegalCorpusFile(corpusFileId)
      toast.success('Файл удалён из справочника')
      await loadData()
    } catch (err: unknown) {
      toast.error(extractErrorMessage(err))
    } finally {
      setDeletingId(null)
    }
  }

  const onDeleteAll = async () => {
    if (
      !window.confirm(
        'Удалить ВСЕ файлы из правового справочника? Это удалит старые кодексы из индекса.'
      )
    ) {
      return
    }
    setDeletingAll(true)
    try {
      const res = await deleteAllLegalCorpusFiles()
      toast.success(`Справочник очищен: файлов ${res.deleted_files}, фрагментов ${res.deleted_chunks}`)
      await loadData()
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
                Правовой Справочник
              </h1>
              <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                Загрузка актуальных кодексов и НПА для общего доступа ИИ
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
                  Не удалось проверить доступ к справочнику: {statusError}
                </p>
                <button
                  type="button"
                  onClick={() => void loadData()}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm border"
                  style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                >
                  Повторить
                </button>
              </div>
            ) : !status?.is_uploader ? (
              <div
                className="rounded-xl border p-5"
                style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
              >
                <p className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                  Доступ к загрузке справочника есть только у уполномоченных аккаунтов.
                </p>
              </div>
            ) : (
              <>
                {jobProgress && (
                  <div
                    className="rounded-xl border p-4 mb-4 text-sm"
                    style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div style={{ color: 'var(--color-text-primary)' }}>
                        {jobProgress.message || 'Индексация…'}
                      </div>
                      <div style={{ color: 'var(--color-text-muted)' }}>
                        {Math.max(0, Math.min(100, Math.round(jobProgress.percent)))}%
                      </div>
                    </div>
                    <div className="mt-2 h-2 rounded bg-gray-200 overflow-hidden">
                      <div
                        className="h-2 bg-teal-600"
                        style={{ width: `${Math.max(0, Math.min(100, jobProgress.percent))}%` }}
                      />
                    </div>
                  </div>
                )}
                <div
                  className="rounded-xl border p-4 mb-4 flex items-center justify-between gap-3"
                  style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
                >
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-lg flex items-center justify-center bg-teal-100">
                      <Scale className="w-5 h-5 text-teal-700" />
                    </div>
                    <div>
                      <div className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                        Проиндексировано фрагментов: {status.chunk_count}
                      </div>
                      <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                        Эти данные доступны всем пользователям платформы
                      </div>
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center gap-2">
                      <input
                        ref={fileInputRef}
                        type="file"
                        multiple
                        accept=".pdf,.docx,.txt,.xlsx,.csv,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.gif"
                        className="hidden"
                        onChange={(e) => void onUploadFiles(e.target.files)}
                      />
                      <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={uploading || deletingAll}
                        className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm border disabled:opacity-50"
                        style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                      >
                        {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                        {uploading ? 'Индексация…' : 'Добавить файлы'}
                      </button>
                      <button
                        type="button"
                        onClick={() => void onDeleteAll()}
                        disabled={deletingAll || uploading || filesLoading || files.length === 0}
                        className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm border disabled:opacity-50"
                        style={{ borderColor: '#fecaca', color: '#dc2626', backgroundColor: '#fef2f2' }}
                      >
                        {deletingAll ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                        {deletingAll ? 'Удаление…' : 'Удалить все'}
                      </button>
                    </div>
                  </div>
                </div>

                <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--color-border)' }}>
                  <div
                    className="px-4 py-3 text-sm font-medium border-b"
                    style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                  >
                    Загруженные файлы ({files.length})
                  </div>

                  {filesLoading ? (
                    <div className="px-4 py-5 text-sm flex items-center gap-2" style={{ color: 'var(--color-text-muted)' }}>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Загрузка списка файлов…
                    </div>
                  ) : files.length === 0 ? (
                    <div className="px-4 py-5 text-sm" style={{ color: 'var(--color-text-muted)' }}>
                      Пока нет загруженных файлов.
                    </div>
                  ) : (
                    <div className="divide-y" style={{ borderColor: 'var(--color-border)' }}>
                      {files.map((row) => (
                        <div key={row.corpus_file_id} className="px-4 py-3 flex items-center gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="text-sm truncate" style={{ color: 'var(--color-text-primary)' }}>
                              {row.source_filename}
                            </div>
                            <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                              Фрагментов в индексе: {row.chunk_count}
                            </div>
                          </div>
                          <button
                            type="button"
                            disabled={deletingId === row.corpus_file_id || uploading}
                            onClick={() => void onDelete(row.corpus_file_id, row.source_filename)}
                            className="p-2 rounded-lg hover:bg-red-50 disabled:opacity-50"
                            style={{ color: '#dc2626' }}
                            aria-label={`Удалить ${row.source_filename}`}
                          >
                            {deletingId === row.corpus_file_id ? (
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

export default LegalCorpusManagePage
