import { useAuth } from '../../contexts/AuthContext'
import './Layout.css'

const Header = () => {
  const { user } = useAuth()

  return (
    <header className="layout-header">
      <div className="layout-header-left">
        <h1 className="layout-header-title">
          <span className="layout-header-icon">⚖️</span>
          Legal AI Vault
        </h1>
      </div>
      <div className="layout-header-right">
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
  )
}

export default Header

