import { useState } from 'react'
import { LayoutGrid, List, Table2, Plus } from 'lucide-react'
import { CaseListItem } from '../../services/api'
import CaseCard from './CaseCard'
import Pagination from '../UI/Pagination'
import { Skeleton } from '../UI/Skeleton'
import { Button } from '../UI/Button'
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
      <div className="flex-1 flex flex-col">
        <div className="p-6 border-b border-border flex items-center justify-between">
          <h2 className="text-h2 text-primary">
            📋 Дела
          </h2>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setIsUploadDialogOpen(true)}
          >
            <Plus className="w-4 h-4 mr-2" />
            Создать дело
          </Button>
        </div>
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <div className="text-6xl mb-4">📁</div>
            <h3 className="text-h3 text-primary mb-2">Нет дел</h3>
            <p className="text-body text-secondary mb-4">Загрузите документы, чтобы создать первое дело</p>
            <Button
              variant="primary"
              onClick={() => setIsUploadDialogOpen(true)}
            >
              <Plus className="w-4 h-4 mr-2" />
              Создать первое дело
            </Button>
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
      <div className="p-6 border-b border-border flex items-center justify-between">
        <h2 className="text-h2 text-primary">
          📋 Дела ({total} результатов)
        </h2>
        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            onClick={() => setIsUploadDialogOpen(true)}
          >
            <Plus className="w-4 h-4 mr-2" />
            Создать дело
          </Button>
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
          <Button
            variant={viewMode === 'table' ? 'primary' : 'secondary'}
            size="sm"
            onClick={() => onViewModeChange('table')}
          >
            <Table2 className="w-4 h-4" />
          </Button>
        </div>
      </div>
      
      {/* Grid/List/Table */}
      <div className="flex-1 overflow-y-auto p-6">
        {viewMode === 'table' ? (
          <CasesTable data={cases} loading={loading} />
        ) : viewMode === 'grid' ? (
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
      {totalPages > 1 && viewMode !== 'table' && (
        <div className="p-6 border-t border-border flex justify-center">
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
