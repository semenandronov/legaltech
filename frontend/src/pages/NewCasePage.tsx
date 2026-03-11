import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderOpen, MessageSquare, Upload, X, FileText } from 'lucide-react'
import { createCase, addFilesToCase } from '../services/api'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'

const MAX_FILE_SIZE_MB = 30
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

const mainNavItems = [
  { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
  { id: 'assistant', label: 'Ассистент', icon: MessageSquare, path: '/assistant' },
]

const NewCasePage = () => {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [stagedFiles, setStagedFiles] = useState<File[]>([])
  const [dragActive, setDragActive] = useState(false)
  const [isCreating, setIsCreating] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const addStagedFiles = (files: File[]) => {
    const oversized = files.find(f => f.size > MAX_FILE_SIZE_BYTES)
    if (oversized) {
      setError(`Файл «${oversized.name}» превышает ${MAX_FILE_SIZE_MB} МБ`)
      return
    }
    setStagedFiles(prev => {
      const existingNames = new Set(prev.map(f => f.name))
      return [...prev, ...files.filter(f => !existingNames.has(f.name))]
    })
    setError(null)
  }

  const removeFile = (index: number) => {
    setStagedFiles(prev => prev.filter((_, i) => i !== index))
  }

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
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      addStagedFiles(Array.from(e.dataTransfer.files))
    }
  }

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      addStagedFiles(Array.from(e.target.files))
      e.target.value = ''
    }
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' КБ'
    return (bytes / (1024 * 1024)).toFixed(1) + ' МБ'
  }

  const handleCreate = async () => {
    if (!title.trim()) {
      setError('Укажите название дела')
      return
    }
    setError(null)
    setIsCreating(true)
    setUploadProgress(0)

    try {
      const caseResponse = await createCase({ title: title.trim(), description: '' })
      const caseId = caseResponse.id

      if (stagedFiles.length > 0) {
        await addFilesToCase(caseId, stagedFiles, (percent) => {
          setUploadProgress(percent)
        })
      }

      navigate(`/cases/${caseId}`)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Ошибка при создании дела')
      setIsCreating(false)
      setUploadProgress(0)
    }
  }

  return (
    <div
      className="h-screen flex overflow-hidden"
      style={{ backgroundColor: 'var(--color-bg-primary)' }}
    >
      <UnifiedSidebar navItems={mainNavItems} title="Legal AI" />

      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Scrollable content area */}
        <div className="flex-1 overflow-auto">
          <div className="px-8 pt-8 pb-8 max-w-2xl">
            {/* Breadcrumb */}
            <div className="flex items-center gap-1.5 text-sm mb-6" style={{ color: 'var(--color-text-muted)' }}>
              <button
                onClick={() => navigate('/cases')}
                className="hover:underline transition-colors"
                style={{ color: 'var(--color-text-muted)' }}
              >
                Дела
              </button>
              <span>/</span>
            </div>

            {/* Heading */}
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

            {/* Project name */}
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
                onChange={e => setTitle(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleCreate() }}
                placeholder="Введите название дела"
                autoFocus
                className="w-full px-4 py-2.5 rounded-lg border text-sm focus:outline-none transition-colors"
                style={{
                  backgroundColor: 'var(--color-bg-elevated)',
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-primary)',
                }}
              />
            </div>

            {/* Files */}
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
              <p className="text-xs mb-3 leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
                Документы будут сохранены и доступны только вам. Вы сможете удалить их в любое время.
              </p>

              {/* Drop zone */}
              <div
                className="rounded-lg border transition-colors"
                style={{
                  borderColor: dragActive ? 'var(--color-accent, #6366f1)' : 'var(--color-border)',
                  backgroundColor: dragActive ? 'var(--color-bg-hover)' : 'var(--color-bg-elevated)',
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
                  className="hidden"
                  onChange={handleFileInput}
                />
                <div className="flex items-center justify-between gap-4">
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
                        Выберите с вашего компьютера
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="flex-shrink-0 px-4 py-2 rounded-lg text-sm font-medium border transition-colors hover:bg-[var(--color-bg-hover)]"
                    style={{
                      borderColor: 'var(--color-border)',
                      color: 'var(--color-text-primary)',
                      backgroundColor: 'var(--color-bg-primary)',
                    }}
                  >
                    Выбрать файлы
                  </button>
                </div>
              </div>

              {/* Staged file list */}
              {stagedFiles.length > 0 && (
                <div className="mt-3 space-y-2">
                  {stagedFiles.map((file, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-3 px-4 py-3 rounded-lg border"
                      style={{
                        borderColor: 'var(--color-border)',
                        backgroundColor: 'var(--color-bg-elevated)',
                      }}
                    >
                      <FileText
                        className="w-4 h-4 flex-shrink-0"
                        style={{ color: 'var(--color-text-muted)' }}
                      />
                      <span
                        className="flex-1 text-sm truncate"
                        style={{ color: 'var(--color-text-primary)' }}
                      >
                        {file.name}
                      </span>
                      <span
                        className="text-xs flex-shrink-0"
                        style={{ color: 'var(--color-text-muted)' }}
                      >
                        {formatFileSize(file.size)}
                      </span>
                      <button
                        onClick={() => removeFile(i)}
                        className="flex-shrink-0 p-0.5 rounded transition-colors hover:opacity-70"
                        style={{ color: 'var(--color-text-muted)' }}
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Bottom action bar */}
        <div
          className="border-t flex items-center justify-end gap-3 px-8 py-4"
          style={{ borderTopColor: 'var(--color-border)' }}
        >
          {isCreating && stagedFiles.length > 0 && (
            <span className="text-xs mr-auto" style={{ color: 'var(--color-text-muted)' }}>
              {uploadProgress < 100 && uploadProgress > 0
                ? `Загрузка файлов… ${uploadProgress}%`
                : uploadProgress >= 100
                ? 'Обработка файлов… это может занять до минуты'
                : 'Загрузка файлов…'}
            </span>
          )}
          {isCreating && stagedFiles.length === 0 && (
            <span className="text-xs mr-auto" style={{ color: 'var(--color-text-muted)' }}>
              Создание дела…
            </span>
          )}
          <button
            onClick={() => navigate('/cases')}
            disabled={isCreating}
            className="px-4 py-2 text-sm font-medium rounded-lg border transition-colors hover:bg-[var(--color-bg-hover)]"
            style={{
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
              backgroundColor: 'transparent',
            }}
          >
            Отмена
          </button>
          <button
            onClick={handleCreate}
            disabled={isCreating || !title.trim()}
            className="px-4 py-2 text-sm font-medium rounded-lg transition-colors"
            style={{
              backgroundColor: isCreating || !title.trim()
                ? 'var(--color-text-muted)'
                : 'var(--color-text-primary)',
              color: 'var(--color-bg-primary)',
              opacity: isCreating || !title.trim() ? 0.5 : 1,
              cursor: isCreating || !title.trim() ? 'not-allowed' : 'pointer',
            }}
          >
            {isCreating ? 'Создание…' : 'Создать дело'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default NewCasePage
