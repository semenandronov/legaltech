import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import UploadArea from '../UploadArea'
import './Layout.css'

const Header = () => {
  const { user } = useAuth()
  const [showUploadModal, setShowUploadModal] = useState(false)
  const navigate = useNavigate()

  const handleUpload = (caseId: string, fileNames: string[]) => {
    setShowUploadModal(false)
    navigate(`/cases/${caseId}/chat`)
    // Перезагрузить страницу для обновления списка дел
    window.location.reload()
  }

  return (
    <>
      <header className="layout-header">
        <div className="layout-header-left">
          <h1 className="layout-header-title">
            <span className="layout-header-icon">⚖️</span>
            Legal AI Vault
          </h1>
        </div>
        <div className="layout-header-right">
          <button
            className="layout-header-upload-button"
            onClick={() => setShowUploadModal(true)}
            style={{
              padding: '10px 20px',
              background: '#4299e1',
              color: 'white',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: '500',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              marginRight: '16px',
            }}
          >
            <span>📄</span>
            <span>Загрузить новое дело</span>
          </button>
          {user && (
            <div className="layout-header-user">
              <span className="layout-header-user-name">{user.full_name || user.email}</span>
              {user.company && (
                <span className="layout-header-user-company">{user.company}</span>
              )}
            </div>
          )}
        </div>
      </header>

      {showUploadModal && (
        <div
          className="upload-modal-overlay"
          onClick={() => setShowUploadModal(false)}
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0, 0, 0, 0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            className="upload-modal-content"
            onClick={(e) => e.stopPropagation()}
            style={{
              background: '#1a202c',
              borderRadius: '12px',
              padding: '24px',
              maxWidth: '600px',
              width: '90%',
              maxHeight: '90vh',
              overflow: 'auto',
              position: 'relative',
            }}
          >
            <button
              onClick={() => setShowUploadModal(false)}
              style={{
                position: 'absolute',
                top: '16px',
                right: '16px',
                background: 'transparent',
                border: 'none',
                color: '#a0aec0',
                fontSize: '24px',
                cursor: 'pointer',
                padding: '4px 8px',
              }}
            >
              ×
            </button>
            <UploadArea onUpload={handleUpload} />
          </div>
        </div>
      )}
    </>
  )
}

export default Header

