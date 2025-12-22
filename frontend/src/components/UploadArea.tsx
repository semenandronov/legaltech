import { useState, useRef } from 'react'
import './UploadArea.css'
import { uploadFiles, AnalysisConfig } from '../services/api'
import CaseInfoForm, { CaseInfo } from './Upload/CaseInfoForm'
import AnalysisOptions, { AnalysisOptions as AnalysisOptionsType } from './Upload/AnalysisOptions'
import ProcessingScreen from './Upload/ProcessingScreen'
import { useNavigate } from 'react-router-dom'

const MAX_FILE_SIZE_MB = 5
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

interface UploadAreaProps {
  onUpload: (caseId: string, fileNames: string[]) => void
}

type UploadStep = 'files' | 'info' | 'analysis' | 'processing' | 'complete'

const UploadArea = ({ onUpload }: UploadAreaProps) => {
  const [step, setStep] = useState<UploadStep>('files')
  const [files, setFiles] = useState<File[]>([])
  const [caseInfo, setCaseInfo] = useState<CaseInfo | null>(null)
  const [caseId, setCaseId] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
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

  const handleCaseInfoSubmit = (info: CaseInfo) => {
    setCaseInfo(info)
    setStep('analysis')
  }

  const handleAnalysisSubmit = async (options: AnalysisOptionsType) => {
    if (files.length === 0) {
      setError('Пожалуйста, выберите файлы для загрузки')
      setStep('files')
      return
    }

    setStep('processing')
    setError(null)

    // Upload files with metadata
    try {
      // Convert AnalysisOptions to AnalysisConfig
      const analysisConfig: AnalysisConfig = {
        enable_timeline: options.timeline,
        enable_entities: options.key_facts,
        enable_classification: options.discrepancies,
        enable_privilege_check: options.risk_analysis,
      }
      const result = await uploadFiles(files, caseInfo, analysisConfig)
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

  if (step === 'analysis') {
    return (
      <AnalysisOptions
        onSubmit={handleAnalysisSubmit}
        onBack={() => setStep('info')}
      />
    )
  }

  if (step === 'processing') {
    return (
      <ProcessingScreen
        caseId={caseId || ''}
        onComplete={handleProcessingComplete}
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
        accept=".pdf,.docx,.txt,.xlsx"
        onChange={handleFileInput}
        style={{ display: 'none' }}
      />

      <div className="upload-icon">📄 📄 📄</div>
      <p className="upload-text">Перетащите документы сюда</p>
      <p className="upload-subtext">или нажмите для выбора файлов</p>
      <p className="supported">Поддерживаемые форматы: PDF, DOCX, TXT, XLSX</p>

      {error && <div className="error-message">{error}</div>}
    </div>
  )
}

export default UploadArea
