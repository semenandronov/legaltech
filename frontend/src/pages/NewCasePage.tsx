import { useState, useRef, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Upload, Loader } from 'lucide-react'
import { createCase } from '../services/api'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { GoogleDriveImportButton } from '../components/Documents/GoogleDriveImportButton'
import { CaseFileStagingList } from '../components/Documents/CaseFileStagingList'
import { NewCasePageHeader } from '../components/Cases/NewCasePageHeader'
import { buildMainNavItems } from '../lib/mainNavItems'
import { startCaseStagedUpload } from '../lib/caseStagedUploadCoordinator'
import {
  type StagedCaseFile,
  type StagedDriveFile,
  type StagedLocalFile,
  dedupeStagedDrive,
  dedupeStagedLocal,
  drivePicksToStaged,
} from '../lib/caseFileStaging'
import { cn } from '@/lib/utils'

const MAX_FILE_SIZE_MB = 30
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

const NewCasePage = () => {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [staged, setStaged] = useState<StagedCaseFile[]>([])
  const [dragActive, setDragActive] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const stagedLocal = useMemo(
    () => staged.filter((s): s is StagedLocalFile => s.kind === 'local'),
    [staged],
  )
  const stagedDrive = useMemo(
    () => staged.filter((s): s is StagedDriveFile => s.kind === 'drive'),
    [staged],
  )

  const addLocalFiles = (files: File[]) => {
    const oversized = files.find((f) => f.size > MAX_FILE_SIZE_BYTES)
    if (oversized) {
      setError(`Файл «${oversized.name}» превышает ${MAX_FILE_SIZE_MB} МБ`)
      return
    }
    setStaged((prev) => {
      const locals = prev.filter((p): p is StagedLocalFile => p.kind === 'local')
      const drives = prev.filter((p): p is StagedDriveFile => p.kind === 'drive')
      return [...drives, ...dedupeStagedLocal(locals, files)]
    })
    setError(null)
  }

  const removeStaged = (key: string) => {
    setStaged((prev) => prev.filter((s) => s.key !== key))
  }

  const handleDrivePicked = useCallback((result: Parameters<typeof drivePicksToStaged>[0]) => {
    const incoming = drivePicksToStaged(result)
    setStaged((prev) => {
      const locals = prev.filter((p): p is StagedLocalFile => p.kind === 'local')
      const drives = prev.filter((p): p is StagedDriveFile => p.kind === 'drive')
      return [...locals, ...dedupeStagedDrive(drives, incoming)]
    })
    setError(null)
  }, [])

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') setDragActive(true)
    else if (e.type === 'dragleave') setDragActive(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    if (e.dataTransfer.files?.length) {
      addLocalFiles(Array.from(e.dataTransfer.files))
    }
  }

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) {
      addLocalFiles(Array.from(e.target.files))
      e.target.value = ''
    }
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
    return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
  }

  const hasStaged = staged.length > 0

  const handleCreate = async () => {
    if (!title.trim()) {
      setError('Укажите название дела')
      return
    }
    setError(null)
    setIsSubmitting(true)

    const localsToUpload = stagedLocal
    const drivesToUpload = stagedDrive
    const hasFiles = localsToUpload.length > 0 || drivesToUpload.length > 0

    try {
      const caseResponse = await createCase({ title: title.trim(), description: '' })
      const caseId = caseResponse.id

      if (hasFiles) {
        startCaseStagedUpload(caseId, { locals: localsToUpload, drives: drivesToUpload })
      }

      navigate(`/cases/${caseId}`, { replace: true })
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } }; message?: string }
      setError(
        ax.response?.data?.detail || ax.message || 'Ошибка при создании дела',
      )
      setIsSubmitting(false)
    }
  }

  return (
    <div className="ws-shell ws-tabular-shell flex h-screen overflow-hidden">
      <UnifiedSidebar navItems={buildMainNavItems()} title="Legal AI" showBackButton={false} variant="tabular" />

      <main className="ws-tabular-page flex min-h-0 flex-1 flex-col overflow-hidden">
        <NewCasePageHeader onNavigateCases={() => navigate('/cases')} />

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden border-t border-gray-200">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-2xl px-4 py-6 md:px-10 md:py-8">
              <p className="mb-6 text-sm text-gray-500">
                Каждое дело может содержать до 10 000 файлов
              </p>

              {error && (
                <p className="mb-5 text-sm text-red-500" role="alert">
                  {error}
                </p>
              )}

              <div className="mb-8">
                <label htmlFor="new-case-title" className="sr-only">
                  Название дела
                </label>
                <input
                  id="new-case-title"
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !isSubmitting) void handleCreate()
                  }}
                  placeholder="Название дела"
                  autoFocus
                  disabled={isSubmitting}
                  className="w-full bg-transparent font-serif text-2xl font-light text-gray-900 placeholder:text-gray-300 focus:outline-none disabled:opacity-50"
                />
              </div>

              <div>
                <p className="text-xs font-medium text-gray-700">Файлы</p>
                <p className="mt-1 mb-3 text-xs leading-relaxed text-gray-500">
                  Необязательно. Добавьте с компьютера или Google Drive — на сервер всё уйдёт после
                  «Создать дело».
                </p>

                <div
                  className={cn(
                    'rounded-xl border bg-white/60 p-5 transition-colors',
                    dragActive ? 'border-blue-400 bg-blue-50/40' : 'border-gray-200',
                  )}
                  onDragEnter={handleDrag}
                  onDragLeave={handleDrag}
                  onDragOver={handleDrag}
                  onDrop={handleDrop}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".pdf,.docx,.txt,.xlsx,.csv,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.gif"
                    className="hidden"
                    onChange={handleFileInput}
                  />
                  <div className="flex flex-wrap items-center justify-between gap-4">
                    <div className="flex min-w-0 items-center gap-3">
                      <Upload className="h-4 w-4 shrink-0 text-gray-400" aria-hidden />
                      <div>
                        <p className="text-sm text-gray-700">Перетащите файлы сюда</p>
                        <p className="mt-0.5 text-xs text-gray-400">или выберите на компьютере</p>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={isSubmitting}
                        className="ws-mike-table-empty-btn-secondary disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Выбрать файлы
                      </button>
                      <GoogleDriveImportButton
                        disabled={isSubmitting}
                        onPicked={handleDrivePicked}
                        loadingLabel="Выбор…"
                        variant="pill"
                      />
                    </div>
                  </div>
                </div>

                {hasStaged && (
                  <CaseFileStagingList
                    staged={staged}
                    onRemoveStaged={removeStaged}
                    canRemove={!isSubmitting}
                    formatFileSize={formatFileSize}
                    title="Файлы к загрузке"
                  />
                )}
              </div>
            </div>
          </div>

          <div className="flex shrink-0 items-center justify-end gap-3 border-t border-gray-200 px-4 py-4 md:px-10">
            {isSubmitting && (
              <span className="mr-auto flex items-center gap-1.5 text-xs text-gray-500">
                <Loader className="h-3 w-3 animate-spin" />
                Создание дела…
              </span>
            )}
            <button
              type="button"
              onClick={() => navigate('/cases')}
              disabled={isSubmitting}
              className="ws-mike-modal-btn-cancel disabled:opacity-50"
            >
              Отмена
            </button>
            <button
              type="button"
              onClick={() => void handleCreate()}
              disabled={isSubmitting || !title.trim()}
              className="ws-mike-modal-btn-primary"
            >
              {isSubmitting
                ? 'Создание…'
                : hasStaged
                  ? `Создать дело (${staged.length})`
                  : 'Создать дело'}
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}

export default NewCasePage
