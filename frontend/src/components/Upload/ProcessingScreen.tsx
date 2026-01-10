import { useEffect } from 'react'
import './Upload.css'

interface ProcessingScreenProps {
  caseId?: string  // Optional, not currently used
  onComplete: () => void
  uploadProgress?: number  // Real upload progress (0-100)
}

const ProcessingScreen = ({ onComplete, uploadProgress }: ProcessingScreenProps) => {
  useEffect(() => {
    // Wait for upload to complete, then call onComplete
    if (uploadProgress !== undefined && uploadProgress >= 100) {
      const timer = setTimeout(() => {
        onComplete()
      }, 1000)
      return () => clearTimeout(timer)
    }
  }, [uploadProgress, onComplete])

  return (
    <div className="processing-screen">
      <div className="processing-screen-content">
        <h2 className="processing-title">⏳ Анализ в процессе</h2>
        <p className="processing-subtitle">
          Это может занять несколько минут..
        </p>
      </div>
    </div>
  )
}

export default ProcessingScreen

