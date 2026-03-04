import { useNavigate, useLocation } from 'react-router-dom'
import { LucideIcon, FolderOpen, ChevronLeft, ChevronRight } from 'lucide-react'
import { useState, useEffect } from 'react'

interface NavItem {
  id: string
  label: string
  icon: LucideIcon
  path: string
}

interface UnifiedSidebarProps {
  navItems: NavItem[]
  title?: string
  showBackButton?: boolean
  forceCollapsed?: boolean
}

const SIDEBAR_STATE_KEY = 'unified-sidebar-collapsed'

const UnifiedSidebar = ({ navItems, title = 'Legal AI', showBackButton = true, forceCollapsed = false }: UnifiedSidebarProps) => {
  const navigate = useNavigate()
  const location = useLocation()
  const [userCollapsed, setUserCollapsed] = useState(() => {
    const saved = localStorage.getItem(SIDEBAR_STATE_KEY)
    return saved === 'true'
  })
  const isCollapsed = forceCollapsed || userCollapsed

  const isActive = (path: string) => {
    return location.pathname === path || location.pathname.startsWith(path + '/')
  }

  const shouldShowBackButton = showBackButton && location.pathname.includes('/cases/') && location.pathname !== '/cases'

  useEffect(() => {
    localStorage.setItem(SIDEBAR_STATE_KEY, String(userCollapsed))
  }, [userCollapsed])

  const toggleCollapse = () => {
    setUserCollapsed((prev: boolean) => !prev)
  }

  return (
    <div
      className={`h-screen bg-bg-secondary border-r border-border flex flex-col relative overflow-hidden transition-all duration-200 ease-in-out shrink-0 ${
        isCollapsed ? 'w-[70px]' : 'w-[250px]'
      }`}
      style={{ backgroundColor: 'var(--color-bg-secondary)' }}
    >
      <div className="relative z-10 flex flex-col h-full">
        {/* Header */}
        {title && (
          <div
            className="border-b border-border flex items-center justify-between"
            style={{
              padding: 'var(--space-4)',
              borderBottomColor: 'var(--color-border)'
            }}
          >
            {!isCollapsed && (
              <h1
                className="text-xl font-display text-text-primary tracking-tight flex-1"
                style={{
                  fontFamily: 'var(--font-display)',
                  color: 'var(--color-text-primary)',
                  letterSpacing: 'var(--tracking-tight)',
                  fontWeight: 700,
                }}
              >
                {title}
              </h1>
            )}
            {isCollapsed && (
              <div className="flex-1 flex justify-center">
                <div className="text-xl">⚖️</div>
              </div>
            )}
            <button
              onClick={toggleCollapse}
              className="p-2 rounded-md hover:bg-bg-hover transition-colors flex items-center justify-center"
              style={{
                color: 'var(--color-text-secondary)',
              }}
              aria-label={isCollapsed ? 'Развернуть меню' : 'Свернуть меню'}
            >
              {isCollapsed ? (
                <ChevronRight className="w-5 h-5" />
              ) : (
                <ChevronLeft className="w-5 h-5" />
              )}
            </button>
          </div>
        )}

        {/* Navigation */}
        <nav className="flex-1 p-4 space-y-1 overflow-y-auto overflow-x-hidden" style={{ padding: isCollapsed ? 'var(--space-2)' : 'var(--space-4)' }}>
          {shouldShowBackButton && (
            <button
              onClick={() => navigate('/cases')}
              className={`
                w-full flex items-center overflow-hidden ${isCollapsed ? 'justify-center px-2 py-3' : 'gap-3 px-4 py-3'}
                text-sm font-medium rounded-md
                transition-all duration-150
                mb-2
                text-text-secondary hover:text-text-primary hover:bg-bg-hover
              `}
              style={{
                backgroundColor: 'transparent',
                color: 'var(--color-text-secondary)',
              }}
            >
              <FolderOpen
                className="w-5 h-5 flex-shrink-0"
                style={{ color: 'var(--color-text-secondary)' }}
              />
              {!isCollapsed && <span className="flex-1 text-left">Дела</span>}
            </button>
          )}

          {navItems.map((item) => {
            const Icon = item.icon
            const active = isActive(item.path)

            return (
              <button
                key={item.id}
                onClick={() => navigate(item.path)}
                className={`
                  w-full flex items-center overflow-hidden ${isCollapsed ? 'justify-center px-2 py-3' : 'gap-3 px-4 py-3'}
                  text-sm font-medium rounded-md
                  transition-all duration-150
                  relative
                  ${
                    active
                      ? 'bg-bg-active text-text-primary'
                      : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
                  }
                `}
                style={{
                  backgroundColor: active ? 'var(--color-bg-active)' : 'transparent',
                  color: active ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
                }}
              >
                {active && (
                  <div
                    className="absolute left-0 top-0 bottom-0 w-0.5 bg-accent rounded-r-full"
                    style={{ backgroundColor: 'var(--color-accent)' }}
                  />
                )}
                <Icon
                  className="w-5 h-5 flex-shrink-0"
                  style={{
                    color: active ? 'var(--color-text-primary)' : 'var(--color-text-secondary)'
                  }}
                />
                {!isCollapsed && <span className="flex-1 text-left">{item.label}</span>}
              </button>
            )
          })}
        </nav>
      </div>
    </div>
  )
}

export default UnifiedSidebar
