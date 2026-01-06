import { useState, useEffect } from 'react'
import { getCasesList, CasesListResponse } from '../services/api'
import CasesGrid from '../components/Cases/CasesGrid'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { Home, FolderOpen } from 'lucide-react'

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
  ]
  
  useEffect(() => {
    loadCases()
  }, [currentPage])
  
  const loadCases = async () => {
    setLoading(true)
    try {
      const skip = (currentPage - 1) * limit
      const data = await getCasesList(skip, limit)
      setCases(data.cases)
      setTotal(data.total)
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
            />
          </div>
        </div>
      </div>
    </div>
  )
}

export default CasesListPage
