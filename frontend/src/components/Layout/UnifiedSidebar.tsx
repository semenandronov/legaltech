import { useNavigate, useLocation } from 'react-router-dom'
import { LucideIcon, FolderOpen, ChevronLeft, ChevronRight, Scale, Workflow, FileText, Gavel } from 'lucide-react'
import { useState, useEffect } from 'react'
import { fetchLegalCorpusStatus } from '../../services/api'
import { useAuth } from '../../contexts/AuthContext'
import { canAccessInternalDevTools } from '../../utils/internalDevToolsAccess'
import './UnifiedSidebar.css'

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
const LEGAL_CORPUS_UPLOADER_CACHE_KEY = 'legal-corpus-is-uploader'
const UnifiedSidebar = ({ navItems, title = 'Legal AI', showBackButton = true, forceCollapsed = false }: UnifiedSidebarProps) => {
  const navigate = useNavigate()
  const location = useLocation()
  const { user } = useAuth()
  const showInternalSidebarLinks = canAccessInternalDevTools(user?.email)
  const [userCollapsed, setUserCollapsed] = useState(() => {
    const saved = localStorage.getItem(SIDEBAR_STATE_KEY)
    return saved === 'true'
  })
  const [showLegalCorpusItem, setShowLegalCorpusItem] = useState(() => {
    return localStorage.getItem(LEGAL_CORPUS_UPLOADER_CACHE_KEY) === '1'
  })
  const isCollapsed = forceCollapsed || userCollapsed

  const isActive = (path: string) => {
    return location.pathname === path || location.pathname.startsWith(path + '/')
  }

  const shouldShowBackButton = showBackButton && location.pathname.includes('/cases/') && location.pathname !== '/cases'
  const hasWorkflowItem = navItems.some((item) => item.path === '/workflows' || item.id === 'workflows')
  const renderedNavItems = hasWorkflowItem
    ? navItems
    : [...navItems, { id: 'workflows', label: 'Workflows', icon: Workflow, path: '/workflows' }]

  useEffect(() => {
    localStorage.setItem(SIDEBAR_STATE_KEY, String(userCollapsed))
  }, [userCollapsed])

  useEffect(() => {
    let active = true
    const loadLegalCorpusStatus = async () => {
      try {
        const status = await fetchLegalCorpusStatus()
        const isUploader = Boolean(status.is_uploader)
        if (active) setShowLegalCorpusItem(isUploader)
        localStorage.setItem(LEGAL_CORPUS_UPLOADER_CACHE_KEY, isUploader ? '1' : '0')
      } catch {
        // Keep last known value to avoid flickering permission on transient API errors.
        if (active) {
          setShowLegalCorpusItem(localStorage.getItem(LEGAL_CORPUS_UPLOADER_CACHE_KEY) === '1')
        }
      }
    }
    void loadLegalCorpusStatus()
    return () => {
      active = false
    }
  }, [])

  const toggleCollapse = () => {
    setUserCollapsed((prev: boolean) => !prev)
  }

  const navPad = isCollapsed ? 'var(--space-2)' : 'var(--space-4)'

  return (
    <div
      className={`unified-sidebar h-screen flex flex-col relative overflow-hidden transition-all duration-200 ease-in-out shrink-0 ${
        isCollapsed ? 'w-[70px]' : 'w-[250px]'
      }`}
    >
      <div className="relative z-10 flex flex-col h-full">
        {title && (
          <div
            className="unified-sidebar__header flex items-center justify-between"
            style={{ padding: 'var(--space-4)' }}
          >
            {!isCollapsed && (
              <h1 className="unified-sidebar__title flex-1">
                {title}
              </h1>
            )}
            {isCollapsed && (
              <div className="flex-1 flex justify-center">
                <div className="text-xl" aria-hidden>
                  ⚖️
                </div>
              </div>
            )}
            <button
              type="button"
              onClick={toggleCollapse}
              className="unified-sidebar__toggle p-2 flex items-center justify-center"
              aria-label={isCollapsed ? 'Развернуть меню' : 'Свернуть меню'}
            >
              {isCollapsed ? (
                <ChevronRight className="w-5 h-5" aria-hidden />
              ) : (
                <ChevronLeft className="w-5 h-5" aria-hidden />
              )}
            </button>
          </div>
        )}

        <nav
          className="flex-1 space-y-1 overflow-y-auto overflow-x-hidden"
          style={{ padding: navPad }}
        >
          {shouldShowBackButton && (
            <button
              type="button"
              onClick={() => navigate('/cases')}
              className={`unified-sidebar__link mb-2 ${isCollapsed ? 'justify-center px-2 py-3' : 'gap-3 px-4 py-3'}`}
            >
              <FolderOpen className="unified-sidebar__link-icon w-5 h-5" aria-hidden />
              {!isCollapsed && <span className="flex-1 text-left">Дела</span>}
            </button>
          )}

          {renderedNavItems.map((item) => {
            const Icon = item.icon
            const active = isActive(item.path)

            return (
              <button
                key={`${item.id}:${item.path}`}
                type="button"
                onClick={() => navigate(item.path)}
                className={`
                  unified-sidebar__link
                  ${active ? 'unified-sidebar__link--active' : ''}
                  ${isCollapsed ? 'justify-center px-2 py-3' : 'gap-3 px-4 py-3'}
                `}
              >
                <span className="unified-sidebar__accent" aria-hidden />
                <Icon className="unified-sidebar__link-icon w-5 h-5" aria-hidden />
                {!isCollapsed && <span className="flex-1 text-left">{item.label}</span>}
              </button>
            )
          })}

          {showInternalSidebarLinks &&
            showLegalCorpusItem &&
            !navItems.some((item) => item.path === '/legal-corpus') && (
              <button
                type="button"
                onClick={() => navigate('/legal-corpus')}
                className={`
                unified-sidebar__link
                ${isActive('/legal-corpus') ? 'unified-sidebar__link--active' : ''}
                ${isCollapsed ? 'justify-center px-2 py-3' : 'gap-3 px-4 py-3'}
              `}
              >
                <span className="unified-sidebar__accent" aria-hidden />
                <Scale className="unified-sidebar__link-icon w-5 h-5" aria-hidden />
                {!isCollapsed && <span className="flex-1 text-left">Справочник</span>}
              </button>
            )}

          {!navItems.some((item) => item.path === '/court-practice') && (
              <button
                type="button"
                onClick={() => navigate('/court-practice')}
                className={`
                unified-sidebar__link
                ${isActive('/court-practice') ? 'unified-sidebar__link--active' : ''}
                ${isCollapsed ? 'justify-center px-2 py-3' : 'gap-3 px-4 py-3'}
              `}
              >
                <span className="unified-sidebar__accent" aria-hidden />
                <Gavel className="unified-sidebar__link-icon w-5 h-5" aria-hidden />
                {!isCollapsed && <span className="flex-1 text-left">Суд. практика</span>}
              </button>
            )}

          {showInternalSidebarLinks && !navItems.some((item) => item.path === '/admin/draft-templates') && (
            <button
              type="button"
              onClick={() => navigate('/admin/draft-templates')}
              className={`
                unified-sidebar__link
                ${isActive('/admin/draft-templates') ? 'unified-sidebar__link--active' : ''}
                ${isCollapsed ? 'justify-center px-2 py-3' : 'gap-3 px-4 py-3'}
              `}
            >
              <span className="unified-sidebar__accent" aria-hidden />
              <FileText className="unified-sidebar__link-icon w-5 h-5" aria-hidden />
              {!isCollapsed && <span className="flex-1 text-left">Шаблоны Draft</span>}
            </button>
          )}
        </nav>
      </div>
    </div>
  )
}

export default UnifiedSidebar
