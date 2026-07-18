import { useState } from 'react'
import './UploadArea.css'
import { createCase, CaseInfo as CaseInfoType } from '../services/api'
import CaseInfoForm, { CaseInfo } from './Upload/CaseInfoForm'
import DocumentsUploadStep from './Upload/DocumentsUploadStep'
import { useNavigate } from 'react-router-dom'
import { caseHomePath } from '../lib/productFeatures'

interface UploadAreaProps {
  onUpload: (caseId: string, fileNames: string[]) => void
  onCancel?: () => void
}

type UploadStep = 'info' | 'documents'

const UploadArea = ({ onUpload, onCancel }: UploadAreaProps) => {
  const [step, setStep] = useState<UploadStep>('info')
  const [caseId, setCaseId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const navigate = useNavigate()

  const handleCaseInfoSubmit = async (info: CaseInfo) => {
    setError(null)

    try {
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

  const handleDocumentsContinue = () => {
    if (!caseId) {
      setError('Ошибка: ID дела не найден')
      return
    }
    // Files are already uploaded, indexed, and case.status is "completed"
    onUpload(caseId, [])
    navigate(caseHomePath(caseId))
  }

  const handleCancel = () => {
    if (step === 'info' && onCancel) {
      onCancel()
    } else {
      setStep('info')
      setCaseId(null)
      setError(null)
    }
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

  return null
}

export default UploadArea
