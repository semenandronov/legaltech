import { ChevronLeft, ChevronRight } from 'lucide-react'

interface PaginationProps {
  currentPage: number
  totalPages: number
  onPageChange: (page: number) => void
  className?: string
}

const Pagination = ({ currentPage, totalPages, onPageChange, className = '' }: PaginationProps) => {
  const getPageNumbers = () => {
    const pages: (number | string)[] = []
    const maxVisible = 5
    
    if (totalPages <= maxVisible) {
      for (let i = 1; i <= totalPages; i++) {
        pages.push(i)
      }
    } else {
      if (currentPage <= 3) {
        for (let i = 1; i <= 4; i++) {
          pages.push(i)
        }
        pages.push('...')
        pages.push(totalPages)
      } else if (currentPage >= totalPages - 2) {
        pages.push(1)
        pages.push('...')
        for (let i = totalPages - 3; i <= totalPages; i++) {
          pages.push(i)
        }
      } else {
        pages.push(1)
        pages.push('...')
        for (let i = currentPage - 1; i <= currentPage + 1; i++) {
          pages.push(i)
        }
        pages.push('...')
        pages.push(totalPages)
      }
    }
    
    return pages
  }
  
  return (
    <div className={`flex items-center gap-1 ${className}`}>
      <button
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage === 1}
        className="p-2 rounded border border-border bg-secondary text-primary disabled:opacity-50 disabled:cursor-not-allowed hover:bg-tertiary transition-colors"
        aria-label="Предыдущая страница"
      >
        <ChevronLeft className="w-4 h-4" />
      </button>
      
      {getPageNumbers().map((page, index) => {
        if (page === '...') {
          return (
            <span key={index} className="px-2 text-secondary">
              ...
            </span>
          )
        }
        
        const pageNum = page as number
        const isActive = pageNum === currentPage
        
        return (
          <button
            key={index}
            onClick={() => onPageChange(pageNum)}
            className={`px-3 py-2 rounded text-body font-medium transition-colors ${
              isActive
                ? 'bg-primary text-white'
                : 'border border-border bg-secondary text-primary hover:bg-tertiary'
            }`}
          >
            {pageNum}
          </button>
        )
      })}
      
      <button
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage === totalPages}
        className="p-2 rounded border border-border bg-secondary text-primary disabled:opacity-50 disabled:cursor-not-allowed hover:bg-tertiary transition-colors"
        aria-label="Следующая страница"
      >
        <ChevronRight className="w-4 h-4" />
      </button>
    </div>
  )
}

export default Pagination
