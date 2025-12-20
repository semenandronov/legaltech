import { useState, useEffect } from 'react'
import { getCasesList, CasesListResponse } from '../services/api'
import MainLayout from '../components/Layout/MainLayout'
import CasesFilters, { FilterState } from '../components/Cases/CasesFilters'
import CasesGrid from '../components/Cases/CasesGrid'

const CasesListPage = () => {
  const [cases, setCases] = useState<CasesListResponse['cases']>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [currentPage, setCurrentPage] = useState(1)
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
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
    <MainLayout>
      <div className="flex h-full">
        <CasesFilters onFiltersChange={handleFiltersChange} />
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
    </MainLayout>
  )
}

export default CasesListPage
