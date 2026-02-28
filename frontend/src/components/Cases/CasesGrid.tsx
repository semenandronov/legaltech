import { useNavigate } from 'react-router-dom'
import { Plus, Info } from 'lucide-react'
import { CaseListItem } from '../../services/api'
import CaseCard from './CaseCard'
import Pagination from '../UI/Pagination'

interface CasesGridProps {
  cases: CaseListItem[]
  total: number
  loading: boolean
  currentPage: number
  onPageChange: (page: number) => void
  viewMode: 'grid' | 'list' | 'table'
  onViewModeChange: (mode: 'grid' | 'list' | 'table') => void
  onDeleteCase?: (caseId: string) => void
  reviewCounts?: Record<string, number>
}

const CASE_LIMIT = 20

const CasesGrid = ({
  cases,
  total,
  loading,
  currentPage,
  onPageChange,
  onDeleteCase,
  reviewCounts,
}: CasesGridProps) => {
  const navigate = useNavigate()
  const safeCases = cases || []
  const totalPages = Math.ceil(total / CASE_LIMIT)

  return (
    <div className="flex-1 flex flex-col">
      {/* Header */}
      <div
        className="px-8 pt-8 pb-5 border-b"
        style={{ borderBottomColor: 'var(--color-border)' }}
      >
        <h1
          className="text-2xl font-semibold tracking-tight mb-1"
          style={{ color: 'var(--color-text-primary)' }}
        >
          Дела
        </h1>
        <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          Храните и анализируйте тысячи документов
        </p>
      </div>

      {/* Counter */}
      <div className="px-8 pt-4 pb-2 flex items-center gap-1.5">
        <Info className="w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />
        <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
          {loading ? '…' : `${total} из ${CASE_LIMIT} дел`}
        </p>
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-y-auto px-8 pb-8 pt-2">
        {loading && safeCases.length === 0 ? (
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(3, 1fr)', gridAutoRows: '220px' }}>
            <div className="rounded-xl animate-pulse" style={{ border: '1.5px dashed #D1D5DB' }} />
            {[...Array(5)].map((_, i) => (
              <div
                key={i}
                className="rounded-xl border animate-pulse"
                style={{
                  backgroundColor: 'var(--color-bg-elevated)',
                  borderColor: 'var(--color-border)',
                }}
              />
            ))}
          </div>
        ) : (
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: 'repeat(3, 1fr)', gridAutoRows: '220px' }}
          >
            {/* New case card — same size as case cards */}
            <button
              onClick={() => navigate('/cases/new')}
              className="rounded-xl flex flex-col items-center justify-center gap-3 transition-all duration-150 hover:bg-gray-50 group"
              style={{
                border: '1.5px dashed #D1D5DB',
                backgroundColor: 'transparent',
              }}
            >
              <Plus className="w-6 h-6" style={{ color: '#9CA3AF' }} />
              <div className="text-center px-6">
                <p className="text-sm font-medium mb-1" style={{ color: '#374151' }}>
                  Новое дело
                </p>
                <p className="text-xs leading-relaxed" style={{ color: '#9CA3AF' }}>
                  Каждое дело может содержать до 10 000 файлов
                </p>
              </div>
            </button>

            {/* Case cards */}
            {safeCases.map((caseItem) => (
              <CaseCard
                key={caseItem.id}
                caseItem={caseItem}
                onDelete={onDeleteCase}
                reviewCount={reviewCounts?.[caseItem.id] ?? 0}
              />
            ))}
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="mt-8 flex justify-center">
            <Pagination
              currentPage={currentPage}
              totalPages={totalPages}
              onPageChange={onPageChange}
            />
          </div>
        )}
      </div>
    </div>
  )
}

export default CasesGrid
