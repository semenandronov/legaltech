import { useState } from 'react'
import { LayoutGrid, List } from 'lucide-react'
import { CaseListItem, CasesListResponse } from '../../services/api'
import CaseCard from './CaseCard'
import Pagination from '../UI/Pagination'
import Skeleton from '../UI/Skeleton'
import Button from '../UI/Button'

interface CasesGridProps {
  cases: CaseListItem[]
  total: number
  loading: boolean
  currentPage: number
  onPageChange: (page: number) => void
  viewMode: 'grid' | 'list'
  onViewModeChange: (mode: 'grid' | 'list') => void
}

const CasesGrid = ({
  cases,
  total,
  loading,
  currentPage,
  onPageChange,
  viewMode,
  onViewModeChange,
}: CasesGridProps) => {
  const limit = 20
  const totalPages = Math.ceil(total / limit)
  
  if (loading && cases.length === 0) {
    return (
      <div className="flex-1 p-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <Skeleton key={i} variant="rectangular" height={200} />
          ))}
        </div>
      </div>
    )
  }
  
  if (cases.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <div className="text-6xl mb-4">📁</div>
          <h3 className="text-h3 text-primary mb-2">Нет дел</h3>
          <p className="text-body text-secondary">Загрузите документы, чтобы создать первое дело</p>
        </div>
      </div>
    )
  }
  
  return (
    <div className="flex-1 flex flex-col">
      {/* Header */}
      <div className="p-6 border-b border-border flex items-center justify-between">
        <h2 className="text-h2 text-primary">
          📋 Дела ({total} результатов)
        </h2>
        <div className="flex items-center gap-2">
          <Button
            variant={viewMode === 'grid' ? 'primary' : 'secondary'}
            size="sm"
            onClick={() => onViewModeChange('grid')}
          >
            <LayoutGrid className="w-4 h-4" />
          </Button>
          <Button
            variant={viewMode === 'list' ? 'primary' : 'secondary'}
            size="sm"
            onClick={() => onViewModeChange('list')}
          >
            <List className="w-4 h-4" />
          </Button>
        </div>
      </div>
      
      {/* Grid/List */}
      <div className="flex-1 overflow-y-auto p-6">
        {viewMode === 'grid' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {cases.map((caseItem) => (
              <CaseCard key={caseItem.id} caseItem={caseItem} />
            ))}
          </div>
        ) : (
          <div className="space-y-4">
            {cases.map((caseItem) => (
              <CaseCard key={caseItem.id} caseItem={caseItem} />
            ))}
          </div>
        )}
      </div>
      
      {/* Pagination */}
      {totalPages > 1 && (
        <div className="p-6 border-t border-border flex justify-center">
          <Pagination
            currentPage={currentPage}
            totalPages={totalPages}
            onPageChange={onPageChange}
          />
        </div>
      )}
    </div>
  )
}

export default CasesGrid
