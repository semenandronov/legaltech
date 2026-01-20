import { useState, useRef } from 'react'
import { X, Upload, FileText, Trash2, Loader2 } from 'lucide-react'
import { addFilesToCase, deleteFileFromCase, UploadedFile } from '../../services/api'

interface DocumentUploadModalProps {
  isOpen: boolean
  onClose: () => void
  caseId: string
  onUploadComplete: () => void
}

const MAX_FILE_SIZE_MB = 5
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

const DocumentUploadModal = ({ isOpen, onClose, caseId, onUploadComplete }: DocumentUploadModalProps) => {
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [deletingFileId, setDeletingFileId] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  if (!isOpen) return null

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true)
    } else if (e.type === 'dragleave') {
      setDragActive(false)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleAddFiles(Array.from(e.dataTransfer.files))
    }
  }

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleAddFiles(Array.from(e.target.files))
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const handleAddFiles = async (files: File[]) => {
    setError(null)

    if (!files || files.length === 0) {
      setError('Пожалуйста, выберите хотя бы один файл')
      return
    }

    const tooBig = files.find((file) => file.size > MAX_FILE_SIZE_BYTES)
    if (tooBig) {
      setError(`Файл «${tooBig.name}» слишком большой. Максимальный размер: ${MAX_FILE_SIZE_MB} МБ.`)
      return
    }

    try {
      setLoading(true)
      setUploadProgress(0)
      const response = await addFilesToCase(caseId, files, (percent) => {
        setUploadProgress(percent)
      })
      setUploadedFiles((prev) => [...prev, ...(response.files || [])])
      setUploadProgress(0)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Ошибка при загрузке файлов')
    } finally {
      setLoading(false)
      setUploadProgress(0)
    }
  }

  const handleDeleteFile = async (fileId: string, filename: string) => {
    try {
      setDeletingFileId(fileId)
      setError(null)
      await deleteFileFromCase(caseId, fileId)
      setUploadedFiles((prev) => prev.filter((f) => f.id !== fileId))
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || `Ошибка при удалении файла «${filename}»`)
    } finally {
      setDeletingFileId(null)
    }
  }

  const handleClick = () => {
    fileInputRef.current?.click()
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return bytes + ' Б'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' КБ'
    return (bytes / (1024 * 1024)).toFixed(1) + ' МБ'
  }

  const handleClose = () => {
    if (uploadedFiles.length > 0) {
      onUploadComplete()
    }
    setUploadedFiles([])
    setError(null)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div
        className="w-full max-w-2xl max-h-[90vh] overflow-hidden rounded-xl shadow-xl flex flex-col"
        style={{ backgroundColor: 'var(--color-bg-primary, white)' }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between p-4 border-b shrink-0"
          style={{ borderColor: 'var(--color-border, #e5e7eb)' }}
        >
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center"
              style={{ backgroundColor: 'rgba(99, 102, 241, 0.15)' }}
            >
              <Upload className="w-5 h-5" style={{ color: '#6366f1' }} />
            </div>
            <div>
              <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary, #1f2937)' }}>
                Загрузить документы
              </h2>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
                Добавьте файлы в дело
              </p>
            </div>
          </div>
          <button
            onClick={handleClose}
            className="p-2 rounded-lg transition-colors hover:bg-gray-100"
            style={{ color: 'var(--color-text-secondary, #6b7280)' }}
            aria-label="Закрыть"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {error && (
            <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
              {error}
            </div>
          )}

          {/* Drop zone */}
          <div
            className={`
              relative border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all
              ${dragActive 
                ? 'border-indigo-500 bg-indigo-50' 
                : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50'
              }
            `}
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            onClick={handleClick}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              onChange={handleFileInput}
              className="hidden"
            />

            <div className="flex flex-col items-center gap-3">
              <div
                className="w-16 h-16 rounded-full flex items-center justify-center"
                style={{ backgroundColor: 'rgba(99, 102, 241, 0.1)' }}
              >
                <Upload className="w-8 h-8" style={{ color: '#6366f1' }} />
              </div>
              <div>
                <p className="text-base font-medium" style={{ color: 'var(--color-text-primary, #1f2937)' }}>
                  Перетащите файлы сюда
                </p>
                <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
                  или нажмите для выбора файлов
                </p>
              </div>
              <p className="text-xs" style={{ color: 'var(--color-text-tertiary, #9ca3af)' }}>
                Максимальный размер файла: {MAX_FILE_SIZE_MB} МБ
              </p>
            </div>

            {loading && uploadProgress > 0 && (
              <div className="mt-6 w-full max-w-xs mx-auto">
                <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className="h-full transition-all duration-300"
                    style={{
                      width: `${uploadProgress}%`,
                      background: 'linear-gradient(90deg, #667eea 0%, #764ba2 100%)'
                    }}
                  />
                </div>
                <p className="text-sm mt-2" style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
                  Загрузка… {uploadProgress}%
                </p>
              </div>
            )}
          </div>

          {/* Uploaded files list */}
          {uploadedFiles.length > 0 && (
            <div className="mt-6">
              <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-primary, #1f2937)' }}>
                Загруженные файлы ({uploadedFiles.length})
              </h3>
              <div className="space-y-2">
                {uploadedFiles.map((file) => (
                  <div
                    key={file.id}
                    className="flex items-center justify-between p-3 rounded-lg border"
                    style={{
                      backgroundColor: 'var(--color-bg-secondary, #f9fafb)',
                      borderColor: 'var(--color-border, #e5e7eb)'
                    }}
                  >
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      <div
                        className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                        style={{ backgroundColor: 'rgba(99, 102, 241, 0.1)' }}
                      >
                        <FileText className="w-4 h-4" style={{ color: '#6366f1' }} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium truncate" style={{ color: 'var(--color-text-primary, #1f2937)' }}>
                          {file.filename}
                        </p>
                        <p className="text-xs" style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
                          {file.file_type.toUpperCase()}
                          {file.size && ` • ${formatFileSize(file.size)}`}
                        </p>
                      </div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeleteFile(file.id, file.filename)
                      }}
                      disabled={deletingFileId === file.id}
                      className="p-2 rounded-lg transition-colors hover:bg-red-50 shrink-0"
                      style={{
                        color: deletingFileId === file.id ? '#9ca3af' : '#ef4444'
                      }}
                      aria-label={`Удалить ${file.filename}`}
                    >
                      {deletingFileId === file.id ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Trash2 className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          className="flex items-center justify-end gap-3 p-4 border-t shrink-0"
          style={{ borderColor: 'var(--color-border, #e5e7eb)' }}
        >
          <button
            onClick={handleClose}
            className="px-4 py-2 rounded-lg text-sm font-medium transition-colors border"
            style={{
              borderColor: 'var(--color-border, #d1d5db)',
              color: 'var(--color-text-primary, #1f2937)',
              backgroundColor: 'transparent'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--color-bg-secondary, #f3f4f6)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent'
            }}
          >
            {uploadedFiles.length > 0 ? 'Готово' : 'Отмена'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default DocumentUploadModal

