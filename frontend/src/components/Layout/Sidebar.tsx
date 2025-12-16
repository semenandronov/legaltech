import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import './Layout.css'

const Sidebar = () => {
  const { logout, user } = useAuth()
  const navigate = useNavigate()
  const [isCollapsed, setIsCollapsed] = useState(false)

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <aside className={`sidebar ${isCollapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-header">
        {!isCollapsed && (
          <div className="sidebar-brand">
            <span className="sidebar-brand-icon">⚖️</span>
            <span className="sidebar-brand-text">Legal AI</span>
          </div>
        )}
        <button
          className="sidebar-toggle"
          onClick={() => setIsCollapsed(!isCollapsed)}
          aria-label={isCollapsed ? 'Развернуть' : 'Свернуть'}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
            {isCollapsed ? (
              <path d="M6 12L10 8L6 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            ) : (
              <path d="M10 12L6 8L10 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            )}
          </svg>
        </button>
      </div>
      
      {!isCollapsed && (
        <>
          <nav className="sidebar-nav">
            <NavLink to="/" className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}>
              <span className="sidebar-link-icon">📊</span>
              <span className="sidebar-link-text">Dashboard</span>
            </NavLink>
            <NavLink
              to="/settings"
              className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
            >
              <span className="sidebar-link-icon">⚙️</span>
              <span className="sidebar-link-text">Настройки</span>
            </NavLink>
          </nav>
          
          <div className="sidebar-footer">
            {user && (
              <div className="sidebar-user">
                <div className="sidebar-user-avatar">
                  {user.full_name?.[0]?.toUpperCase() || user.email[0].toUpperCase()}
                </div>
                <div className="sidebar-user-info">
                  <div className="sidebar-user-name">{user.full_name || user.email}</div>
                  {user.company && (
                    <div className="sidebar-user-company">{user.company}</div>
                  )}
                </div>
              </div>
            )}
            <button className="sidebar-logout" onClick={handleLogout}>
              <span className="sidebar-link-icon">🚪</span>
              <span className="sidebar-link-text">Выход</span>
            </button>
          </div>
        </>
      )}
    </aside>
  )
}

export default Sidebar

