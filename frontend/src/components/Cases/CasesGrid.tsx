import { useState } from 'react'
import { LayoutGrid, List, Table2, Plus } from 'lucide-react'
import { CaseListItem } from '../../services/api'
import CaseCard from './CaseCard'
import Pagination from '../UI/Pagination'
import { CasesTable } from './CasesTable'
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from '@mui/material'
import UploadArea from '../UploadArea'

interface CasesGridProps {
  cases: CaseListItem[]
  total: number
  loading: boolean
  currentPage: number
  onPageChange: (page: number) => void
  viewMode: 'grid' | 'list' | 'table'
  onViewModeChange: (mode: 'grid' | 'list' | 'table') => void
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
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false)
  const limit = 20
  const totalPages = Math.ceil(total / limit)

  const handleUploadComplete = (_caseId: string, _fileNames: string[]) => {
    setIsUploadDialogOpen(false)
    // Перезагрузить список дел можно через обновление страницы или callback
    window.location.reload()
  }
  
  if (loading && cases.length === 0) {
    return (
      <div className="flex-1 p-8" style={{ padding: 'var(--space-8)' }}>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[...Array(6)].map((_, i) => (
            <div 
              key={i} 
              className="rounded-xl p-6 border h-[200px] animate-pulse"
              style={{ 
                backgroundColor: 'var(--color-bg-elevated)',
                borderColor: 'var(--color-border)',
                padding: 'var(--space-6)'
              }}
            >
              <div 
                className="h-6 rounded mb-4 w-3/4"
                style={{ backgroundColor: 'var(--color-bg-tertiary)' }}
              />
              <div 
                className="h-4 rounded mb-2 w-1/2"
                style={{ backgroundColor: 'var(--color-bg-tertiary)' }}
              />
              <div 
                className="h-4 rounded w-2/3"
                style={{ backgroundColor: 'var(--color-bg-tertiary)' }}
              />
            </div>
          ))}
        </div>
      </div>
    )
  }
  
  if (cases.length === 0) {
    return (
      <div className="flex-1 flex flex-col">
        <div 
          className="p-8 border-b flex items-center justify-between"
          style={{ 
            padding: 'var(--space-8)',
            borderBottomColor: 'var(--color-border)',
            backgroundColor: 'var(--color-bg-primary)'
          }}
        >
          <div>
            <h2 
              className="text-3xl font-display mb-1 tracking-tight"
              style={{ 
                fontFamily: 'var(--font-display)',
                color: 'var(--color-text-primary)',
                letterSpacing: 'var(--tracking-tight)'
              }}
            >
              Дела
            </h2>
            <p 
              className="text-sm font-medium"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              Начните работу с первым делом
            </p>
          </div>
          <button
            onClick={() => setIsUploadDialogOpen(true)}
            className="px-5 py-2.5 rounded-lg font-medium text-sm transition-all duration-150 flex items-center gap-2"
            style={{
              backgroundColor: 'var(--color-accent)',
              color: 'var(--color-bg-primary)',
            }}
          >
            <Plus className="w-4 h-4" />
            Создать дело
          </button>
        </div>
        <div className="flex-1 flex items-center justify-center fade-in">
          <div className="text-center max-w-md">
            <div className="text-7xl mb-6 scale-in" style={{ animationDelay: '0.1s' }}>📁</div>
            <h3 className="text-2xl font-display text-[#0F1419] mb-3 tracking-tight">Нет дел</h3>
            <p className="text-base text-[#666B78] mb-8 leading-relaxed">
              Загрузите документы, чтобы создать первое дело и начать работу с AI-ассистентом
            </p>
            <button
              onClick={() => setIsUploadDialogOpen(true)}
              className="px-6 py-3 rounded-lg font-medium text-base transition-all duration-150 flex items-center gap-2 mx-auto"
              style={{
                backgroundColor: 'var(--color-accent)',
                color: 'var(--color-bg-primary)',
              }}
            >
              <Plus className="w-5 h-5" />
              Создать первое дело
            </button>
          </div>
        </div>
        <Dialog 
          open={isUploadDialogOpen} 
          onClose={() => setIsUploadDialogOpen(false)}
          maxWidth="lg"
          fullWidth
        >
          <DialogTitle>Создать новое дело</DialogTitle>
          <DialogContent sx={{ maxHeight: '90vh', overflowY: 'auto' }}>
            <UploadArea onUpload={handleUploadComplete} />
          </DialogContent>
        </Dialog>
      </div>
    )
  }
  
  return (
    <div className="flex-1 flex flex-col">
      {/* Header */}
      <div 
        className="p-8 border-b flex items-center justify-between"
        style={{ 
          padding: 'var(--space-8)',
          borderBottomColor: 'var(--color-border)',
          backgroundColor: 'var(--color-bg-primary)'
        }}
      >
        <div>
          <h2 
            className="text-3xl font-display mb-1 tracking-tight"
            style={{ 
              fontFamily: 'var(--font-display)',
              color: 'var(--color-text-primary)',
              letterSpacing: 'var(--tracking-tight)'
            }}
          >
            Дела
          </h2>
          <p 
            className="text-sm font-medium"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {total} {total === 1 ? 'результат' : total < 5 ? 'результата' : 'результатов'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setIsUploadDialogOpen(true)}
            className="px-4 py-2 rounded-lg font-medium text-sm transition-all duration-150 flex items-center gap-2"
            style={{
              backgroundColor: 'var(--color-accent)',
              color: 'var(--color-bg-primary)',
            }}
          >
            <Plus className="w-4 h-4" />
            Создать дело
          </button>
          <div 
            className="flex items-center gap-1 rounded-lg p-1 border"
            style={{
              backgroundColor: 'var(--color-bg-elevated)',
              borderColor: 'var(--color-border)'
            }}
          >
            <button
              onClick={() => onViewModeChange('grid')}
              className={`p-2 rounded-md transition-all duration-150 ${
                viewMode === 'grid'
                  ? 'text-text-primary'
                  : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
              }`}
              style={{
                backgroundColor: viewMode === 'grid' ? 'var(--color-bg-active)' : 'transparent',
                color: viewMode === 'grid' ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
              }}
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
            <button
              onClick={() => onViewModeChange('list')}
              className={`p-2 rounded-md transition-all duration-150 ${
                viewMode === 'list'
                  ? 'text-text-primary'
                  : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
              }`}
              style={{
                backgroundColor: viewMode === 'list' ? 'var(--color-bg-active)' : 'transparent',
                color: viewMode === 'list' ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
              }}
            >
              <List className="w-4 h-4" />
            </button>
            <button
              onClick={() => onViewModeChange('table')}
              className={`p-2 rounded-md transition-all duration-150 ${
                viewMode === 'table'
                  ? 'text-text-primary'
                  : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
              }`}
              style={{
                backgroundColor: viewMode === 'table' ? 'var(--color-bg-active)' : 'transparent',
                color: viewMode === 'table' ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
              }}
            >
              <Table2 className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
      
      {/* Grid/List/Table */}
      <div className="flex-1 overflow-y-auto p-8">
        {viewMode === 'table' ? (
          <CasesTable data={cases} loading={loading} />
        ) : viewMode === 'grid' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {cases.map((caseItem, index) => (
              <div 
                key={caseItem.id} 
                className="stagger-item"
                style={{ animationDelay: `${index * 0.05}s` }}
              >
                <CaseCard caseItem={caseItem} />
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-4">
            {cases.map((caseItem, index) => (
              <div 
                key={caseItem.id}
                className="stagger-item"
                style={{ animationDelay: `${index * 0.03}s` }}
              >
                <CaseCard caseItem={caseItem} />
              </div>
            ))}
          </div>
        )}
      </div>
      
      {/* Pagination */}
      {totalPages > 1 && viewMode !== 'table' && (
        <div 
          className="p-6 border-t flex justify-center"
          style={{ 
            padding: 'var(--space-6)',
            borderTopColor: 'var(--color-border)'
          }}
        >
          <Pagination
            currentPage={currentPage}
            totalPages={totalPages}
            onPageChange={onPageChange}
          />
        </div>
      )}

      {/* Upload Dialog */}
      <Dialog 
        open={isUploadDialogOpen} 
        onClose={() => setIsUploadDialogOpen(false)}
        maxWidth="lg"
        fullWidth
      >
        <DialogTitle>Создать новое дело</DialogTitle>
        <DialogContent sx={{ maxHeight: '90vh', overflowY: 'auto' }}>
          <UploadArea onUpload={handleUploadComplete} />
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default CasesGrid
