import { useState } from 'react'
import './UploadArea.css'
import { createCase, processCaseFiles, getCase, AnalysisConfig, CaseInfo as CaseInfoType } from '../services/api'
import CaseInfoForm, { CaseInfo } from './Upload/CaseInfoForm'
import DocumentsUploadStep from './Upload/DocumentsUploadStep'
import ProcessingScreen from './Upload/ProcessingScreen'
import { useNavigate } from 'react-router-dom'

interface UploadAreaProps {
  onUpload: (caseId: string, fileNames: string[]) => void
}

type UploadStep = 'info' | 'documents' | 'processing' | 'complete'

const UploadArea = ({ onUpload }: UploadAreaProps) => {
  const [step, setStep] = useState<UploadStep>('info')
  const [caseId, setCaseId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const navigate = useNavigate()

  const handleCaseInfoSubmit = async (info: CaseInfo) => {
    setError(null)

    try {
      // Create case
      const caseInfo: CaseInfoType = {
        title: info.title,
        description: info.description,
      }
      const caseResponse = await createCase(caseInfo)
      setCaseId(caseResponse.id)
      setStep('documents')
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Ошибка при создании дела')
    }
  }

  const handleDocumentsContinue = async () => {
    if (!caseId) {
      setError('Ошибка: ID дела не найден')
      return
    }

    setError(null)
    setStep('processing')

    try {
      // Default analysis config
      const defaultAnalysisConfig: AnalysisConfig = {
        enable_timeline: true,
        enable_entities: true,
        enable_classification: true,
        enable_privilege_check: false,
      }

      // Start processing
      await processCaseFiles(caseId, defaultAnalysisConfig)

      // Poll for completion
      const pollInterval = setInterval(async () => {
        try {
          const caseData = await getCase(caseId)
          if (caseData.status === 'completed') {
            clearInterval(pollInterval)
            handleProcessingComplete()
          } else if (caseData.status === 'failed') {
            clearInterval(pollInterval)
            setError('Ошибка при обработке файлов')
            setStep('documents')
          }
        } catch (err) {
          // Continue polling on error
        }
      }, 2000) // Poll every 2 seconds

      // Timeout after 5 minutes
      setTimeout(() => {
        clearInterval(pollInterval)
      }, 5 * 60 * 1000)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Ошибка при запуске обработки')
      setStep('documents')
    }
  }

  const handleProcessingComplete = () => {
    if (caseId) {
      onUpload(caseId, [])
      navigate(`/cases/${caseId}/chat`)
    }
  }

  const handleCancel = () => {
    setStep('info')
    setCaseId(null)
    setError(null)
  }

  if (step === 'info') {
    return (
      <>
        {error && (
          <div className="auth-error" style={{ margin: '16px auto', maxWidth: '600px', padding: '12px', borderRadius: '8px', background: '#fee', border: '1px solid #fcc' }}>
            {error}
          </div>
        )}
        <CaseInfoForm
          onSubmit={handleCaseInfoSubmit}
          onCancel={handleCancel}
        />
      </>
    )
  }

  if (step === 'documents' && caseId) {
    return (
      <DocumentsUploadStep
        caseId={caseId}
        onContinue={handleDocumentsContinue}
        onCancel={handleCancel}
      />
    )
  }

  if (step === 'processing') {
    return (
      <>
        {error && (
          <div className="auth-error" style={{ margin: '16px auto', maxWidth: '600px', padding: '12px', borderRadius: '8px', background: '#fee', border: '1px solid #fcc' }}>
            {error}
          </div>
        )}
        <ProcessingScreen
          caseId={caseId || ''}
          onComplete={handleProcessingComplete}
        />
      </>
    )
  }

  return null
}

export default UploadArea
