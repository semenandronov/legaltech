import { useNavigate, useLocation } from 'react-router-dom'
import {
  FolderOpen,
  PanelLeft,
  Scale,
  FileText,
  Gavel,
  ChevronsUpDown,
  LogOut,
  type LucideIcon,
} from 'lucide-react'
import { useState, useEffect } from 'react'
import { fetchLegalCorpusStatus } from '../../services/api'
import { useAuth } from '../../contexts/AuthContext'
import { canAccessInternalDevTools } from '../../utils/internalDevToolsAccess'
import { productFeatures } from '@/lib/productFeatures'
import { cn } from '@/lib/utils'
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
  variant?: 'default' | 'tabular'
}

const SIDEBAR_STATE_KEY = 'unified-sidebar-collapsed'
const LEGAL_CORPUS_UPLOADER_CACHE_KEY = 'legal-corpus-is-uploader'

const UnifiedSidebar = ({
  navItems,
  title = 'Legal AI',
  showBackButton: _showBackButton = true,
  forceCollapsed = false,
  variant: _variant = 'default',
}: UnifiedSidebarProps) => {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuth()
  const showInternalSidebarLinks = canAccessInternalDevTools(user?.email)
  const [showLegalCorpusItem, setShowLegalCorpusItem] = useState(() => {
    return localStorage.getItem(LEGAL_CORPUS_UPLOADER_CACHE_KEY) === '1'
  })
  const showLegalCorpusNav =
    productFeatures.legalCorpusPages && showInternalSidebarLinks && showLegalCorpusItem
  const showCourtPracticeNav = productFeatures.courtPracticePages
  const showDraftTemplatesNav = productFeatures.draftTemplates && showInternalSidebarLinks
  const [userCollapsed, setUserCollapsed] = useState(() => {
    const saved = localStorage.getItem(SIDEBAR_STATE_KEY)
    return saved === 'true'
  })
  const [shouldAnimate, setShouldAnimate] = useState(false)
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)

  const isCollapsed = forceCollapsed || userCollapsed
  const isOpen = !isCollapsed

  const isActive = (path: string) => {
    return location.pathname === path || location.pathname.startsWith(path + '/')
  }

  const isInsideCase =
    /^\/cases\/[^/]+/.test(location.pathname) &&
    !location.pathname.startsWith('/cases/new')

  /** «Дела» — назад к списку внутри дела; не дублировать, если уже есть в navItems. */
  const shouldShowCasesBackLink =
    isInsideCase && !navItems.some((item) => item.path === '/cases')

  type SidebarLink = { id: string; label: string; icon: LucideIcon; path: string }

  const extraLinks: SidebarLink[] = []
  if (showLegalCorpusNav && !navItems.some((item) => item.path === '/legal-corpus')) {
    extraLinks.push({ id: 'legal-corpus', label: 'Справочник', icon: Scale, path: '/legal-corpus' })
  }
  if (showCourtPracticeNav && !navItems.some((item) => item.path === '/court-practice')) {
    extraLinks.push({ id: 'court-practice', label: 'Суд. практика', icon: Gavel, path: '/court-practice' })
  }
  if (showDraftTemplatesNav && !navItems.some((item) => item.path === '/admin/draft-templates')) {
    extraLinks.push({
      id: 'draft-templates',
      label: 'Шаблоны Draft',
      icon: FileText,
      path: '/admin/draft-templates',
    })
  }

  const allLinks: SidebarLink[] = [
    ...(shouldShowCasesBackLink
      ? [{ id: 'back-cases', label: 'Дела', icon: FolderOpen, path: '/cases' }]
      : []),
    ...navItems,
    ...extraLinks,
  ]

  useEffect(() => {
    if (!forceCollapsed) {
      localStorage.setItem(SIDEBAR_STATE_KEY, String(userCollapsed))
    }
  }, [userCollapsed, forceCollapsed])

  useEffect(() => {
    if (isOpen) setShouldAnimate(true)
  }, [isOpen])

  useEffect(() => {
    if (!isUserMenuOpen) return
    const handleClickOutside = () => setIsUserMenuOpen(false)
    document.addEventListener('click', handleClickOutside)
    return () => document.removeEventListener('click', handleClickOutside)
  }, [isUserMenuOpen])

  useEffect(() => {
    let active = true
    const loadLegalCorpusStatus = async () => {
      try {
        const status = await fetchLegalCorpusStatus()
        const isUploader = Boolean(status.is_uploader)
        if (active) setShowLegalCorpusItem(isUploader)
        localStorage.setItem(LEGAL_CORPUS_UPLOADER_CACHE_KEY, isUploader ? '1' : '0')
      } catch {
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
    if (forceCollapsed) return
    setUserCollapsed((prev) => !prev)
  }

  const getUserInitials = () => {
    if (user?.full_name) return user.full_name.charAt(0).toUpperCase()
    if (user?.email) return user.email.charAt(0).toUpperCase()
    return '?'
  }

  const getDisplayName = () => {
    if (!user) return ''
    return user.full_name || user.email.split('@')[0] || ''
  }

  const handleLogout = async () => {
    setIsUserMenuOpen(false)
    await logout()
    navigate('/login')
  }

  const glassPanelClass =
    'bg-white/65 border border-white/70 shadow-[0_-2px_7px_rgba(15,23,42,0.044),0_5px_12px_rgba(15,23,42,0.095),inset_0_1px_0_rgba(255,255,255,0.85)] backdrop-blur-2xl'

  const isTabular = _variant === 'tabular'

  return (
    <div
      className={cn(
        'unified-sidebar shrink-0 flex flex-col z-[99] relative',
        isOpen ? 'unified-sidebar--expanded' : 'unified-sidebar--collapsed',
        'h-[calc(100dvh-1rem)] md:h-[calc(100dvh-1.5rem)]',
        !isOpen && !forceCollapsed && 'max-md:hidden',
        'my-2 ml-2 md:my-3 md:ml-3 mr-0 rounded-2xl',
        isTabular && isOpen && 'md:mr-1',
        glassPanelClass,
      )}
    >
      <div
        className={cn(
          'flex items-center min-h-[3.25rem] px-2.5 py-3',
          isOpen ? 'justify-between' : 'justify-start',
          !isOpen && !forceCollapsed && 'hidden md:flex',
        )}
      >
        <div
          className={cn(
            'flex items-center gap-1.5 min-w-0',
            !isOpen && 'sr-only',
          )}
          aria-hidden={!isOpen}
        >
          <span className="text-xl leading-none shrink-0">⚖️</span>
          <button
            type="button"
            onClick={() => navigate('/cases')}
            className={cn(
              'border-0 bg-transparent p-0 cursor-pointer text-left min-w-0',
              'hover:opacity-80 transition-opacity',
            )}
          >
            <span
              className={cn(
                'unified-sidebar-label block text-2xl font-light font-serif text-gray-900 truncate',
                shouldAnimate && isOpen && 'unified-sidebar-fade-in',
              )}
            >
              {title}
            </span>
          </button>
        </div>
        {!forceCollapsed && (
          <button
            type="button"
            onClick={toggleCollapse}
            className="h-9 w-9 p-2.5 flex items-center justify-center rounded-md hover:bg-gray-100 transition-colors text-gray-700 shrink-0"
            aria-label={isOpen ? 'Свернуть меню' : 'Развернуть меню'}
          >
            <PanelLeft className="h-4 w-4" />
          </button>
        )}
      </div>

      <nav className="flex flex-col min-h-0 flex-1 overflow-y-auto overflow-x-hidden pb-2">
        {allLinks.map((item) => {
          const Icon = item.icon
          const active = isActive(item.path)

          return (
            <div key={`${item.id}:${item.path}`} className="py-0.5 px-2.5">
              <button
                type="button"
                onClick={() => navigate(item.path)}
                aria-label={!isOpen ? item.label : undefined}
                className={cn(
                  'w-full h-9 flex items-center gap-3 px-2.5 py-2 rounded-md transition-colors text-left border-0 cursor-pointer',
                  active ? 'bg-gray-200/60 text-gray-900' : 'text-gray-700 hover:bg-gray-100',
                  !isOpen && !forceCollapsed && 'hidden md:flex',
                )}
              >
                <Icon
                  className={cn(
                    'h-4 w-4 flex-shrink-0',
                    active ? 'text-gray-900' : 'text-black',
                  )}
                  aria-hidden
                />
                <span
                  className={cn(
                    'unified-sidebar-label text-sm font-medium truncate',
                    shouldAnimate && isOpen && 'unified-sidebar-fade-in-2',
                  )}
                >
                  {item.label}
                </span>
              </button>
            </div>
          )
        })}
      </nav>

      {user && (
        <div className="mt-auto p-1 shrink-0">
          <div className="relative">
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                setIsUserMenuOpen((open) => !open)
              }}
              className={cn(
                'flex items-center transition-colors w-full px-2.5 py-3 border-t border-white/60 rounded-xl cursor-pointer gap-3',
                isUserMenuOpen ? 'bg-gray-200/60' : 'hover:bg-gray-100',
                !isOpen && !forceCollapsed && 'hidden md:flex',
              )}
              aria-label={!isOpen ? getDisplayName() || user.email : undefined}
            >
              <span
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-900 text-sm font-medium text-white"
                aria-hidden
              >
                {getUserInitials()}
              </span>
              <span className="min-w-0 flex-1 text-left unified-sidebar-label">
                <span
                  className={cn(
                    'block truncate text-sm font-medium text-gray-900',
                    shouldAnimate && isOpen && 'unified-sidebar-fade-in',
                  )}
                >
                  {getDisplayName()}
                </span>
                <span
                  className={cn(
                    'block truncate text-xs text-gray-500',
                    shouldAnimate && isOpen && 'unified-sidebar-fade-in-2',
                  )}
                >
                  {user.email}
                </span>
              </span>
              <ChevronsUpDown
                className={cn(
                  'h-4 w-4 shrink-0 text-gray-400 unified-sidebar-label',
                  shouldAnimate && isOpen && 'unified-sidebar-fade-in-2',
                )}
                aria-hidden
              />
            </button>

            {isUserMenuOpen && isOpen && (
              <div
                className="absolute bottom-full left-1 mb-1 w-full min-w-[12rem] rounded-xl border border-white/70 bg-white/90 p-1 shadow-lg backdrop-blur-xl z-50"
                onClick={(event) => event.stopPropagation()}
              >
                <button
                  type="button"
                  onClick={() => void handleLogout()}
                  className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-gray-700 hover:bg-white/70 transition-colors border-0 bg-transparent cursor-pointer"
                >
                  <LogOut className="h-4 w-4 shrink-0" aria-hidden />
                  Выйти
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default UnifiedSidebar
