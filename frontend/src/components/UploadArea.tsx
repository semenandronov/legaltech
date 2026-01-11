import { useState, useRef } from 'react'
import './UploadArea.css'
import { uploadFiles, AnalysisConfig } from '../services/api'
import CaseInfoForm, { CaseInfo } from './Upload/CaseInfoForm'
import ProcessingScreen from './Upload/ProcessingScreen'
import { useNavigate } from 'react-router-dom'

const MAX_FILE_SIZE_MB = 5
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

interface UploadAreaProps {
  onUpload: (caseId: string, fileNames: string[]) => void
}

type UploadStep = 'files' | 'info' | 'processing' | 'complete'

const UploadArea = ({ onUpload }: UploadAreaProps) => {
  const [step, setStep] = useState<UploadStep>('files')
  const [files, setFiles] = useState<File[]>([])
  const [caseId, setCaseId] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

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

  const handleFiles = (selectedFiles: File[]) => {
    setError(null)

    // Validate that files were selected
    if (!selectedFiles || selectedFiles.length === 0) {
      setError('Пожалуйста, выберите хотя бы один файл')
      return
    }

    // Validate file sizes
    const tooBig = selectedFiles.find((file) => file.size > MAX_FILE_SIZE_BYTES)
    if (tooBig) {
      setError(`Файл '${tooBig.name}' слишком большой. Максимальный размер: ${MAX_FILE_SIZE_MB} МБ.`)
      return
    }

    setFiles(selectedFiles)
    setStep('info')
  }

  const handleCaseInfoSubmit = async (info: CaseInfo) => {
    // Убираем шаг выбора типа анализа, сразу начинаем загрузку с дефолтными настройками
    if (files.length === 0) {
      setError('Пожалуйста, выберите файлы для загрузки')
      setStep('files')
      return
    }

    setStep('processing')
    setError(null)
    setUploadProgress(0)

    // Используем дефолтные значения анализа (те же, что были в AnalysisOptions)
    const defaultAnalysisConfig: AnalysisConfig = {
      enable_timeline: true,
      enable_entities: true,  // key_facts
      enable_classification: true,  // discrepancies
      enable_privilege_check: false,  // risk_analysis
    }

    try {
      const result = await uploadFiles(files, info, defaultAnalysisConfig, setUploadProgress)
      setCaseId(result.caseId)
      // onUpload will be called after processing completes
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Ошибка при загрузке файлов')
      setStep('files')
    }
  }

  const handleProcessingComplete = () => {
    if (caseId) {
      onUpload(caseId, files.map(f => f.name))
      navigate(`/cases/${caseId}/chat`)
    }
  }

  const handleClick = () => {
    fileInputRef.current?.click()
  }

  if (step === 'info') {
    return (
      <CaseInfoForm
        onSubmit={handleCaseInfoSubmit}
        onCancel={() => {
          setStep('files')
          setFiles([])
        }}
      />
    )
  }

  if (step === 'processing') {
    return (
      <ProcessingScreen
        caseId={caseId || ''}
        onComplete={handleProcessingComplete}
        uploadProgress={uploadProgress}
      />
    )
  }

  return (
    <div
      className={`upload-area ${dragActive ? 'drag-active' : ''}`}
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
        style={{ display: 'none' }}
      />

      <div className="upload-icon">📄 📄 📄</div>
      <p className="upload-text">Перетащите документы сюда</p>
      <p className="upload-subtext">или нажмите для выбора файлов</p>

      {error && <div className="error-message">{error}</div>}
    </div>
  )
}

export default UploadArea
