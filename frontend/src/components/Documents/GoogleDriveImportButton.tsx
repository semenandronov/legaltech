import { useCallback, useState } from 'react'
import { Cloud, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  importFilesFromGoogleDrive,
  FilesResponse,
  UploadedFile,
} from '../../services/api'
import {
  isGoogleDriveImportConfigured,
  openGoogleDrivePicker,
  type GoogleDrivePickResult,
} from '../../lib/googleDrivePicker'
import { logger } from '../../lib/logger'

export interface GoogleDriveImportButtonProps {
  /** Импорт сразу в существующее дело */
  caseId?: string
  /**
   * Только выбор в Picker (без API). Для экрана «Новое дело» — файлы в локальный список.
   */
  onPicked?: (result: GoogleDrivePickResult) => void
  disabled?: boolean
  onImportStarted?: () => void
  /** После успешного import в дело (режим caseId) */
  onImportComplete?: (response: FilesResponse) => void
  onImportFailed?: () => void
  className?: string
  variant?: 'primary' | 'secondary'
  label?: string
  loadingLabel?: string
}

export function GoogleDriveImportButton({
  caseId,
  onPicked,
  disabled = false,
  onImportStarted,
  onImportComplete,
  onImportFailed,
  className = '',
  variant = 'secondary',
  label = 'Из Google Drive',
  loadingLabel = 'Импорт…',
}: GoogleDriveImportButtonProps) {
  const [loading, setLoading] = useState(false)
  const stageMode = Boolean(onPicked) && !caseId

  const handleClick = useCallback(async () => {
    if (!isGoogleDriveImportConfigured()) {
      toast.error('Импорт из Google Drive не настроен', {
        description: 'Добавьте VITE_GOOGLE_CLIENT_ID и VITE_GOOGLE_API_KEY в корневой .env',
      })
      return
    }

    if (!stageMode && !caseId) {
      toast.error('Не указано дело для импорта')
      return
    }

    setLoading(true)
    onImportStarted?.()

    try {
      const pickResult = await openGoogleDrivePicker()

      if (stageMode && onPicked) {
        onPicked(pickResult)
        toast.success(
          pickResult.docs.length === 1
            ? 'Файл добавлен в список'
            : `Добавлено файлов: ${pickResult.docs.length}`,
        )
        return
      }

      if (!caseId) {
        throw new Error('Не указано дело для импорта')
      }

      toast.message(`Импорт ${pickResult.docs.length} файл(ов) из Google Drive…`)

      const response = await importFilesFromGoogleDrive(caseId, {
        access_token: pickResult.accessToken,
        files: pickResult.docs.map((d) => ({
          id: d.id,
          name: d.name,
          mime_type: d.mimeType,
        })),
      })

      const added = response.added ?? response.files?.length ?? 0
      const errors = response.errors ?? []
      if (errors.length > 0 && added > 0) {
        toast.warning(`Импортировано ${added}, ошибок: ${errors.length}`)
      } else if (added > 0) {
        toast.success(`Импортировано файлов: ${added}`)
      } else {
        toast.error('Не удалось импортировать файлы')
      }

      onImportComplete?.(response)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Ошибка импорта'
      if (message === 'Выбор отменён') {
        toast.message('Выбор отменён')
      } else {
        logger.error('Google Drive import failed', err)
        toast.error(message)
      }
      onImportFailed?.()
    } finally {
      setLoading(false)
    }
  }, [caseId, stageMode, onPicked, onImportComplete, onImportFailed, onImportStarted])

  if (!isGoogleDriveImportConfigured()) {
    return null
  }

  const base =
    variant === 'primary'
      ? 'bg-blue-600 text-white hover:bg-blue-700'
      : 'border border-gray-300 bg-white text-gray-800 hover:bg-gray-50'

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 ${base} ${className}`}
    >
      {loading ? (
        <Loader2 className="w-4 h-4 animate-spin" />
      ) : (
        <Cloud className="w-4 h-4" />
      )}
      {loading ? loadingLabel : label}
    </button>
  )
}

/** Merge API response files into existing uploaded list (dedupe by id). */
export function mergeUploadedFiles(
  prev: UploadedFile[],
  response: FilesResponse,
): UploadedFile[] {
  const newFiles = response.files ?? []
  const existingIds = new Set(prev.map((f) => f.id))
  const uniqueNew = newFiles.filter((f) => !existingIds.has(f.id))
  return [...prev, ...uniqueNew]
}
