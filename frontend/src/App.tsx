import { useState } from 'react'
import UploadArea from './components/UploadArea'
import ChatWindow from './components/ChatWindow'
import './App.css'

function App() {
  const [caseId, setCaseId] = useState<string | null>(null)
  const [fileNames, setFileNames] = useState<string[]>([])

  const handleUpload = (newCaseId: string, names: string[]) => {
    setCaseId(newCaseId)
    setFileNames(names)
  }

  const handleBack = () => {
    setCaseId(null)
    setFileNames([])
  }

  return (
    <div className="app-container">
      <div className="app-header">
        <h1 className="app-title">📄 Legal AI Vault</h1>
        {caseId && (
          <button className="back-button" onClick={handleBack}>
            ← Загрузить новые документы
          </button>
        )}
      </div>
      <div className="app-main">
        {!caseId ? (
          <div className="panel left-panel">
            <UploadArea onUpload={handleUpload} />
          </div>
        ) : (
          <div className="panel right-panel">
            <ChatWindow caseId={caseId} fileNames={fileNames} />
          </div>
        )}
      </div>
    </div>
  )
}

export default App

