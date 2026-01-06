import { useNavigate, useLocation } from 'react-router-dom'
import { LucideIcon } from 'lucide-react'

interface NavItem {
  id: string
  label: string
  icon: LucideIcon
  path: string
}

interface UnifiedSidebarProps {
  navItems: NavItem[]
  title?: string
}

const UnifiedSidebar = ({ navItems, title = 'Legal AI' }: UnifiedSidebarProps) => {
  const navigate = useNavigate()
  const location = useLocation()
  
  const isActive = (path: string) => {
    return location.pathname === path || location.pathname.startsWith(path + '/')
  }
  
  return (
    <div 
      className="w-[250px] h-screen bg-bg-secondary border-r border-border flex flex-col relative overflow-hidden"
      style={{ backgroundColor: 'var(--color-bg-secondary)' }}
    >
      {/* Content */}
      <div className="relative z-10 flex flex-col h-full">
        {/* Header */}
        {title && (
          <div 
            className="p-6 border-b border-border"
            style={{ 
              padding: 'var(--space-6)',
              borderBottomColor: 'var(--color-border)'
            }}
          >
            <h1 
              className="text-xl font-display text-text-primary tracking-tight"
              style={{ 
                fontFamily: 'var(--font-display)',
                color: 'var(--color-text-primary)',
                letterSpacing: 'var(--tracking-tight)'
              }}
            >
              {title}
            </h1>
          </div>
        )}
        
        {/* Navigation */}
        <nav className="flex-1 p-4 space-y-1 overflow-y-auto" style={{ padding: 'var(--space-4)' }}>
          {navItems.map((item) => {
            const Icon = item.icon
            const active = isActive(item.path)
            
            return (
              <button
                key={item.id}
                onClick={() => navigate(item.path)}
                className={`
                  w-full flex items-center gap-3 px-4 py-3 
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
                {/* Active indicator - subtle left border */}
                {active && (
                  <div 
                    className="absolute left-0 top-0 bottom-0 w-0.5 bg-accent rounded-r-full"
                    style={{ backgroundColor: 'var(--color-accent)' }}
                  />
                )}
                
                {/* Icon */}
                <Icon 
                  className="w-5 h-5"
                  style={{ 
                    color: active ? 'var(--color-text-primary)' : 'var(--color-text-secondary)'
                  }}
                />
                
                {/* Label */}
                <span className="flex-1 text-left">{item.label}</span>
              </button>
            )
          })}
        </nav>
      </div>
    </div>
  )
}

export default UnifiedSidebar


