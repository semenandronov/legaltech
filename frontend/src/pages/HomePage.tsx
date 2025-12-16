import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import UploadArea from '../components/UploadArea'
import ChatWindow from '../components/ChatWindow'
import CaseSidebar from '../components/CaseSidebar'
import { useAuth } from '../contexts/AuthContext'
import '../App.css'

const HomePage = () => {
  const [caseId, setCaseId] = useState<string | null>(null)
  const [fileNames, setFileNames] = useState<string[]>([])
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleUpload = (newCaseId: string, names: string[]) => {
    setCaseId(newCaseId)
    setFileNames(names)
  }

  const handleBack = () => {
    setCaseId(null)
    setFileNames([])
  }

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <div className="app-root">
      <div className="app-shell">
        <header className="app-header">
          <div className="app-header-left">
            <h1 className="app-title">
              <span className="app-title-icon">⚖️</span>
              Legal AI Vault
            </h1>
            <p className="app-subtitle">
              Анализируйте юридические документы в тёмном, минималистичном AI-чате
              Perplexity-стиля.
            </p>
          </div>
          <div className="app-header-right">
            {user && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                <span style={{ color: '#a0aec0' }}>{user.email}</span>
                <button
                  onClick={handleLogout}
                  style={{
                    padding: '8px 16px',
                    background: '#4a5568',
                    color: 'white',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: 'pointer',
                  }}
                >
                  Выход
                </button>
              </div>
            )}
            {caseId && (
              <button className="back-button" onClick={handleBack}>
                <span>←</span>
                <span>Новое дело</span>
              </button>
            )}
          </div>
        </header>

        <main className="app-main">
          {caseId ? (
            <>
              <div className="sidebar-column">
                <CaseSidebar caseId={caseId} fileNames={fileNames} />
              </div>
              <div className="chat-column">
                <ChatWindow caseId={caseId} fileNames={fileNames} />
              </div>
            </>
          ) : (
            <div className="chat-column upload-wrapper">
              <UploadArea onUpload={handleUpload} />
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

export default HomePage

