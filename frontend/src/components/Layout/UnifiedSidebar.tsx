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
    <div className="w-[250px] h-screen bg-gradient-to-b from-[#1A1B2E] via-[#1A2332] to-[#1A1B2E] border-r border-[#2A2B3E]/50 flex flex-col relative overflow-hidden">
      {/* Subtle noise overlay for texture */}
      <div 
        className="absolute inset-0 opacity-[0.02] pointer-events-none"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 400 400' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")`,
        }}
      />
      
      {/* Gradient accent on border */}
      <div className="absolute top-0 right-0 w-px h-full bg-gradient-to-b from-transparent via-[#00D4FF]/20 to-transparent" />
      
      {/* Content */}
      <div className="relative z-10 flex flex-col h-full">
        {/* Header */}
        {title && (
          <div className="p-6 border-b border-[#2A2B3E]/50">
            <h1 className="text-xl font-display text-white tracking-tight">
              {title}
            </h1>
          </div>
        )}
        
        {/* Navigation */}
        <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
          {navItems.map((item, index) => {
            const Icon = item.icon
            const active = isActive(item.path)
            
            return (
              <button
                key={item.id}
                onClick={() => navigate(item.path)}
                className={`
                  sidebar-item
                  w-full flex items-center gap-3 px-4 py-3 
                  text-sm font-medium rounded-lg
                  transition-all duration-300 ease-out
                  relative overflow-hidden
                  ${
                    active
                      ? 'bg-gradient-to-r from-[#00D4FF]/15 to-[#7C3AED]/10 text-[#00D4FF] shadow-lg shadow-[#00D4FF]/10'
                      : 'text-[#B0B3C0] hover:text-white hover:bg-[#242538]/50'
                  }
                `}
                style={{
                  animationDelay: `${index * 0.05}s`,
                }}
              >
                {/* Active indicator */}
                {active && (
                  <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-[#00D4FF] to-[#7C3AED] rounded-r-full" />
                )}
                
                {/* Icon */}
                <Icon 
                  className={`w-5 h-5 transition-transform duration-300 ${
                    active ? 'scale-110' : 'group-hover:scale-105'
                  }`}
                />
                
                {/* Label */}
                <span className="flex-1 text-left">{item.label}</span>
                
                {/* Hover shimmer effect */}
                <div className="absolute inset-0 opacity-0 hover:opacity-100 transition-opacity duration-300 bg-gradient-to-r from-transparent via-white/5 to-transparent translate-x-[-100%] hover:translate-x-[100%] transition-transform duration-700" />
              </button>
            )
          })}
        </nav>
      </div>
    </div>
  )
}

export default UnifiedSidebar

