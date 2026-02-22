import { useState, useEffect } from 'react'
import { getCasesList, deleteCase, CasesListResponse } from '../services/api'
import CasesGrid from '../components/Cases/CasesGrid'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { Home, FolderOpen, MessageSquare } from 'lucide-react'
import { toast } from 'sonner'

const CasesListPage = () => {
  const [cases, setCases] = useState<CasesListResponse['cases']>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [currentPage, setCurrentPage] = useState(1)
  const [viewMode, setViewMode] = useState<'grid' | 'list' | 'table'>('grid')
  
  const limit = 20
  
  // Navigation items for main sidebar
  const mainNavItems = [
    { id: 'home', label: 'Главная', icon: Home, path: '/' },
    { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
    { id: 'assistant', label: 'Ассистент', icon: MessageSquare, path: '/assistant' },
  ]
  
  useEffect(() => {
    loadCases()
  }, [currentPage])
  
  const loadCases = async () => {
    setLoading(true)
    try {
      const skip = (currentPage - 1) * limit
      const data = await getCasesList(skip, limit)
      setCases(data.cases || [])
      setTotal(data.total || 0)
    } catch (error: any) {
      console.error('Ошибка при загрузке дел:', error)
    } finally {
      setLoading(false)
    }
  }
  
  const handlePageChange = (page: number) => {
    setCurrentPage(page)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const handleDeleteCase = async (caseId: string) => {
    const caseItem = cases.find(c => c.id === caseId)
    const title = caseItem?.title || 'Без названия'
    if (!window.confirm(`Удалить дело «${title}»?\n\nВсе документы, чаты и анализы будут удалены безвозвратно.`)) {
      return
    }
    try {
      await deleteCase(caseId)
      setCases(prev => prev.filter(c => c.id !== caseId))
      setTotal(prev => prev - 1)
      toast.success('Дело удалено')
    } catch (error: any) {
      console.error('Ошибка при удалении дела:', error)
      toast.error('Не удалось удалить дело')
    }
  }
  
  return (
    <div 
      className="h-screen flex overflow-hidden"
      style={{ backgroundColor: 'var(--color-bg-primary)' }}
    >
      {/* Unified Sidebar */}
      <UnifiedSidebar navItems={mainNavItems} title="Legal AI" />
      
      {/* Main Content Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Content */}
        <div 
          className="flex-1 overflow-auto"
          style={{ backgroundColor: 'var(--color-bg-primary)' }}
        >
          {/* Cases Grid */}
          <div className="animate-fade-in">
            <CasesGrid
              cases={cases}
              total={total}
              loading={loading}
              currentPage={currentPage}
              onPageChange={handlePageChange}
              viewMode={viewMode}
              onViewModeChange={setViewMode}
              onDeleteCase={handleDeleteCase}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

export default CasesListPage
