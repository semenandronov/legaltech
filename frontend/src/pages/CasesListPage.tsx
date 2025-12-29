import { useState, useEffect } from 'react'
import { getCasesList, CasesListResponse } from '../services/api'
import CasesFilters, { FilterState } from '../components/Cases/CasesFilters'
import CasesGrid from '../components/Cases/CasesGrid'

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
    <div className="h-screen bg-background flex overflow-hidden">
      <CasesFilters onFiltersChange={handleFiltersChange} />
      <div className="flex-1 flex flex-col overflow-hidden">
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
  )
}

export default CasesListPage
