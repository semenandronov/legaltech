import { useState, useEffect, useRef } from 'react'
import './Upload.css'
import { addFilesToCase, deleteFileFromCase, getCaseFiles, UploadedFile } from '../../services/api'

interface DocumentsUploadStepProps {
  caseId: string
  onContinue: () => void
  onCancel: () => void
}

const MAX_FILE_SIZE_MB = 5
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

const DocumentsUploadStep = ({ caseId, onContinue, onCancel }: DocumentsUploadStepProps) => {
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [deletingFileId, setDeletingFileId] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    loadFiles()
  }, [caseId])

  const loadFiles = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await getCaseFiles(caseId)
      setUploadedFiles(response.files || [])
    } catch (err: any) {
      setError(err.message || 'Ошибка при загрузке списка файлов')
    } finally {
      setLoading(false)
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
      // Reset input
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

    // Validate file sizes
    const tooBig = files.find((file) => file.size > MAX_FILE_SIZE_BYTES)
    if (tooBig) {
      setError(`Файл '${tooBig.name}' слишком большой. Максимальный размер: ${MAX_FILE_SIZE_MB} МБ.`)
      return
    }

    try {
      setLoading(true)
      setUploadProgress(0)
      const response = await addFilesToCase(caseId, files, (percent) => {
        setUploadProgress(percent)
      })
      setUploadedFiles(response.files || [])
      setUploadProgress(0)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Ошибка при загрузке файлов')
    } finally {
      setLoading(false)
      setUploadProgress(0)
    }
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
    fileInputRef.current?.click()
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return bytes + ' Б'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' КБ'
    return (bytes / (1024 * 1024)).toFixed(1) + ' МБ'
  }

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
        style={{ marginBottom: '24px', cursor: 'pointer' }}
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
        
        {loading && uploadProgress > 0 && (
          <div style={{ marginTop: '16px', width: '100%', maxWidth: '300px' }}>
            <div className="processing-progress-bar">
              <div 
                className="processing-progress-fill" 
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
            <div className="processing-progress-text">{uploadProgress}%</div>
          </div>
        )}
      </div>

      {/* Files list */}
      {loading && !uploadProgress && (
        <div style={{ textAlign: 'center', padding: '20px', color: '#6b7280' }}>
          Загрузка списка файлов...
        </div>
      )}

      {!loading && uploadedFiles.length === 0 && (
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
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
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
                <div style={{ flex: 1 }}>
                  <div style={{ 
                    fontWeight: 500, 
                    color: '#1f2937',
                    marginBottom: '4px'
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
                  disabled={deletingFileId === file.id}
                  style={{
                    padding: '8px 16px',
                    background: deletingFileId === file.id ? '#f3f4f6' : '#ef4444',
                    color: deletingFileId === file.id ? '#9ca3af' : 'white',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: deletingFileId === file.id ? 'not-allowed' : 'pointer',
                    fontSize: '14px',
                    fontWeight: 500,
                    transition: 'all 0.2s',
                  }}
                  onMouseEnter={(e) => {
                    if (deletingFileId !== file.id) {
                      e.currentTarget.style.background = '#dc2626'
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (deletingFileId !== file.id) {
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
          disabled={loading}
        >
          Отменить
        </button>
        <button 
          type="button"
          className="upload-button-primary" 
          onClick={onContinue}
          disabled={loading || uploadedFiles.length === 0}
          style={{
            opacity: (loading || uploadedFiles.length === 0) ? 0.5 : 1,
            cursor: (loading || uploadedFiles.length === 0) ? 'not-allowed' : 'pointer',
          }}
        >
          Продолжить
        </button>
      </div>
    </div>
  )
}

export default DocumentsUploadStep


