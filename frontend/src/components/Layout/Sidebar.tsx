import { useState, useEffect } from 'react'
import { NavLink, useNavigate, useLocation } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Home, Settings, LogOut, Moon, Sun } from 'lucide-react'
import { useAuth } from '../../contexts/AuthContext'
import { useTheme } from '../../contexts/ThemeContext'
import Button from '../UI/Button'

const Sidebar = () => {
  const { logout, user } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()
  const location = useLocation()
  const [isCollapsed, setIsCollapsed] = useState(false)

  useEffect(() => {
    const root = document.querySelector('.dashboard-root') as HTMLElement
    if (root) {
      root.setAttribute('data-sidebar-collapsed', String(isCollapsed))
    }
  }, [isCollapsed])

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }
  
  const navItems = [
    { to: '/cases', icon: Home, label: 'Дела' },
    { to: '/settings', icon: Settings, label: 'Настройки' },
  ]

  return (
    <aside className={`bg-secondary border-r border-border flex flex-col transition-all duration-300 fixed left-0 top-0 h-screen z-50 ${
      isCollapsed ? 'w-[60px]' : 'w-[260px]'
    }`}>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-border min-h-[56px]">
        {!isCollapsed && (
          <div className="flex items-center gap-2">
            <span className="text-xl">⚖️</span>
            <span className="text-body font-semibold text-primary">Legal AI</span>
          </div>
        )}
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="p-1 hover:bg-tertiary rounded transition-colors"
          aria-label={isCollapsed ? 'Развернуть' : 'Свернуть'}
        >
            {isCollapsed ? (
            <ChevronRight className="w-4 h-4 text-secondary" />
            ) : (
            <ChevronLeft className="w-4 h-4 text-secondary" />
            )}
        </button>
      </div>
      
      {/* Navigation */}
      {!isCollapsed && (
        <>
          <nav className="flex-1 p-4 space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon
              const isActive = location.pathname === item.to || location.pathname.startsWith(item.to + '/')
              
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={`flex items-center gap-3 px-3 py-2 text-body font-medium rounded-md transition-colors ${
                    isActive
                      ? 'bg-primary bg-opacity-10 text-primary'
                      : 'text-secondary hover:text-primary hover:bg-tertiary'
                  }`}
                >
                  <Icon className="w-5 h-5" />
                  <span>{item.label}</span>
                </NavLink>
              )
            })}
          </nav>
          
          {/* Footer */}
          <div className="p-4 border-t border-border space-y-3">
            {user && (
              <div className="flex items-center gap-3 px-3 py-2">
                <div className="w-8 h-8 rounded-full bg-primary bg-opacity-20 flex items-center justify-center text-small font-semibold text-primary">
                  {user.full_name?.[0]?.toUpperCase() || user.email[0].toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-body font-medium text-primary truncate">
                    {user.full_name || user.email}
                  </div>
                  {user.company && (
                    <div className="text-small text-secondary truncate">{user.company}</div>
                  )}
                </div>
              </div>
            )}
            <button
              onClick={toggleTheme}
              className="flex items-center gap-3 px-3 py-2 w-full text-body font-medium rounded-md transition-colors text-secondary hover:text-primary hover:bg-tertiary"
              aria-label={theme === 'dark' ? 'Переключить на светлую тему' : 'Переключить на темную тему'}
            >
              {theme === 'dark' ? (
                <>
                  <Sun className="w-5 h-5" />
                  <span>Светлая тема</span>
                </>
              ) : (
                <>
                  <Moon className="w-5 h-5" />
                  <span>Темная тема</span>
                </>
              )}
            </button>
            <Button
              variant="secondary"
              className="w-full justify-start"
              onClick={handleLogout}
            >
              <LogOut className="w-4 h-4 mr-2" />
              Выход
            </Button>
          </div>
        </>
      )}
      
      {/* Collapsed state icons */}
      {isCollapsed && (
        <nav className="flex-1 p-2 space-y-2">
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive = location.pathname === item.to || location.pathname.startsWith(item.to + '/')
            
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={`flex items-center justify-center p-2 rounded-md transition-colors ${
                  isActive
                    ? 'bg-primary bg-opacity-10 text-primary'
                    : 'text-secondary hover:text-primary hover:bg-tertiary'
                }`}
                title={item.label}
              >
                <Icon className="w-5 h-5" />
              </NavLink>
            )
          })}
        </nav>
      )}
    </aside>
  )
}

export default Sidebar