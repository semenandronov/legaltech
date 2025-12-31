import { useNavigate, useLocation } from 'react-router-dom'
import { MessageSquare, FileText, Table } from 'lucide-react'

interface CaseNavigationProps {
  caseId: string
}

const CaseNavigation = ({ caseId }: CaseNavigationProps) => {
  const navigate = useNavigate()
  const location = useLocation()
  
  const navItems = [
    { id: 'chat', label: 'Ассистент', icon: MessageSquare, path: `/cases/${caseId}/chat` },
    { id: 'documents', label: 'Документы', icon: FileText, path: `/cases/${caseId}/documents` },
    { id: 'tabular-review', label: 'Tabular Review', icon: Table, path: `/cases/${caseId}/tabular-review` },
  ]
  
  const isActive = (path: string) => {
    return location.pathname === path || location.pathname.startsWith(path + '/')
  }
  
  return (
    <div className="w-[250px] h-screen bg-secondary border-r border-border flex flex-col">
      <div className="p-4 space-y-1">
        {navItems.map((item) => {
          const Icon = item.icon
          const active = isActive(item.path)
          
          return (
            <button
              key={item.id}
              onClick={() => navigate(item.path)}
              className={`w-full flex items-center gap-3 px-3 py-2 text-body font-medium rounded-md transition-colors ${
                active
                  ? 'bg-primary bg-opacity-10 text-primary'
                  : 'text-secondary hover:text-primary hover:bg-tertiary'
              }`}
            >
              <Icon className="w-5 h-5" />
              <span>{item.label}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default CaseNavigation
