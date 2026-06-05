import { useState, useEffect, useRef } from 'react'
import './Upload.css'
import { addFilesToCase, deleteFileFromCase, getCaseFiles, UploadedFile } from '../../services/api'
import {
  GoogleDriveImportButton,
  mergeUploadedFiles,
} from '../Documents/GoogleDriveImportButton'

interface DocumentsUploadStepProps {
  caseId: string
  onContinue: () => void
  onCancel: () => void
}

const MAX_FILE_SIZE_MB = 30
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

type FileUploadStatus = 'pending' | 'uploading' | 'processing' | 'done' | 'error'

interface FileUploadItem {
  file: File
  status: FileUploadStatus
  progress: number // 0-100
  error?: string
}

const DocumentsUploadStep = ({ caseId, onContinue, onCancel }: DocumentsUploadStepProps) => {
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([])
  const [uploadQueue, setUploadQueue] = useState<FileUploadItem[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const [loadingList, setLoadingList] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deletingFileId, setDeletingFileId] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    loadFiles()
  }, [caseId])

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
      setError(`Файл '${tooBig.name}' слишком большой. Максимальный размер: ${MAX_FILE_SIZE_MB} МБ.`)
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
      // Update status to uploading
      setUploadQueue(prev => prev.map((item, idx) =>
        idx === i ? { ...item, status: 'uploading', progress: 0 } : item
      ))

      // Simulated progress timer for server processing phase
      let processingTimer: ReturnType<typeof setInterval> | null = null

      try {
        const response = await addFilesToCase(caseId, [queueItems[i].file], (percent) => {
          setUploadQueue(prev => prev.map((item, idx) => {
            if (idx !== i) return item
            // Map upload progress to 0-70% range
            const mappedProgress = Math.round(percent * 0.7)
            // When HTTP upload is done (100%), server starts processing
            if (percent >= 100) {
              // Start simulated processing progress: 70% → 95%
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

        // Stop simulated progress
        if (processingTimer) clearInterval(processingTimer)

        // Mark as done
        setUploadQueue(prev => prev.map((item, idx) =>
          idx === i ? { ...item, status: 'done', progress: 100 } : item
        ))

        // Add to uploaded files list
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

    // Clear queue after a delay so user can see the results
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
      const response = await deleteFileFromCase(caseId, fileId)
      setUploadedFiles(response.files || [])
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Ошибка при удалении файла')
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

  const hasActiveUploads = uploadQueue.some(item => item.status === 'uploading' || item.status === 'processing' || item.status === 'pending')

  return (
    <div className="upload-step-container">
      <h2 className="upload-step-title">Загрузка документов</h2>

      {error && <div className="auth-error" style={{ marginBottom: '16px' }}>{error}</div>}

      {/* Upload area */}
      <div
        className={`upload-area ${dragActive ? 'drag-active' : ''}`}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={handleClick}
        style={{
          marginBottom: '24px',
          cursor: isUploading ? 'default' : 'pointer',
          pointerEvents: isUploading ? 'none' : 'auto',
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileInput}
          style={{ display: 'none' }}
        />
        <div className="upload-icon">📄 📄 📄</div>
        <p className="upload-text">Перетащите документы сюда</p>
        <p className="upload-subtext">или нажмите для выбора файлов</p>
      </div>

      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '24px' }}>
        <GoogleDriveImportButton
          caseId={caseId}
          disabled={isUploading}
          onImportComplete={(response) => {
            setUploadedFiles((prev) => mergeUploadedFiles(prev, response))
            loadFiles()
          }}
        />
      </div>

      {/* Per-file upload progress */}
      {uploadQueue.length > 0 && (
        <div style={{ marginBottom: '24px' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px', color: '#1f2937' }}>
            Загрузка ({uploadQueue.filter(f => f.status === 'done').length}/{uploadQueue.length})
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {uploadQueue.map((item, idx) => (
              <div
                key={idx}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  padding: '10px 14px',
                  background: item.status === 'error' ? '#fef2f2' : '#f9fafb',
                  border: `1px solid ${item.status === 'error' ? '#fecaca' : '#e5e7eb'}`,
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
                        {/* Background circle */}
                        <circle cx="14" cy="14" r={radius} fill="none" stroke="#e5e7eb" strokeWidth="2.5" />
                        {/* Progress circle - always green */}
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
                    color: item.status === 'error' ? '#dc2626' : '#1f2937',
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

      {/* Files list */}
      {loadingList && (
        <div style={{ textAlign: 'center', padding: '20px', color: '#6b7280' }}>
          Загрузка списка файлов...
        </div>
      )}

      {!loadingList && uploadedFiles.length === 0 && uploadQueue.length === 0 && (
        <div style={{
          textAlign: 'center',
          padding: '40px',
          color: '#6b7280',
          border: '2px dashed #e5e7eb',
          borderRadius: '8px',
          marginBottom: '24px'
        }}>
          <p>Файлы еще не загружены</p>
          <p style={{ fontSize: '14px', marginTop: '8px' }}>
            Добавьте документы для продолжения
          </p>
        </div>
      )}

      {uploadedFiles.length > 0 && (
        <div style={{ marginBottom: '24px' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px', color: '#1f2937' }}>
            Загруженные файлы ({uploadedFiles.length})
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxHeight: '240px', overflowY: 'auto' }}>
            {uploadedFiles.map((file) => (
              <div
                key={file.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '16px',
                  background: '#ffffff',
                  border: '1px solid #e5e7eb',
                  borderRadius: '8px',
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontWeight: 500,
                    color: '#1f2937',
                    marginBottom: '4px',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}>
                    {file.filename}
                  </div>
                  <div style={{ fontSize: '12px', color: '#6b7280' }}>
                    {file.file_type.toUpperCase()}
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
                  style={{
                    flexShrink: 0,
                    marginLeft: '12px',
                    padding: '8px 16px',
                    background: (deletingFileId === file.id || isUploading) ? '#f3f4f6' : '#ef4444',
                    color: (deletingFileId === file.id || isUploading) ? '#9ca3af' : 'white',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: (deletingFileId === file.id || isUploading) ? 'not-allowed' : 'pointer',
                    fontSize: '14px',
                    fontWeight: 500,
                    transition: 'all 0.2s',
                  }}
                  onMouseEnter={(e) => {
                    if (deletingFileId !== file.id && !isUploading) {
                      e.currentTarget.style.background = '#dc2626'
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (deletingFileId !== file.id && !isUploading) {
                      e.currentTarget.style.background = '#ef4444'
                    }
                  }}
                >
                  {deletingFileId === file.id ? 'Удаление...' : 'Удалить'}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="upload-form-actions">
        <button
          type="button"
          className="upload-button-secondary"
          onClick={onCancel}
          disabled={isUploading}
        >
          Отменить
        </button>
        <button
          type="button"
          className="upload-button-primary"
          onClick={onContinue}
          disabled={hasActiveUploads || uploadedFiles.length === 0}
          style={{
            opacity: (hasActiveUploads || uploadedFiles.length === 0) ? 0.5 : 1,
            cursor: (hasActiveUploads || uploadedFiles.length === 0) ? 'not-allowed' : 'pointer',
          }}
        >
          Продолжить
        </button>
      </div>

      {/* Inline keyframes for spinner */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}

export default DocumentsUploadStep
