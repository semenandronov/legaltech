import { useState, useEffect, useRef } from 'react'
import { X, Upload, Trash2, Loader2 } from 'lucide-react'
import { addFilesToCase, deleteFileFromCase, getCaseFiles, UploadedFile } from '../../services/api'

interface DocumentUploadModalProps {
  isOpen: boolean
  onClose: () => void
  caseId: string
  onUploadComplete: () => void
}

const MAX_FILE_SIZE_MB = 30
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

type FileUploadStatus = 'pending' | 'uploading' | 'processing' | 'done' | 'error'

interface FileUploadItem {
  file: File
  status: FileUploadStatus
  progress: number
  error?: string
}

const DocumentUploadModal = ({ isOpen, onClose, caseId, onUploadComplete }: DocumentUploadModalProps) => {
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([])
  const [uploadQueue, setUploadQueue] = useState<FileUploadItem[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const [loadingList, setLoadingList] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deletingFileId, setDeletingFileId] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Load existing files when modal opens
  useEffect(() => {
    if (isOpen && caseId) {
      loadFiles()
    }
  }, [isOpen, caseId])

  // Clean up on close
  useEffect(() => {
    if (!isOpen) {
      setUploadQueue([])
      setError(null)
    }
  }, [isOpen])

  const loadFiles = async () => {
    try {
      setLoadingList(true)
      setError(null)
      const response = await getCaseFiles(caseId)
      setUploadedFiles(response.files || [])
    } catch (err: any) {
      setError(err.message || 'Ошибка при загрузке списка файлов')
    } finally {
      setLoadingList(false)
    }
  }

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

    // Create queue items
    const queueItems: FileUploadItem[] = files.map(f => ({
      file: f,
      status: 'pending',
      progress: 0,
    }))

    setUploadQueue(queueItems)
    setIsUploading(true)

    // Upload files one by one
    for (let i = 0; i < queueItems.length; i++) {
      setUploadQueue(prev => prev.map((item, idx) =>
        idx === i ? { ...item, status: 'uploading', progress: 0 } : item
      ))

      let processingTimer: ReturnType<typeof setInterval> | null = null

      try {
        const response = await addFilesToCase(caseId, [queueItems[i].file], (percent) => {
          setUploadQueue(prev => prev.map((item, idx) => {
            if (idx !== i) return item
            const mappedProgress = Math.round(percent * 0.7)
            if (percent >= 100) {
              if (!processingTimer) {
                processingTimer = setInterval(() => {
                  setUploadQueue(prev2 => prev2.map((item2, idx2) => {
                    if (idx2 !== i || item2.status !== 'processing') return item2
                    const newProgress = Math.min(95, item2.progress + 0.5)
                    return { ...item2, progress: newProgress }
                  }))
                }, 300)
              }
              return { ...item, status: 'processing', progress: 70 }
            }
            return { ...item, progress: mappedProgress }
          }))
        })

        if (processingTimer) clearInterval(processingTimer)

        setUploadQueue(prev => prev.map((item, idx) =>
          idx === i ? { ...item, status: 'done', progress: 100 } : item
        ))

        const newFiles = response.files || []
        setUploadedFiles(prev => {
          const existingIds = new Set(prev.map(f => f.id))
          const uniqueNew = newFiles.filter(f => !existingIds.has(f.id))
          return [...prev, ...uniqueNew]
        })
      } catch (err: any) {
        if (processingTimer) clearInterval(processingTimer)
        const errorMsg = err.response?.data?.detail || err.message || 'Ошибка загрузки'
        setUploadQueue(prev => prev.map((item, idx) =>
          idx === i ? { ...item, status: 'error', error: errorMsg } : item
        ))
      }
    }

    setIsUploading(false)

    // Clear successful uploads after delay
    setTimeout(() => {
      setUploadQueue(prev => prev.filter(item => item.status === 'error'))
    }, 2000)
  }

  const handleDeleteFile = async (fileId: string, filename: string) => {
    if (!confirm(`Вы уверены, что хотите удалить файл "${filename}"?`)) {
      return
    }

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
    if (!isUploading) {
      fileInputRef.current?.click()
    }
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
              relative border-2 border-dashed rounded-xl p-8 text-center transition-all
              ${dragActive
                ? 'border-indigo-500 bg-indigo-50'
                : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50'
              }
            `}
            style={{
              cursor: isUploading ? 'default' : 'pointer',
              pointerEvents: isUploading ? 'none' : 'auto',
            }}
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
          </div>

          {/* Per-file upload progress */}
          {uploadQueue.length > 0 && (
            <div className="mt-6">
              <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-primary, #1f2937)' }}>
                Загрузка ({uploadQueue.filter(f => f.status === 'done').length}/{uploadQueue.length})
              </h3>
              <div className="space-y-2">
                {uploadQueue.map((item, idx) => (
                  <div
                    key={idx}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '12px',
                      padding: '10px 14px',
                      background: item.status === 'error' ? '#fef2f2' : 'var(--color-bg-secondary, #f9fafb)',
                      border: `1px solid ${item.status === 'error' ? '#fecaca' : 'var(--color-border, #e5e7eb)'}`,
                      borderRadius: '8px',
                    }}
                  >
                    {/* Circular progress indicator */}
                    <div style={{ flexShrink: 0, width: '28px', height: '28px', position: 'relative' }}>
                      {item.status === 'done' && (
                        <svg width="28" height="28" viewBox="0 0 28 28">
                          <circle cx="14" cy="14" r="12" fill="#16a34a" />
                          <path d="M9 14.5l3 3 7-7" stroke="white" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                      {item.status === 'error' && (
                        <svg width="28" height="28" viewBox="0 0 28 28">
                          <circle cx="14" cy="14" r="12" fill="#dc2626" />
                          <path d="M10 10l8 8M18 10l-8 8" stroke="white" strokeWidth="2" strokeLinecap="round" />
                        </svg>
                      )}
                      {item.status === 'pending' && (
                        <svg width="28" height="28" viewBox="0 0 28 28">
                          <circle cx="14" cy="14" r="12" fill="none" stroke="#e5e7eb" strokeWidth="2.5" />
                        </svg>
                      )}
                      {(item.status === 'uploading' || item.status === 'processing') && (() => {
                        const radius = 12
                        const circumference = 2 * Math.PI * radius
                        const offset = circumference - (item.progress / 100) * circumference
                        return (
                          <svg width="28" height="28" viewBox="0 0 28 28" style={{ transform: 'rotate(-90deg)' }}>
                            <circle cx="14" cy="14" r={radius} fill="none" stroke="#e5e7eb" strokeWidth="2.5" />
                            <circle
                              cx="14" cy="14" r={radius}
                              fill="none"
                              stroke="#16a34a"
                              strokeWidth="2.5"
                              strokeDasharray={circumference}
                              strokeDashoffset={offset}
                              strokeLinecap="round"
                              style={{ transition: 'stroke-dashoffset 0.3s ease' }}
                            />
                          </svg>
                        )
                      })()}
                    </div>

                    {/* File info */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{
                        fontSize: '13px',
                        fontWeight: 500,
                        color: item.status === 'error' ? '#dc2626' : 'var(--color-text-primary, #1f2937)',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}>
                        {item.file.name}
                      </div>
                      <div style={{ fontSize: '11px', color: '#9ca3af', marginTop: '2px' }}>
                        {item.status === 'pending' && 'В очереди'}
                        {item.status === 'uploading' && `Загрузка... ${Math.round(item.progress)}%`}
                        {item.status === 'processing' && `Обработка на сервере... ${Math.round(item.progress)}%`}
                        {item.status === 'done' && 'Готово'}
                        {item.status === 'error' && (
                          <span style={{ color: '#dc2626' }}>{item.error}</span>
                        )}
                      </div>
                    </div>

                    {/* File size */}
                    <div style={{ fontSize: '11px', color: '#9ca3af', flexShrink: 0 }}>
                      {formatFileSize(item.file.size)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Loading state */}
          {loadingList && (
            <div className="mt-6 flex items-center justify-center gap-2 py-4" style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
              <Loader2 className="w-4 h-4 animate-spin" />
              <span className="text-sm">Загрузка списка файлов...</span>
            </div>
          )}

          {/* Uploaded files list */}
          {!loadingList && uploadedFiles.length > 0 && (
            <div className="mt-6">
              <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-primary, #1f2937)' }}>
                Загруженные файлы ({uploadedFiles.length})
              </h3>
              <div className="space-y-2" style={{ maxHeight: '240px', overflowY: 'auto' }}>
                {uploadedFiles.map((file) => (
                  <div
                    key={file.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '12px 14px',
                      background: 'var(--color-bg-secondary, #f9fafb)',
                      border: '1px solid var(--color-border, #e5e7eb)',
                      borderRadius: '8px',
                    }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{
                        fontWeight: 500,
                        fontSize: '13px',
                        color: 'var(--color-text-primary, #1f2937)',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}>
                        {file.filename}
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--color-text-secondary, #6b7280)', marginTop: '2px' }}>
                        {file.file_type?.toUpperCase()}
                        {file.size && ` • ${formatFileSize(file.size)}`}
                        {file.created_at && ` • ${new Date(file.created_at).toLocaleDateString('ru-RU')}`}
                      </div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeleteFile(file.id, file.filename)
                      }}
                      disabled={deletingFileId === file.id || isUploading}
                      className="p-2 rounded-lg transition-colors hover:bg-red-50 shrink-0 ml-2"
                      style={{
                        color: (deletingFileId === file.id || isUploading) ? '#9ca3af' : '#ef4444'
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

          {/* Empty state */}
          {!loadingList && uploadedFiles.length === 0 && uploadQueue.length === 0 && (
            <div className="mt-6 text-center py-6" style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
              <p className="text-sm">Файлы ещё не загружены</p>
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
