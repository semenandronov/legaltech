import { useState, useRef, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderOpen, MessageSquare, Upload, Loader } from 'lucide-react'
import { createCase } from '../services/api'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { GoogleDriveImportButton } from '../components/Documents/GoogleDriveImportButton'
import { CaseFileStagingList } from '../components/Documents/CaseFileStagingList'
import {
  type StagedCaseFile,
  type StagedDriveFile,
  type StagedLocalFile,
  dedupeStagedDrive,
  dedupeStagedLocal,
  drivePicksToStaged,
} from '../lib/caseFileStaging'
import type { CaseOverviewLocationState } from '../lib/casePostCreateUpload'

const MAX_FILE_SIZE_MB = 30
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

const mainNavItems = [
  { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
  { id: 'assistant', label: 'Ассистент', icon: MessageSquare, path: '/assistant' },
]

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

      const navState: CaseOverviewLocationState | undefined = hasFiles
        ? { postCreateUpload: { locals: localsToUpload, drives: drivesToUpload } }
        : undefined

      navigate(`/cases/${caseId}`, { replace: true, state: navState })
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } }; message?: string }
      setError(
        ax.response?.data?.detail || ax.message || 'Ошибка при создании дела',
      )
      setIsSubmitting(false)
    }
  }

  return (
    <div
      className="h-screen flex overflow-hidden"
      style={{ backgroundColor: 'var(--color-bg-primary)' }}
    >
      <UnifiedSidebar navItems={mainNavItems} title="Legal AI" />

      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-auto">
          <div className="px-8 pt-8 pb-8 max-w-2xl">
            <div
              className="flex items-center gap-1.5 text-sm mb-6"
              style={{ color: 'var(--color-text-muted)' }}
            >
              <button
                type="button"
                onClick={() => navigate('/cases')}
                className="hover:underline transition-colors"
                style={{ color: 'var(--color-text-muted)' }}
              >
                Дела
              </button>
              <span>/</span>
            </div>

            <h1
              className="text-2xl font-semibold tracking-tight mb-1"
              style={{ color: 'var(--color-text-primary)' }}
            >
              Новое дело
            </h1>
            <p className="text-sm mb-8" style={{ color: 'var(--color-text-secondary)' }}>
              Каждое дело может содержать до 10 000 файлов
            </p>

            {error && (
              <div
                className="mb-5 p-3 rounded-lg text-sm"
                style={{
                  backgroundColor: 'var(--color-bg-elevated)',
                  border: '1px solid var(--color-error, #dc2626)',
                  color: 'var(--color-error, #dc2626)',
                }}
              >
                {error}
              </div>
            )}

            <div className="mb-7">
              <label
                className="block text-sm font-medium mb-2"
                style={{ color: 'var(--color-text-primary)' }}
              >
                Название дела
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !isSubmitting) handleCreate()
                }}
                placeholder="Введите название дела"
                autoFocus
                disabled={isSubmitting}
                className="w-full px-4 py-2.5 rounded-lg border text-sm focus:outline-none transition-colors disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--color-bg-elevated)',
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-primary)',
                }}
              />
            </div>

            <div>
              <label
                className="block text-sm font-medium mb-1"
                style={{ color: 'var(--color-text-primary)' }}
              >
                Файлы{' '}
                <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}>
                  (необязательно)
                </span>
              </label>
              <p
                className="text-xs mb-3 leading-relaxed"
                style={{ color: 'var(--color-text-muted)' }}
              >
                Добавьте файлы с компьютера или Google Drive. Удалите лишние в списке ниже. На
                сервер всё уйдёт только после «Создать дело» — обработка одинакова для всех
                источников.
              </p>

              <div
                className="rounded-lg border transition-colors"
                style={{
                  borderColor: dragActive ? 'var(--color-accent, #6366f1)' : 'var(--color-border)',
                  backgroundColor: dragActive
                    ? 'var(--color-bg-hover)'
                    : 'var(--color-bg-elevated)',
                  padding: '20px 24px',
                }}
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
                  <div className="flex items-center gap-3">
                    <Upload
                      className="w-4 h-4 flex-shrink-0"
                      style={{ color: 'var(--color-text-muted)' }}
                    />
                    <div>
                      <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                        Перетащите файлы сюда
                      </p>
                      <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                        или выберите на компьютере
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={isSubmitting}
                      className="flex-shrink-0 px-4 py-2 rounded-lg text-sm font-medium border transition-colors hover:bg-[var(--color-bg-hover)] disabled:opacity-50"
                      style={{
                        borderColor: 'var(--color-border)',
                        color: 'var(--color-text-primary)',
                        backgroundColor: 'var(--color-bg-primary)',
                      }}
                    >
                      Выбрать файлы
                    </button>
                    <GoogleDriveImportButton
                      disabled={isSubmitting}
                      onPicked={handleDrivePicked}
                      loadingLabel="Выбор…"
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

        <div
          className="border-t flex items-center justify-end gap-3 px-8 py-4"
          style={{ borderTopColor: 'var(--color-border)' }}
        >
          {isSubmitting && (
            <span
              className="text-xs mr-auto flex items-center gap-1.5"
              style={{ color: 'var(--color-text-muted)' }}
            >
              <Loader className="w-3 h-3 animate-spin" />
              Создание дела…
            </span>
          )}
          <button
            type="button"
            onClick={() => navigate('/cases')}
            disabled={isSubmitting}
            className="px-4 py-2 text-sm font-medium rounded-lg border transition-colors hover:bg-[var(--color-bg-hover)] disabled:opacity-50"
            style={{
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
              backgroundColor: 'transparent',
            }}
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={handleCreate}
            disabled={isSubmitting || !title.trim()}
            className="px-4 py-2 text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
            style={{
              backgroundColor:
                isSubmitting || !title.trim()
                  ? 'var(--color-text-muted)'
                  : 'var(--color-text-primary)',
              color: 'var(--color-bg-primary)',
              cursor: isSubmitting || !title.trim() ? 'not-allowed' : 'pointer',
            }}
          >
            {isSubmitting
              ? 'Создание…'
              : hasStaged
                ? `Создать дело (${staged.length} файл.)`
                : 'Создать дело'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default NewCasePage
