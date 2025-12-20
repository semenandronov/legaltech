import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import UploadArea from '../UploadArea'
import ThemeToggle from '../UI/ThemeToggle'
import Modal from '../UI/Modal'
import Button from '../UI/Button'

const Header = () => {
  const { user } = useAuth()
  const [showUploadModal, setShowUploadModal] = useState(false)
  const navigate = useNavigate()

  const handleUpload = (caseId: string, _fileNames: string[]) => {
    setShowUploadModal(false)
    navigate(`/cases/${caseId}/workspace`)
    window.location.reload()
  }

  return (
    <>
      <header className="bg-secondary border-b border-border px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-h2 text-primary flex items-center gap-2">
              <span>⚖️</span>
            Legal AI Vault
          </h1>
        </div>
          <div className="flex items-center gap-4">
            <Button variant="primary" onClick={() => setShowUploadModal(true)}>
              <span className="mr-2">📄</span>
              Загрузить новое дело
            </Button>
            <ThemeToggle />
          {user && (
              <div className="flex flex-col items-end">
                <span className="text-body text-primary font-medium">{user.full_name || user.email}</span>
              {user.company && (
                  <span className="text-small text-secondary">{user.company}</span>
              )}
            </div>
          )}
          </div>
        </div>
      </header>

      <Modal
        isOpen={showUploadModal}
        onClose={() => setShowUploadModal(false)}
        title="Загрузить новое дело"
        size="lg"
      >
            <UploadArea onUpload={handleUpload} />
      </Modal>
    </>
  )
}

export default Header