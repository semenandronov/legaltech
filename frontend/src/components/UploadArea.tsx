import { useState, useRef } from 'react'
import axios from 'axios'
import './UploadArea.css'

// Используем относительный путь, так как frontend и backend на одном домене
const API_URL = import.meta.env.VITE_API_URL || ''

interface UploadAreaProps {
  onUpload: (caseId: string, fileNames: string[]) => void
}

const UploadArea = ({ onUpload }: UploadAreaProps) => {
  const [isLoading, setIsLoading] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

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
      handleFiles(Array.from(e.dataTransfer.files))
    }
  }

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(Array.from(e.target.files))
    }
  }

  const handleFiles = async (files: File[]) => {
    setIsLoading(true)
    setError(null)

    const formData = new FormData()
    files.forEach((file) => {
      formData.append('files', file)
    })

    try {
      const response = await axios.post(`${API_URL}/api/upload`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })

      if (response.data.status === 'success') {
        onUpload(response.data.case_id, response.data.file_names)
      } else {
        setError(response.data.message || 'Ошибка при загрузке файлов')
      }
    } catch (err: any) {
      if (err.response?.data?.detail) {
        setError(err.response.data.detail)
      } else {
        setError('Ошибка при загрузке файлов. Проверьте что backend запущен на http://localhost:8000')
      }
    } finally {
      setIsLoading(false)
    }
  }

  const handleClick = () => {
    fileInputRef.current?.click()
  }

  return (
    <div
      className={`upload-area ${dragActive ? 'drag-active' : ''} ${isLoading ? 'loading' : ''}`}
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
        accept=".pdf,.docx,.txt,.xlsx"
        onChange={handleFileInput}
        style={{ display: 'none' }}
      />
      
      {isLoading ? (
        <>
          <div className="spinner"></div>
          <p className="upload-text">Загружаем документы...</p>
        </>
      ) : (
        <>
          <div className="upload-icon">📄 📄 📄</div>
          <p className="upload-text">Перетащите документы сюда</p>
          <p className="upload-subtext">или нажмите для выбора файлов</p>
          <p className="supported">Поддерживаемые форматы: PDF, DOCX, TXT, XLSX</p>
        </>
      )}

      {error && (
        <div className="error-message">{error}</div>
      )}
    </div>
  )
}

export default UploadArea

