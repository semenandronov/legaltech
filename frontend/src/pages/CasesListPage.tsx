import { useState, useEffect } from 'react'
import { getCasesList, CasesListResponse } from '../services/api'
import CasesFilters, { FilterState } from '../components/Cases/CasesFilters'
import CasesGrid from '../components/Cases/CasesGrid'
import UnifiedSidebar from '../components/Layout/UnifiedSidebar'
import { Home, FolderOpen, Settings, BarChart3 } from 'lucide-react'

const CasesListPage = () => {
  const [cases, setCases] = useState<CasesListResponse['cases']>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [currentPage, setCurrentPage] = useState(1)
  const [viewMode, setViewMode] = useState<'grid' | 'list' | 'table'>('grid')
  const [filters, setFilters] = useState<FilterState>({
    search: '',
    status: [],
    caseType: [],
    assignedTo: [],
    dateFrom: '',
    dateTo: '',
  })
  
  const limit = 20
  
  // Navigation items for main sidebar
  const mainNavItems = [
    { id: 'home', label: 'Главная', icon: Home, path: '/' },
    { id: 'cases', label: 'Дела', icon: FolderOpen, path: '/cases' },
    { id: 'analytics', label: 'Аналитика', icon: BarChart3, path: '/analytics' },
    { id: 'settings', label: 'Настройки', icon: Settings, path: '/settings' },
  ]
  
  useEffect(() => {
    loadCases()
  }, [currentPage, filters])
  
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
  
  const handleFiltersChange = (newFilters: FilterState) => {
    setFilters(newFilters)
    setCurrentPage(1) // Сброс на первую страницу при изменении фильтров
  }
  
  const handlePageChange = (page: number) => {
    setCurrentPage(page)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  
  return (
    <div className="h-screen flex overflow-hidden bg-[#0F0F23]">
      {/* Unified Sidebar */}
      <UnifiedSidebar navItems={mainNavItems} title="Legal AI" />
      
      {/* Main Content Area with expressive design */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Content with gradient mesh background */}
        <div className="flex-1 content-background overflow-auto">
          <div className="flex h-full">
            {/* Filters Sidebar */}
            <div className="w-[280px] border-r border-[#E5E8EB]/50 bg-white/50 backdrop-blur-subtle">
              <CasesFilters onFiltersChange={handleFiltersChange} />
            </div>
            
            {/* Cases Grid */}
            <div className="flex-1 fade-in-up" style={{ animationDelay: '0.1s' }}>
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
    </div>
  )
}

export default CasesListPage
